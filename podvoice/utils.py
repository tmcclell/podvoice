"""Shared utilities and simple data structures for podvoice.

We keep this module intentionally small and beginner-friendly.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path


class PodvoiceError(Exception):
    """Base exception for all podvoice-specific errors."""


class ScriptParseError(PodvoiceError):
    """Raised when the input Markdown script cannot be parsed."""


class ModelLoadError(PodvoiceError):
    """Raised when the TTS model cannot be loaded."""


class SynthesisError(PodvoiceError):
    """Raised when TTS synthesis fails for a segment."""


@dataclass
class Segment:
    """A single speech segment in the script.

    Attributes
    ----------
    speaker:
        Name of the speaker, as written in the Markdown block.
    emotion:
        Optional emotion tag (e.g. "calm", "excited"). This is not
        interpreted by the TTS model directly in v0.1, but is kept for
        future use and for potential downstream tooling.
    text:
        The spoken content for this segment.
    """

    speaker: str
    emotion: str | None
    text: str


def stable_hash(text: str) -> int:
    """Return a deterministic integer hash for mapping names to speakers.

    Python's built-in ``hash`` is randomized between processes. For
    reproducible behavior, we base our mapping on an MD5 digest instead.
    This is only used for speaker name -> XTTS speaker mapping and does
    not have any security implications.
    """

    digest = hashlib.md5(text.encode("utf-8")).hexdigest()
    return int(digest, 16)


def stable_sha256(text: str) -> str:
    """Return a deterministic SHA256 hex digest for cache keys."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_segment_cache_key(
    model_name: str,
    language: str,
    speaker: str,
    emotion: str | None,
    text: str,
) -> str:
    """Build a deterministic cache key for one synthesized segment."""

    payload = "\n".join([model_name, language, speaker, emotion or "", text])
    return stable_sha256(payload)


def get_default_cache_dir() -> Path:
    """Return the default cache directory path for podvoice.

    Users can override this location with ``PODVOICE_CACHE_DIR``.
    """

    override = os.environ.get("PODVOICE_CACHE_DIR")
    if override:
        return Path(override).expanduser().resolve()

    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "podvoice" / "cache"

    # Linux/macOS/other POSIX fallback.
    return Path.home() / ".cache" / "podvoice"
