import sys
import tempfile
import unittest
import importlib.util
from pathlib import Path
from unittest.mock import patch, MagicMock

if importlib.util.find_spec("pydub") is None or importlib.util.find_spec("typer") is None:
    raise unittest.SkipTest("CLI playback tests require pydub and typer.")

from pydub import AudioSegment

for _mod in ("TTS", "TTS.api", "torch"):
    sys.modules.setdefault(_mod, MagicMock())

from typer.testing import CliRunner

from podvoice import cli


class _FakeEngine:
    def __init__(self, language: str = "en", device: str = "cpu", **kwargs) -> None:
        self.language = language
        self.device = device

    def cache_key_for_segment(self, segment) -> str:
        return f"{segment.speaker}_{len(segment.text)}"

    def synthesize_to_audiosegment(self, segment) -> AudioSegment:
        return AudioSegment.silent(duration=50)


class CliPlaybackModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def _write_script(self, tmp_dir: str) -> Path:
        script = Path(tmp_dir) / "script.md"
        script.write_text("[Host | calm]\nHello world\n", encoding="utf-8")
        return script

    def test_render_defaults_to_export_when_no_play_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            script = self._write_script(tmp_dir)
            expected_out = script.with_suffix(".wav")

            with patch("podvoice.cli.XTTSVoiceEngine", _FakeEngine), patch(
                "podvoice.cli.export_audio"
            ) as export_mock, patch("podvoice.cli.play_audio") as play_mock:
                result = self.runner.invoke(
                    cli.app, ["render", str(script), "--no-cache"]
                )

            self.assertEqual(0, result.exit_code)
            export_mock.assert_called_once()
            play_mock.assert_not_called()
            self.assertEqual(expected_out, export_mock.call_args.args[1])

    def test_render_play_without_out_skips_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            script = self._write_script(tmp_dir)

            with patch("podvoice.cli.XTTSVoiceEngine", _FakeEngine), patch(
                "podvoice.cli.export_audio"
            ) as export_mock, patch("podvoice.cli.play_audio") as play_mock:
                result = self.runner.invoke(
                    cli.app, ["render", str(script), "--play", "--no-cache"]
                )

            self.assertEqual(0, result.exit_code)
            export_mock.assert_not_called()
            play_mock.assert_called_once()

    def test_render_play_stream_without_out_skips_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            script = self._write_script(tmp_dir)

            with patch("podvoice.cli.XTTSVoiceEngine", _FakeEngine), patch(
                "podvoice.cli.export_audio"
            ) as export_mock, patch("podvoice.cli.play_audio") as play_mock:
                result = self.runner.invoke(
                    cli.app, ["render", str(script), "--play-stream", "--no-cache"]
                )

            self.assertEqual(0, result.exit_code)
            export_mock.assert_not_called()
            play_mock.assert_called_once()

    def test_render_rejects_play_and_play_stream_together(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            script = self._write_script(tmp_dir)

            result = self.runner.invoke(
                cli.app,
                ["render", str(script), "--play", "--play-stream", "--no-cache"],
            )

            self.assertNotEqual(0, result.exit_code)
            self.assertIn("Use either --play or --play-stream", result.output)

    def test_render_rejects_negative_stream_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            script = self._write_script(tmp_dir)

            result = self.runner.invoke(
                cli.app,
                [
                    "render",
                    str(script),
                    "--play-stream",
                    "--stream-gap-ms",
                    "-1",
                ],
            )

            self.assertNotEqual(0, result.exit_code)
            self.assertIn("--stream-gap-ms must be >=", result.output)

    def test_render_rejects_negative_stream_prebuffer(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
