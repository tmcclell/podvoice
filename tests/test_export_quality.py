"""Tests for export quality presets (Issue #5)."""

import tempfile
import unittest
import importlib.util
from pathlib import Path
from unittest.mock import patch, ANY

if importlib.util.find_spec("pydub") is None or importlib.util.find_spec("typer") is None:
    raise unittest.SkipTest("Export quality tests require pydub and typer.")

from pydub import AudioSegment

from podvoice.audio import export_audio


class ExportQualityTests(unittest.TestCase):
    """Unit tests for the quality parameter on export_audio."""

    def test_draft_uses_96k_bitrate(self) -> None:
        audio = AudioSegment.silent(duration=100)
        with tempfile.TemporaryDirectory() as tmp_dir:
            out = Path(tmp_dir) / "out.mp3"
            with patch.object(AudioSegment, "export") as mock_export:
                export_audio(audio, out, quality="draft")
            mock_export.assert_called_once_with(out, format="mp3", bitrate="96k")

    def test_final_uses_192k_bitrate(self) -> None:
        audio = AudioSegment.silent(duration=100)
        with tempfile.TemporaryDirectory() as tmp_dir:
            out = Path(tmp_dir) / "out.mp3"
            with patch.object(AudioSegment, "export") as mock_export:
                export_audio(audio, out, quality="final")
            mock_export.assert_called_once_with(out, format="mp3", bitrate="192k")

    def test_default_uses_128k_bitrate(self) -> None:
        audio = AudioSegment.silent(duration=100)
        with tempfile.TemporaryDirectory() as tmp_dir:
            out = Path(tmp_dir) / "out.mp3"
            with patch.object(AudioSegment, "export") as mock_export:
                export_audio(audio, out)
            mock_export.assert_called_once_with(out, format="mp3", bitrate="128k")

    def test_wav_ignores_quality(self) -> None:
        audio = AudioSegment.silent(duration=100)
        with tempfile.TemporaryDirectory() as tmp_dir:
            out = Path(tmp_dir) / "out.wav"
            with patch.object(AudioSegment, "export") as mock_export:
                export_audio(audio, out, quality="draft")
            mock_export.assert_called_once_with(out, format="wav")


if __name__ == "__main__":
    unittest.main()
