"""Tests for automatic device selection logic (Issue #7)."""

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

from podvoice.tts import _resolve_device  # noqa: E402


class ResolveDeviceTests(unittest.TestCase):
    """Verify _resolve_device picks the right device under various conditions."""

    # ------------------------------------------------------------------
    # auto / None — CUDA available
    # ------------------------------------------------------------------
    @patch("podvoice.tts.torch.cuda.is_available", return_value=True)
    def test_auto_selects_cuda_when_available(self, _mock: object) -> None:
        self.assertEqual(_resolve_device("auto"), "cuda")

    @patch("podvoice.tts.torch.cuda.is_available", return_value=True)
    def test_none_selects_cuda_when_available(self, _mock: object) -> None:
        self.assertEqual(_resolve_device(None), "cuda")

    # ------------------------------------------------------------------
    # auto / None — CUDA NOT available
    # ------------------------------------------------------------------
    @patch("podvoice.tts.torch.cuda.is_available", return_value=False)
    def test_auto_falls_back_to_cpu(self, _mock: object) -> None:
        self.assertEqual(_resolve_device("auto"), "cpu")

    @patch("podvoice.tts.torch.cuda.is_available", return_value=False)
    def test_none_falls_back_to_cpu(self, _mock: object) -> None:
        self.assertEqual(_resolve_device(None), "cpu")

    # ------------------------------------------------------------------
    # Explicit device requests
    # ------------------------------------------------------------------
    def test_explicit_cpu_is_honoured(self) -> None:
        self.assertEqual(_resolve_device("cpu"), "cpu")

    @patch("podvoice.tts.torch.cuda.is_available", return_value=True)
    def test_explicit_cuda_is_honoured(self, _mock: object) -> None:
        self.assertEqual(_resolve_device("cuda"), "cuda")

    @patch("podvoice.tts.torch.cuda.is_available", return_value=False)
    def test_explicit_cuda_falls_back_when_unavailable(self, _mock: object) -> None:
        self.assertEqual(_resolve_device("cuda"), "cpu")


if __name__ == "__main__":
    unittest.main()
