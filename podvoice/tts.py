"""XTTS v2 loading and inference for podvoice.

This module wraps Coqui's XTTS v2 model behind a small, CPU-friendly
interface suitable for CLI use.
"""

from __future__ import annotations

import io
import logging
import os
from pathlib import Path
import wave

import numpy as np
import torch
from TTS.api import TTS as CoquiTTS
from pydub import AudioSegment

from .utils import (
    ModelLoadError,
    SynthesisError,
    Segment,
    stable_hash,
    build_segment_cache_key,
)

logger = logging.getLogger(__name__)

# Speakers whose conditioning latents are trained on English-language data.
# Curated from the XTTS v2 default speaker list.  Speakers with non-English
# surname origins (e.g. Hayasaka, Mataracı, Rudaski) tend to bias the GPT
# toward their native language even when ``language="en"`` is requested.
_ENGLISH_SAFE_SPEAKERS: set[str] = {
    "Claribel Dervla",
    "Daisy Studious",
    "Gracie Wise",
    "Brenda Stern",
    "Andrew Chipper",
    "Craig Gutsy",
    "Damien Black",
    "Nova Hogarth",
    "Narelle Moon",
    "Barbora MacLean",
    "Rosemary Okafor",
    "Chandra MacFarland",
    "Camilla Holmström",
    "Szofi Granger",
    "Aaron Dreschner",
    "Abrahan Mack",
    "Damjan Chapman",
    "Filip Traverse",
}


def _english_safe_speakers(all_speakers: list[str]) -> list[str]:
    """Return only speakers known to produce clean English output."""
    safe = [s for s in all_speakers if s in _ENGLISH_SAFE_SPEAKERS]
    return safe if safe else all_speakers


def _resolve_device(device: str | None) -> str:
    """Resolve device string to an actual torch device name.

    When *device* is ``None`` or ``"auto"``, CUDA is used if available,
    otherwise CPU.  An explicit ``"cuda"`` request falls back to CPU
    with a warning when CUDA is not available.
    """

    if device is None or device == "auto":
        if torch.cuda.is_available():
            logger.info("CUDA is available — selecting 'cuda' device.")
            return "cuda"
        logger.info("CUDA is not available — falling back to 'cpu'.")
        return "cpu"

    if device == "cuda" and not torch.cuda.is_available():
        logger.warning(
            "CUDA was explicitly requested but is not available. "
            "Falling back to 'cpu'."
        )
        return "cpu"

    logger.info("Using explicitly requested device '%s'.", device)
    return device


def _apply_cpu_thread_settings(cpu_threads: int | None) -> None:
    """Configure PyTorch CPU thread counts for inference.

    When *cpu_threads* is ``None`` the PyTorch / OS defaults are kept.
    """

    if cpu_threads is None:
        count = os.cpu_count() or 1
        logger.info(
            "cpu_threads not set — keeping PyTorch defaults "
            "(os.cpu_count()=%d).",
            count,
        )
        return

    torch.set_num_threads(cpu_threads)
    torch.set_num_interop_threads(cpu_threads)
    logger.info(
        "Set torch num_threads=%d and num_interop_threads=%d.",
        cpu_threads,
        cpu_threads,
    )


