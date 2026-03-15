"""Tests for the normalization toggle (Issue #6)."""

import sys
import tempfile
import types
import unittest
import importlib.util
from pathlib import Path
from unittest.mock import patch

if importlib.util.find_spec("pydub") is None or importlib.util.find_spec("typer") is None:
    raise unittest.SkipTest("Normalization tests require pydub and typer.")

from pydub import AudioSegment

from podvoice.audio import build_podcast, _normalize

# Provide a lightweight stub for podvoice.tts so importing podvoice.cli
# does not pull in the heavy Coqui TTS stack (which may be broken on
# some Python versions).
_tts_stub = types.ModuleType("podvoice.tts")


class _StubEngine:
    def __init__(self, **kwargs):
        pass


_tts_stub.XTTSVoiceEngine = _StubEngine  # type: ignore[attr-defined]
sys.modules.setdefault("podvoice.tts", _tts_stub)

from podvoice import cli  # noqa: E402  (after stub)


class BuildPodcastNormalizationTests(unittest.TestCase):
    """Unit tests for the normalize parameter on build_podcast."""

    def test_normalization_applied_by_default(self) -> None:
        segments = [AudioSegment.silent(duration=100)]
        with patch("podvoice.audio._normalize", wraps=_normalize) as mock_norm:
            build_podcast(segments)
        mock_norm.assert_called_once()

    def test_normalization_skipped_when_false(self) -> None:
        segments = [AudioSegment.silent(duration=100)]
        with patch("podvoice.audio._normalize") as mock_norm:
            build_podcast(segments, normalize=False)
        mock_norm.assert_not_called()


class _FakeEngine:
    def __init__(self, **kwargs):
        pass

    def cache_key_for_segment(self, segment):
        return f"{segment.speaker}_{len(segment.text)}"

    def synthesize_to_audiosegment(self, segment):
        return AudioSegment.silent(duration=50)


class CliSkipNormalizeTests(unittest.TestCase):
    """CLI integration tests for --skip-normalize."""

    def setUp(self) -> None:
        from typer.testing import CliRunner

        self.runner = CliRunner()

    def _write_script(self, tmp_dir: str) -> Path:
        script = Path(tmp_dir) / "script.md"
        script.write_text("[Host | calm]\nHello world\n", encoding="utf-8")
        return script

    def test_default_render_normalizes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            script = self._write_script(tmp_dir)

            with patch("podvoice.cli.XTTSVoiceEngine", _FakeEngine), \
                 patch("podvoice.cli.export_audio"), \
                 patch("podvoice.audio._normalize", wraps=_normalize) as mock_norm:
                result = self.runner.invoke(
                    cli.app, ["render", str(script), "--no-cache"]
                )

            self.assertEqual(0, result.exit_code, result.output)
            mock_norm.assert_called_once()

    def test_skip_normalize_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            script = self._write_script(tmp_dir)

            with patch("podvoice.cli.XTTSVoiceEngine", _FakeEngine), \
                 patch("podvoice.cli.export_audio"), \
                 patch("podvoice.audio._normalize") as mock_norm:
                result = self.runner.invoke(
                    cli.app,
                    ["render", str(script), "--no-cache", "--skip-normalize"],
                )

            self.assertEqual(0, result.exit_code, result.output)
            mock_norm.assert_not_called()


if __name__ == "__main__":
    unittest.main()
