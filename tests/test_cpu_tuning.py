"""Tests for CPU thread tuning logic (Issue #8)."""

from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# Stub heavy third-party modules so we can import podvoice.tts without
# needing the full Coqui TTS installation to be functional.
_TTS_STUB = types.ModuleType("TTS")
_TTS_API_STUB = types.ModuleType("TTS.api")
_TTS_API_STUB.TTS = MagicMock()  # type: ignore[attr-defined]
sys.modules.setdefault("TTS", _TTS_STUB)
sys.modules.setdefault("TTS.api", _TTS_API_STUB)

from podvoice.tts import _apply_cpu_thread_settings  # noqa: E402


class ApplyCpuThreadSettingsTests(unittest.TestCase):
    """Verify _apply_cpu_thread_settings configures PyTorch threads correctly."""

    @patch("podvoice.tts.torch.set_num_interop_threads")
    @patch("podvoice.tts.torch.set_num_threads")
    def test_explicit_thread_count_is_applied(
        self, mock_threads: object, mock_interop: object
    ) -> None:
        _apply_cpu_thread_settings(4)
        mock_threads.assert_called_once_with(4)
        mock_interop.assert_called_once_with(4)

    @patch("podvoice.tts.torch.set_num_interop_threads")
    @patch("podvoice.tts.torch.set_num_threads")
    def test_none_leaves_defaults(
        self, mock_threads: object, mock_interop: object
    ) -> None:
        _apply_cpu_thread_settings(None)
        mock_threads.assert_not_called()
        mock_interop.assert_not_called()

    @patch("podvoice.tts.torch.set_num_interop_threads")
    @patch("podvoice.tts.torch.set_num_threads")
    def test_single_thread(
        self, mock_threads: object, mock_interop: object
    ) -> None:
        _apply_cpu_thread_settings(1)
        mock_threads.assert_called_once_with(1)
        mock_interop.assert_called_once_with(1)


if __name__ == "__main__":
    unittest.main()