class XTTSVoiceEngine:
    """Thin wrapper around Coqui XTTS v2.

    The model is loaded once per process and re-used for all segments.
    Speaker names in the Markdown script are deterministically mapped to
    one of the available Coqui speakers, if any are exposed by the model.
    This gives each logical speaker a consistent voice without requiring
    any custom training or reference audio.
    """

    def __init__(
        self,
        language: str = "en",
        model_name: str = "tts_models/multilingual/multi-dataset/xtts_v2",
        device: str | None = None,
        progress_bar: bool = False,
        cpu_threads: int | None = None,
    ) -> None:
        self.language = language
        self.model_name = model_name

        device = _resolve_device(device)
        self.device = device

        if device == "cpu":
            _apply_cpu_thread_settings(cpu_threads)

        try:
            # The TTS API accepts the model name positionally.
            tts = CoquiTTS(model_name).to(device)
            # Ensure progress bar configuration is applied if supported.
            try:
                tts.progress_bar = progress_bar
            except AttributeError:
                # Older versions may not expose this attribute; ignore.
                pass
            self._tts = tts
        except Exception as exc:  # pragma: no cover - defensive
            raise ModelLoadError(
                f"Failed to load XTTS model '{model_name}' on device '{device}': {exc}"
            ) from exc

        # Many multi-speaker models expose a list of built-in speakers.
        # If this list is missing or empty, we simply let XTTS choose its
        # default voice for all segments.
        speakers = getattr(self._tts, "speakers", None) or []
        all_speakers = list(speakers)

        # When targeting English, restrict to speakers whose conditioning
        # latents come from English-language data.  Speakers trained on
        # other languages (identifiable by non-English surname origins)
        # can pull the autoregressive GPT toward that language even when
        # ``language="en"`` is set, causing audible language drift.
        if language == "en" and all_speakers:
            self._available_speakers = _english_safe_speakers(all_speakers)
            if not self._available_speakers:
                # Fallback: if filtering removed everyone, keep them all.
                self._available_speakers = all_speakers
            logger.info(
                "Filtered speakers for English: %d/%d available.",
                len(self._available_speakers),
                len(all_speakers),
            )
        else:
            self._available_speakers = all_speakers

        # Cache mapping from script speaker name -> internal XTTS speaker id.
        self._speaker_map: dict[str, str | None] = {}

        # Best-effort output sample rate discovery for in-memory WAV encoding.
        sample_rate = 24000
        synthesizer = getattr(self._tts, "synthesizer", None)
        if synthesizer is not None:
            sample_rate = int(getattr(synthesizer, "output_sample_rate", sample_rate))
        self.sample_rate = sample_rate

    # ------------------------------------------------------------------
    # Speaker mapping
    # ------------------------------------------------------------------
    def _map_script_speaker(self, script_speaker: str) -> str | None:
        """Map a script speaker name to a concrete XTTS speaker identifier.

        The mapping is deterministic: the same script speaker name always
        maps to the same XTTS speaker as long as the underlying list of
        available speakers does not change.
        """

        if script_speaker in self._speaker_map:
            return self._speaker_map[script_speaker]

        if not self._available_speakers:
            # No explicit speakers; let XTTS use its own default.
            self._speaker_map[script_speaker] = None
            return None

        idx = stable_hash(script_speaker) % len(self._available_speakers)
        chosen = self._available_speakers[idx]
        self._speaker_map[script_speaker] = chosen
        return chosen

    # ------------------------------------------------------------------
    # Synthesis
    # ------------------------------------------------------------------
    def synthesize_to_path(self, segment: Segment, out_path: Path) -> None:
        """Synthesize a single ``Segment`` to a WAV file at ``out_path``.

        The output format is always WAV, which is convenient for further
        processing with pydub.
        """

        out_path = out_path.with_suffix(".wav")
        speaker_id = self._map_script_speaker(segment.speaker)

        # Prepare keyword arguments for ``tts_to_file``. We only pass
        # parameters that are documented in the Coqui XTTS examples.
        kwargs = {
            "text": segment.text,
            "language": self.language,
            "file_path": str(out_path),
        }

        try:
            if speaker_id is not None:
                # Use a built-in Coqui speaker when available.
                self._tts.tts_to_file(speaker=speaker_id, **kwargs)
            else:
                # Fall back to the model's default voice.
                self._tts.tts_to_file(**kwargs)
        except Exception as exc:  # pragma: no cover - defensive
            raise SynthesisError(
                f"Failed to synthesize segment for speaker '{segment.speaker}': {exc}"
            ) from exc

    def cache_key_for_segment(self, segment: Segment) -> str:
        """Return a deterministic cache key for a segment synthesis result."""
        return build_segment_cache_key(
            model_name=self.model_name,
            language=self.language,
            speaker=segment.speaker,
            emotion=segment.emotion,
            text=segment.text,
        )

    def synthesize_to_audiosegment(self, segment: Segment) -> AudioSegment:
        """Synthesize one segment and return audio in-memory as AudioSegment."""

        speaker_id = self._map_script_speaker(segment.speaker)
        kwargs = {
            "text": segment.text,
            "language": self.language,
            # Lower temperature and raise repetition_penalty to reduce
            # cross-language drift that XTTS v2 can exhibit during
            # autoregressive generation.
            "temperature": 0.5,
            "repetition_penalty": 15.0,
            "top_p": 0.8,
        }

        try:
            with torch.inference_mode():
                if speaker_id is not None:
                    wav = self._tts.tts(speaker=speaker_id, **kwargs)
                else:
                    wav = self._tts.tts(**kwargs)
        except Exception as exc:  # pragma: no cover - defensive
            raise SynthesisError(
                f"Failed to synthesize segment for speaker '{segment.speaker}': {exc}"
            ) from exc

        # Coqui may return list/ndarray/tensor. Normalize to float32 numpy.
        if isinstance(wav, torch.Tensor):
            wav = wav.detach().cpu().numpy()
        arr = np.asarray(wav, dtype=np.float32).flatten()
        if arr.size == 0:
            raise SynthesisError(
                f"Synthesis returned empty audio for speaker '{segment.speaker}'."
            )

        arr = np.clip(arr, -1.0, 1.0)
        pcm16 = (arr * 32767.0).astype(np.int16)

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(pcm16.tobytes())

        buf.seek(0)
        return AudioSegment.from_file(buf, format="wav")
