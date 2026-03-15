"""Language drift guardrails for podvoice.

Detects and optionally sanitizes non-target-language characters in
segment text before TTS synthesis.  All detection is local-first and
pattern-based (Unicode ranges) — no external APIs or ML models.
"""

from __future__ import annotations

import enum
import logging
import re

logger = logging.getLogger(__name__)


class LanguagePolicy(enum.Enum):
    """How to handle detected language drift."""

    WARN = "warn"
    FAIL = "fail"
    SANITIZE = "sanitize"


# Unicode ranges for non-Latin scripts that indicate language drift.
_NON_LATIN_RANGES: dict[str, tuple[int, int]] = {
    "CJK": (0x4E00, 0x9FFF),
    "Hiragana": (0x3040, 0x309F),
    "Katakana": (0x30A0, 0x30FF),
    "Cyrillic": (0x0400, 0x04FF),
    "Arabic": (0x0600, 0x06FF),
}

# Zero-width and other problematic Unicode characters.
_ZWCHARS_RE = re.compile(
    "["
    "\u200b"  # zero-width space
    "\u200c"  # zero-width non-joiner
    "\u200d"  # zero-width joiner
    "\u200e"  # left-to-right mark
    "\u200f"  # right-to-left mark
    "\u202a-\u202e"  # bidi embedding/override
    "\u2060"  # word joiner
    "\u2061-\u2064"  # invisible operators
    "\ufeff"  # byte order mark
    "]"
)


def detect_language_drift(text: str, target_language: str) -> list[dict]:
    """Detect characters outside the expected script for *target_language*.

    For ``"en"`` targets, flags CJK, Hiragana, Katakana, Cyrillic, and
    Arabic codepoints.  For other target languages, ranges belonging to
    the target script are excluded from the results.

    Returns a list of findings, each a dict with keys ``"range"``,
    ``"chars"``, and ``"position"``.
    """

    findings: list[dict] = []

    for pos, ch in enumerate(text):
        code = ord(ch)
        for name, (lo, hi) in _NON_LATIN_RANGES.items():
            if lo <= code <= hi:
                # Skip ranges that belong to the target language.
                if target_language in ("zh", "ja", "ko") and name in (
                    "CJK",
                    "Hiragana",
                    "Katakana",
                ):
                    continue
                if target_language == "ru" and name == "Cyrillic":
                    continue
                if target_language == "ar" and name == "Arabic":
                    continue
                findings.append({"range": name, "chars": ch, "position": pos})
                break  # one finding per character is enough

    return findings


def sanitize_text(text: str, target_language: str) -> str:
    """Remove non-target-language characters and normalise whitespace.

    Also strips common problematic Unicode (zero-width chars, BOM, etc.).
    """

    # Strip zero-width / invisible chars first.
    text = _ZWCHARS_RE.sub("", text)

    # Remove characters flagged as language drift.
    findings = detect_language_drift(text, target_language)
    if findings:
        positions_to_remove = {f["position"] for f in findings}
        text = "".join(
            ch for pos, ch in enumerate(text) if pos not in positions_to_remove
        )

    # Normalise whitespace after removal.
    text = re.sub(r"\s+", " ", text).strip()

    return text


def apply_language_policy(
    text: str,
    target_language: str,
    policy: LanguagePolicy,
    segment_info: str = "",
) -> str:
    """Apply *policy* to *text* for the given *target_language*.

    * ``WARN``     — log a warning, return text unchanged.
    * ``FAIL``     — raise ``ValueError`` if drift is detected.
    * ``SANITIZE`` — log a warning, return sanitised text.
    """

    findings = detect_language_drift(text, target_language)

    if not findings:
        return text

    prefix = f"[{segment_info}] " if segment_info else ""
    chars_found = "".join(f["chars"] for f in findings)
    ranges_found = sorted({f["range"] for f in findings})
    msg = (
        f"{prefix}Language drift detected for target '{target_language}': "
        f"found {len(findings)} character(s) from {ranges_found}: {chars_found!r}"
    )

    if policy is LanguagePolicy.WARN:
        logger.warning(msg)
        return text

    if policy is LanguagePolicy.FAIL:
        raise ValueError(msg)

    # LanguagePolicy.SANITIZE
    logger.warning(msg)
    return sanitize_text(text, target_language)
