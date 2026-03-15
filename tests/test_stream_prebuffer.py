"""Tests for duration-based stream prebuffering (issue #17)."""

import sys
import tempfile
import threading
import unittest
import importlib.util
from pathlib import Path
from queue import Queue
from unittest.mock import patch, MagicMock

if importlib.util.find_spec("pydub") is None or importlib.util.find_spec("typer") is None:
    raise unittest.SkipTest("Stream prebuffer tests require pydub and typer.")

from pydub import AudioSegment

# Ensure podvoice.cli can be imported even when heavy TTS backend deps
# are unavailable (the test mocks the engine anyway).
for _mod in ("TTS", "TTS.api", "torch"):
    sys.modules.setdefault(_mod, MagicMock())

from typer.testing import CliRunner

from podvoice import cli


class _FakeEngine:
    """Fake TTS engine that returns silent audio of a known duration."""

    def __init__(self, language: str = "en", device: str = "cpu", **kwargs) -> None:
        self.language = language
        self.device = device
        self.segment_duration_ms = 2000  # 2 seconds per segment

    def cache_key_for_segment(self, segment) -> str:
        return f"{segment.speaker}_{len(segment.text)}"

    def synthesize_to_audiosegment(self, segment) -> AudioSegment:
        return AudioSegment.silent(duration=self.segment_duration_ms)


class DurationPrebufferTests(unittest.TestCase):
    """Verify that the prebuffer start event uses cumulative duration."""

    def test_prebuffer_fires_when_duration_threshold_met(self) -> None:
        """Playback should start once buffered audio >= stream_prebuffer_ms."""
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as tmp_dir:
            script = Path(tmp_dir) / "script.md"
            # 4 segments × 2 000 ms = 8 000 ms total.
            script.write_text(
                "[Host | calm]\nLine one\n\n"
                "[Guest | happy]\nLine two\n\n"
                "[Host | calm]\nLine three\n\n"
                "[Guest | happy]\nLine four\n",
                encoding="utf-8",
            )

            play_calls: list[AudioSegment] = []

            def fake_play(audio: AudioSegment) -> None:
                play_calls.append(audio)

            with patch("podvoice.cli.XTTSVoiceEngine", _FakeEngine), \
                 patch("podvoice.cli.play_audio", side_effect=fake_play):
                result = runner.invoke(
                    cli.app,
                    [
                        "render",
                        str(script),
                        "--play-stream",
                        "--no-cache",
                        "--stream-prebuffer-ms",
                        "4000",
                    ],
                )

            self.assertEqual(0, result.exit_code, result.output)
            # All 4 segments should have been played.
            self.assertEqual(len(play_calls), 4)

    def test_prebuffer_fires_for_short_script(self) -> None:
        """If total audio < prebuffer threshold, playback starts at last segment."""
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as tmp_dir:
            script = Path(tmp_dir) / "script.md"
            script.write_text("[Host | calm]\nOnly line\n", encoding="utf-8")

            play_calls: list[AudioSegment] = []

            def fake_play(audio: AudioSegment) -> None:
                play_calls.append(audio)

            with patch("podvoice.cli.XTTSVoiceEngine", _FakeEngine), \
                 patch("podvoice.cli.play_audio", side_effect=fake_play):
                result = runner.invoke(
                    cli.app,
                    [
                        "render",
                        str(script),
                        "--play-stream",
                        "--no-cache",
                        "--stream-prebuffer-ms",
                        "999999",
                    ],
                )

            self.assertEqual(0, result.exit_code, result.output)
            self.assertEqual(len(play_calls), 1)

    def test_prebuffer_zero_starts_immediately(self) -> None:
        """With prebuffer 0 ms, playback should start on the first segment."""
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as tmp_dir:
            script = Path(tmp_dir) / "script.md"
            script.write_text(
                "[Host | calm]\nOne\n\n[Guest | happy]\nTwo\n",
                encoding="utf-8",
            )

            play_calls: list[AudioSegment] = []

            def fake_play(audio: AudioSegment) -> None:
                play_calls.append(audio)

            with patch("podvoice.cli.XTTSVoiceEngine", _FakeEngine), \
                 patch("podvoice.cli.play_audio", side_effect=fake_play):
                result = runner.invoke(
                    cli.app,
                    [
                        "render",
                        str(script),
                        "--play-stream",
                        "--no-cache",
                        "--stream-prebuffer-ms",
                        "0",
                    ],
                )

            self.assertEqual(0, result.exit_code, result.output)
            self.assertEqual(len(play_calls), 2)


class CliValidationTests(unittest.TestCase):
    """CLI option validation for the new --stream-prebuffer-ms flag."""

    def setUp(self) -> None:
        self.runner = CliRunner()

    def _write_script(self, tmp_dir: str) -> Path:
        script = Path(tmp_dir) / "script.md"
        script.write_text("[Host | calm]\nHello world\n", encoding="utf-8")
        return script

    def test_negative_prebuffer_ms_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            script = self._write_script(tmp_dir)
            result = self.runner.invoke(
                cli.app,
                [
                    "render",
                    str(script),
                    "--play-stream",
                    "--stream-prebuffer-ms",
                    "-1",
                ],
            )
            self.assertNotEqual(0, result.exit_code)
            self.assertIn("--stream-prebuffer-ms must be >=", result.output)

    def test_deprecated_stream_prebuffer_warns(self) -> None:
        """Using the old --stream-prebuffer flag should print a deprecation warning."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            script = self._write_script(tmp_dir)

            with patch("podvoice.cli.XTTSVoiceEngine", _FakeEngine), \
                 patch("podvoice.cli.play_audio"):
                result = self.runner.invoke(
                    cli.app,
                    [
                        "render",
                        str(script),
                        "--play-stream",
                        "--no-cache",
                        "--stream-prebuffer",
                        "2",
                    ],
                )

            self.assertEqual(0, result.exit_code, result.output)
            self.assertIn("--stream-prebuffer is deprecated", result.output)


if __name__ == "__main__":
    unittest.main()
