"""Tests for podvoice.chunking — segment splitting for stable TTS synthesis."""

from __future__ import annotations

import pytest

from podvoice.chunking import chunk_segment, chunk_segments
from podvoice.utils import Segment, build_segment_cache_key


# ---------------------------------------------------------------------------
# Short segments pass through unchanged
# ---------------------------------------------------------------------------


def test_short_segment_unchanged():
    seg = Segment(speaker="Alice", emotion="calm", text="Hello, world.")
    result = chunk_segment(seg, max_chars=500)
    assert result == [seg]
    assert result[0] is seg  # identity — no copy needed


def test_exact_limit_unchanged():
    text = "a" * 500
    seg = Segment(speaker="Bob", emotion=None, text=text)
    result = chunk_segment(seg, max_chars=500)
    assert len(result) == 1
    assert result[0].text == text


# ---------------------------------------------------------------------------
# Sentence-boundary splitting
# ---------------------------------------------------------------------------


def test_split_on_sentence_boundaries():
    text = "First sentence. Second sentence. Third sentence."
    seg = Segment(speaker="Alice", emotion="calm", text=text)
    result = chunk_segment(seg, max_chars=35)
    assert len(result) >= 2
    # All chunks should be at most 35 chars (sentences fit within limit).
    for chunk in result:
        assert len(chunk.text) <= 35


def test_split_on_exclamation_and_question():
    text = "Wow! Really? Yes. Indeed."
    seg = Segment(speaker="Bob", emotion="excited", text=text)
    result = chunk_segment(seg, max_chars=15)
    assert len(result) >= 2
    combined = " ".join(c.text for c in result)
    # All original words should be present.
    for word in ["Wow!", "Really?", "Yes.", "Indeed."]:
        assert word in combined


def test_split_on_newline():
    text = "Line one.\nLine two.\nLine three."
    seg = Segment(speaker="Alice", emotion=None, text=text)
    result = chunk_segment(seg, max_chars=15)
    assert len(result) >= 2
    for chunk in result:
        assert chunk.speaker == "Alice"


# ---------------------------------------------------------------------------
# Metadata preservation
# ---------------------------------------------------------------------------


def test_speaker_preserved():
    text = "A " * 300
    seg = Segment(speaker="Charlie", emotion="happy", text=text.strip())
    result = chunk_segment(seg, max_chars=50)
    assert all(c.speaker == "Charlie" for c in result)


def test_emotion_preserved():
    text = "A " * 300
    seg = Segment(speaker="Charlie", emotion="happy", text=text.strip())
    result = chunk_segment(seg, max_chars=50)
    assert all(c.emotion == "happy" for c in result)


def test_none_emotion_preserved():
    text = "A " * 300
    seg = Segment(speaker="Dana", emotion=None, text=text.strip())
    result = chunk_segment(seg, max_chars=50)
    assert all(c.emotion is None for c in result)


# ---------------------------------------------------------------------------
# Word-boundary fallback
# ---------------------------------------------------------------------------


def test_word_boundary_fallback():
    # No sentence-ending punctuation, just spaces.
    text = "word " * 120  # 600 chars
    seg = Segment(speaker="Alice", emotion=None, text=text.strip())
    result = chunk_segment(seg, max_chars=100)
    assert len(result) >= 2
    for chunk in result:
        assert len(chunk.text) <= 100


def test_no_space_hard_split():
    # A single extremely long token with no spaces at all.
    text = "x" * 1000
    seg = Segment(speaker="Alice", emotion=None, text=text)
    result = chunk_segment(seg, max_chars=300)
    assert len(result) >= 2
    assert "".join(c.text for c in result) == text


# ---------------------------------------------------------------------------
# Chunk ordering
# ---------------------------------------------------------------------------


def test_chunks_in_correct_order():
    text = "First sentence. Second sentence. Third sentence."
    seg = Segment(speaker="Alice", emotion=None, text=text)
    result = chunk_segment(seg, max_chars=25)
    reconstructed = " ".join(c.text for c in result)
    # "First" should appear before "Second" which should appear before "Third".
    assert reconstructed.index("First") < reconstructed.index("Second")
    assert reconstructed.index("Second") < reconstructed.index("Third")


# ---------------------------------------------------------------------------
# chunk_segments (batch helper)
# ---------------------------------------------------------------------------


def test_chunk_segments_flattens():
    segs = [
        Segment(speaker="Alice", emotion=None, text="Short."),
        Segment(speaker="Bob", emotion=None, text="A " * 300),
    ]
    result = chunk_segments(segs, max_chars=100)
    assert len(result) > 2  # second segment should be split
    assert result[0].text == "Short."
    assert result[0].speaker == "Alice"
    assert all(c.speaker == "Bob" for c in result[1:])


def test_chunk_segments_preserves_short():
    segs = [
        Segment(speaker="A", emotion=None, text="Hello."),
        Segment(speaker="B", emotion=None, text="World."),
    ]
    result = chunk_segments(segs, max_chars=500)
    assert len(result) == 2
    assert result[0].text == "Hello."
    assert result[1].text == "World."


# ---------------------------------------------------------------------------
# Cache keys differ between chunks
# ---------------------------------------------------------------------------


def test_cache_keys_differ():
    text = "First sentence. Second sentence. Third sentence."
    seg = Segment(speaker="Alice", emotion="calm", text=text)
    chunks = chunk_segment(seg, max_chars=25)
    assert len(chunks) >= 2

    keys = [
        build_segment_cache_key("xtts_v2", "en", c.speaker, c.emotion, c.text)
        for c in chunks
    ]
    # All keys should be unique.
    assert len(set(keys)) == len(keys)
