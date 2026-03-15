"""Daemon mode for podvoice — keeps the TTS model loaded between requests.

The daemon is a lightweight HTTP server built on Python's stdlib
``http.server`` so that the expensive XTTS model load is amortized
across multiple render requests.
"""

from __future__ import annotations

import json
import logging
import signal
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

from pydub import AudioSegment

from .parser import parse_markdown_script, merge_adjacent_segments
from .tts import XTTSVoiceEngine
from .audio import build_podcast, export_audio
from .utils import (
    PodvoiceError,
    ScriptParseError,
    SynthesisError,
    get_default_cache_dir,
)

logger = logging.getLogger("podvoice.daemon")


class PodvoiceDaemon:
    """Manages the TTS engine and HTTP server lifecycle.

    The model is loaded once during ``__init__`` and reused for every
    incoming render request, eliminating the per-invocation load overhead.
    """

    def __init__(
        self,
        language: str = "en",
        device: str = "cpu",
        cpu_threads: int | None = None,
        host: str = "127.0.0.1",
        port: int = 8473,
    ) -> None:
        self.language = language
        self.device = device
        self.host = host
        self.port = port
        self._start_time: float | None = None
        self._server: HTTPServer | None = None

        if cpu_threads is not None:
            import torch

            torch.set_num_threads(cpu_threads)

        logger.info("Loading XTTS v2 model on device '%s'…", device)
        load_start = time.perf_counter()
        self.engine = XTTSVoiceEngine(language=language, device=device)
        load_elapsed = time.perf_counter() - load_start
        logger.info("Model loaded in %.2fs", load_elapsed)

    def start(self) -> None:
        """Start the HTTP server (blocks until shutdown)."""
        handler = _make_handler(self)
        self._server = HTTPServer((self.host, self.port), handler)
        self._start_time = time.perf_counter()

        # Signal handlers can only be registered from the main thread.
        if threading.current_thread() is threading.main_thread():

            def _shutdown_from_signal(signum: int, frame: Any) -> None:
                logger.info("Received signal %s, shutting down…", signum)
                self.shutdown()

            signal.signal(signal.SIGTERM, _shutdown_from_signal)
            signal.signal(signal.SIGINT, _shutdown_from_signal)

        logger.info("Daemon listening on http://%s:%d", self.host, self.port)
        self._server.serve_forever()
        logger.info("Daemon stopped.")

    def shutdown(self) -> None:
        """Request graceful shutdown of the HTTP server."""
        if self._server is not None:
            threading.Thread(target=self._server.shutdown, daemon=True).start()

    def handle_render(self, params: dict[str, Any]) -> dict[str, Any]:
        """Perform a render using the pre-loaded engine."""
        script_path = Path(params["script_path"])
        output_path = Path(
            params.get("output_path") or script_path.with_suffix(".wav")
        )
        no_cache = params.get("no_cache", False)
        cache_dir_raw = params.get("cache_dir")
        cache_dir = Path(cache_dir_raw) if cache_dir_raw else None
        skip_normalize = params.get("skip_normalize", False)
        gap_ms = params.get("gap_ms", 800)

        raw_text = script_path.read_text(encoding="utf-8")
        segments = parse_markdown_script(raw_text, source=str(script_path))
        segments = merge_adjacent_segments(segments)

        if not segments:
            raise PodvoiceError("Script did not contain any speaker segments.")

        segment_audio, cache_hits = self._synthesize_with_cache(
            segments, no_cache, cache_dir
        )

        if skip_normalize:
            combined = AudioSegment.silent(duration=0)
            gap = AudioSegment.silent(duration=gap_ms)
            for idx, seg in enumerate(segment_audio):
                combined += seg
                if idx < len(segment_audio) - 1:
                    combined += gap
        else:
            combined = build_podcast(segment_audio, gap_ms=gap_ms)

        export_audio(combined, output_path)

        return {
            "output_path": str(output_path),
            "segments": len(segments),
            "cache_hits": cache_hits,
        }

    def _synthesize_with_cache(
        self,
        segments: list,
        no_cache: bool,
        cache_dir: Path | None,
    ) -> tuple[list[AudioSegment], int]:
        """Synthesize segments with optional caching (no Rich UI)."""
        resolved_cache_dir = (
            cache_dir if cache_dir is not None else get_default_cache_dir()
        )
        if not no_cache:
            try:
                resolved_cache_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                no_cache = True

        segment_audio: list[AudioSegment] = []
        cache_hits = 0

        for i, segment in enumerate(segments):
            cache_path: Path | None = None
            if not no_cache:
                cache_key = self.engine.cache_key_for_segment(segment)
                cache_path = resolved_cache_dir / f"{cache_key}.wav"

            if cache_path is not None and cache_path.exists():
                try:
                    audio = AudioSegment.from_file(cache_path)
                    segment_audio.append(audio)
                    cache_hits += 1
                    continue
                except Exception:
                    pass

            audio = self.engine.synthesize_to_audiosegment(segment)
            segment_audio.append(audio)

            if cache_path is not None:
                try:
                    audio.export(cache_path, format="wav")
                except Exception:
                    pass

            logger.info("Synthesized segment %d/%d", i + 1, len(segments))

        return segment_audio, cache_hits

    def get_health(self) -> dict[str, Any]:
        """Return health and status information."""
        uptime = (
            time.perf_counter() - self._start_time if self._start_time else 0
        )
        return {
            "status": "ok",
            "model": self.engine.model_name,
            "language": self.language,
            "device": self.device,
            "uptime_seconds": round(uptime, 2),
        }


def _make_handler(daemon: PodvoiceDaemon) -> type[BaseHTTPRequestHandler]:
    """Create an HTTP request handler class bound to *daemon*."""

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/health":
                self._send_json(200, daemon.get_health())
            else:
                self._send_json(404, {"error": "Not found"})

        def do_POST(self) -> None:
            if self.path == "/render":
                self._handle_render()
            elif self.path == "/shutdown":
                self._send_json(200, {"status": "shutting down"})
                daemon.shutdown()
            else:
                self._send_json(404, {"error": "Not found"})

        def _handle_render(self) -> None:
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length)
                params = json.loads(body) if body else {}
            except (json.JSONDecodeError, ValueError) as exc:
                self._send_json(400, {"error": f"Invalid JSON: {exc}"})
                return

            if "script_path" not in params:
                self._send_json(
                    400, {"error": "Missing required field: script_path"}
                )
                return

            start = time.perf_counter()
            try:
                result = daemon.handle_render(params)
                elapsed = time.perf_counter() - start
                result["elapsed_seconds"] = round(elapsed, 2)
                logger.info("Render completed in %.2fs", elapsed)
                self._send_json(200, result)
            except (ScriptParseError, SynthesisError, PodvoiceError) as exc:
                self._send_json(500, {"error": str(exc)})
            except FileNotFoundError as exc:
                self._send_json(404, {"error": str(exc)})
            except Exception as exc:
                logger.exception("Unexpected error during render")
                self._send_json(500, {"error": f"Internal error: {exc}"})

        def _send_json(self, status_code: int, data: dict[str, Any]) -> None:
            payload = json.dumps(data).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            logger.info(format, *args)

    return _Handler
