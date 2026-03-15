"""Audio utilities for concatenation and export.

We use :mod:`pydub` for stitching generated WAV segments together and
for simple peak normalization before exporting to the final format.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List

from pydub import AudioSegment
from pydub.playback import play as pydub_play

from .utils import PodvoiceError


def _normalize(audio: AudioSegment, target_dbfs: float = -20.0) -> AudioSegment:
    """Normalize an :class:`AudioSegment` to a target loudness.

    The default value of -20 dBFS is a conservative choice that keeps
    headroom while producing reasonably loud output for podcasts.
    """

    if audio.duration_seconds == 0:
        return audio

    change_in_dbfs = target_dbfs - audio.dBFS
    return audio.apply_gain(change_in_dbfs)


def build_podcast(
    segment_audio: Iterable[AudioSegment],
    gap_ms: int = 300,
    target_dbfs: float = -20.0,
) -> AudioSegment:
    """Concatenate and normalize a sequence of in-memory segments.

    Parameters
    ----------
    segment_audio:
        Audio segments in playback order.
    gap_ms:
        Duration of silence inserted between segments, in milliseconds.
    target_dbfs:
        Target loudness for normalization.
    """

    parts: List[AudioSegment] = list(segment_audio)
    if not parts:
        raise PodvoiceError("No audio segments were generated.")

    combined = AudioSegment.silent(duration=0)
    gap = AudioSegment.silent(duration=gap_ms)

    for idx, segment in enumerate(parts):
        combined += segment
        if idx < len(parts) - 1:
            combined += gap

    return _normalize(combined, target_dbfs=target_dbfs)


def export_audio(audio: AudioSegment, out_path: Path) -> None:
    """Export an :class:`AudioSegment` to WAV or MP3.

    The export format is inferred from the file extension:

    - ``.wav`` (default)
    - ``.mp3``
    """

    out_path = Path(out_path)
    suffix = out_path.suffix.lower()

    if not suffix:
        # Default to WAV if no extension is provided.
        suffix = ".wav"
        out_path = out_path.with_suffix(suffix)

    if suffix not in {".wav", ".mp3"}:
        raise PodvoiceError(
            f"Unsupported output format '{suffix}'. Use .wav or .mp3."
        )

    fmt = suffix.lstrip(".")

    try:
        audio.export(out_path, format=fmt)
    except Exception as exc:  # pragma: no cover - defensive
        raise PodvoiceError(f"Failed to export audio to '{out_path}': {exc}") from exc


def play_audio(audio: AudioSegment) -> None:
    """Play an :class:`AudioSegment` through the local default output device."""

    try:
        pydub_play(audio)
    except Exception as exc:  # pragma: no cover - backend-dependent
        raise PodvoiceError(
            "Failed to play audio via local speakers. "
            "Ensure an audio backend is available (e.g. ffplay/simpleaudio)."
        ) from exc
