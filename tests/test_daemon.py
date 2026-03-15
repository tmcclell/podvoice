"""Tests for the podvoice daemon HTTP server."""

import sys
from unittest.mock import MagicMock

# Pre-populate sys.modules for heavy ML dependencies that may not be
# available in the test environment, allowing podvoice.daemon to be
# imported without loading the actual TTS/model infrastructure.
for _mod in ("torch", "TTS", "TTS.api", "numpy"):
    sys.modules.setdefault(_mod, MagicMock())

import json
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from pydub import AudioSegment

from podvoice.daemon import PodvoiceDaemon


def _find_free_port() -> int:
    """Find an available port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _make_mock_engine() -> MagicMock:
    """Create a mock TTS engine for testing."""
    engine = MagicMock()
    engine.model_name = "test_model"
    engine.language = "en"
    engine.device = "cpu"
    engine.cache_key_for_segment.return_value = "test_cache_key"
    engine.synthesize_to_audiosegment.return_value = AudioSegment.silent(
        duration=100
    )
    return engine


def _wait_for_server(port: int, timeout: float = 5.0) -> None:
    """Wait for the server to start accepting connections."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except (ConnectionRefusedError, OSError):
            time.sleep(0.1)
    raise TimeoutError(f"Server did not start on port {port}")


def _start_daemon(port: int) -> tuple[PodvoiceDaemon, threading.Thread]:
    """Create and start a daemon with a mocked engine in a background thread."""
    with patch("podvoice.daemon.XTTSVoiceEngine") as MockEngine:
        MockEngine.return_value = _make_mock_engine()
        daemon = PodvoiceDaemon(host="127.0.0.1", port=port)
    thread = threading.Thread(target=daemon.start, daemon=True)
    thread.start()
    _wait_for_server(port)
    return daemon, thread


class DaemonHealthTests(unittest.TestCase):
    """Test the /health endpoint."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.port = _find_free_port()
        cls.daemon, cls.thread = _start_daemon(cls.port)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.daemon.shutdown()
        cls.thread.join(timeout=5)

    def test_health_returns_ok_status(self) -> None:
        resp = urlopen(f"http://127.0.0.1:{self.port}/health")
        data = json.loads(resp.read())
        self.assertEqual(data["status"], "ok")

    def test_health_contains_model_info(self) -> None:
        resp = urlopen(f"http://127.0.0.1:{self.port}/health")
        data = json.loads(resp.read())
        self.assertEqual(data["model"], "test_model")
        self.assertEqual(data["language"], "en")
        self.assertEqual(data["device"], "cpu")

    def test_health_contains_uptime(self) -> None:
        resp = urlopen(f"http://127.0.0.1:{self.port}/health")
        data = json.loads(resp.read())
        self.assertIn("uptime_seconds", data)
        self.assertGreaterEqual(data["uptime_seconds"], 0)

    def test_unknown_get_returns_404(self) -> None:
        with self.assertRaises(HTTPError) as ctx:
            urlopen(f"http://127.0.0.1:{self.port}/unknown")
        self.assertEqual(ctx.exception.code, 404)


class DaemonShutdownTests(unittest.TestCase):
    """Test the /shutdown endpoint with a dedicated server instance."""

    def test_shutdown_stops_server(self) -> None:
        port = _find_free_port()
        daemon, thread = _start_daemon(port)

        req = Request(
            f"http://127.0.0.1:{port}/shutdown", data=b"", method="POST"
        )
        resp = urlopen(req)
        data = json.loads(resp.read())
        self.assertEqual(data["status"], "shutting down")

        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())


class DaemonRenderTests(unittest.TestCase):
    """Test the /render endpoint."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.port = _find_free_port()
        cls.daemon, cls.thread = _start_daemon(cls.port)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.daemon.shutdown()
        cls.thread.join(timeout=5)

    @patch("podvoice.daemon.export_audio")
    def test_render_accepts_valid_request(self, mock_export: MagicMock) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            script = Path(tmpdir) / "test.md"
            script.write_text(
                "[Alice | calm]\nHello world\n", encoding="utf-8"
            )
            out = Path(tmpdir) / "out.wav"
            body = json.dumps(
                {
                    "script_path": str(script),
                    "output_path": str(out),
                    "no_cache": True,
                    "skip_normalize": True,
                }
            ).encode()

            req = Request(
                f"http://127.0.0.1:{self.port}/render",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp = urlopen(req)
            data = json.loads(resp.read())

            self.assertEqual(data["segments"], 1)
            self.assertEqual(data["cache_hits"], 0)
            self.assertIn("output_path", data)
            self.assertIn("elapsed_seconds", data)
            mock_export.assert_called_once()

    def test_render_missing_script_path_returns_400(self) -> None:
        body = json.dumps({}).encode()
        req = Request(
            f"http://127.0.0.1:{self.port}/render",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as ctx:
            urlopen(req)
        self.assertEqual(ctx.exception.code, 400)

    def test_render_invalid_json_returns_400(self) -> None:
        req = Request(
            f"http://127.0.0.1:{self.port}/render",
            data=b"not json",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as ctx:
            urlopen(req)
        self.assertEqual(ctx.exception.code, 400)

    def test_render_nonexistent_script_returns_error(self) -> None:
        body = json.dumps(
            {"script_path": "/nonexistent/script.md", "no_cache": True}
        ).encode()
        req = Request(
            f"http://127.0.0.1:{self.port}/render",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as ctx:
            urlopen(req)
        self.assertIn(ctx.exception.code, (404, 500))


class DaemonBindTests(unittest.TestCase):
    """Test that the daemon binds to localhost only by default."""

    def test_default_host_is_localhost(self) -> None:
        with patch("podvoice.daemon.XTTSVoiceEngine") as MockEngine:
            MockEngine.return_value = _make_mock_engine()
            daemon = PodvoiceDaemon()
        self.assertEqual(daemon.host, "127.0.0.1")

    def test_server_binds_to_localhost(self) -> None:
        port = _find_free_port()
        daemon, thread = _start_daemon(port)
        try:
            self.assertEqual(daemon._server.server_address[0], "127.0.0.1")
        finally:
            daemon.shutdown()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
