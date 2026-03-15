"""Split long speech segments into smaller chunks for stable TTS synthesis.

Long segments can cause stream stalls or slow synthesis calls.  This module
provides simple sentence-boundary and word-boundary splitting that keeps each
chunk under a configurable character limit while preserving speaker and emotion
metadata.
"""

from __future__ import annotations

import re

from .utils import Segment

# Sentence-ending punctuation followed by whitespace, or newlines.
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def chunk_segment(segment: Segment, max_chars: int = 500) -> list[Segment]:
    """Split a single segment into chunks that fit within *max_chars*.

    Splitting strategy (in priority order):
    1. If the text already fits, return it unchanged.
    2. Split on sentence boundaries (``. ``, ``! ``, ``? ``, newlines).
    3. If no sentence boundary is found within *max_chars*, fall back to the
       nearest word boundary (space).

    Every returned chunk preserves the original segment's *speaker* and
    *emotion*.
    """

    text = segment.text
    if len(text) <= max_chars:
        return [segment]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_chars:
            chunks.append(remaining)
            break

        # Look for the last sentence boundary within the allowed window.
        best = -1
        for m in _SENTENCE_BOUNDARY_RE.finditer(remaining, 0, max_chars):
            best = m.end()

        if best > 0:
            chunks.append(remaining[:best].rstrip())
            remaining = remaining[best:].lstrip()
            continue

        # No sentence boundary found — fall back to the last space.
        space_idx = remaining.rfind(" ", 0, max_chars)
        if space_idx > 0:
            chunks.append(remaining[:space_idx].rstrip())
            remaining = remaining[space_idx + 1 :].lstrip()
            continue

        # No space at all within max_chars — take the whole window as-is.
        chunks.append(remaining[:max_chars])
        remaining = remaining[max_chars:]

    return [
        Segment(speaker=segment.speaker, emotion=segment.emotion, text=c)
        for c in chunks
        if c
    ]


def chunk_segments(
    segments: list[Segment], max_chars: int = 500
) -> list[Segment]:
    """Apply :func:`chunk_segment` to every segment and flatten the results."""

    result: list[Segment] = []
    for seg in segments:
        result.extend(chunk_segment(seg, max_chars=max_chars))
    return result
