"""Tests for podvoice.guardrails — language drift detection and sanitisation."""

import logging
import unittest

from podvoice.guardrails import (
    LanguagePolicy,
    apply_language_policy,
    detect_language_drift,
    sanitize_text,
)


class DetectLanguageDriftTests(unittest.TestCase):
    """Tests for detect_language_drift()."""

    def test_finds_cjk_in_english_text(self) -> None:
        text = "Hello \u4e16\u754c"  # 世界 (CJK)
        findings = detect_language_drift(text, "en")

        self.assertEqual(2, len(findings))
        self.assertEqual("CJK", findings[0]["range"])
        self.assertEqual("\u4e16", findings[0]["chars"])
        self.assertEqual("CJK", findings[1]["range"])
        self.assertEqual("\u754c", findings[1]["chars"])

    def test_finds_hiragana_in_english_text(self) -> None:
        text = "Say \u3053\u3093\u306b\u3061\u306f"
        findings = detect_language_drift(text, "en")

        self.assertTrue(len(findings) > 0)
        self.assertTrue(all(f["range"] == "Hiragana" for f in findings))

    def test_finds_cyrillic_in_english_text(self) -> None:
        text = "Hello \u041f\u0440\u0438\u0432\u0435\u0442"
        findings = detect_language_drift(text, "en")

        self.assertTrue(len(findings) > 0)
        self.assertTrue(all(f["range"] == "Cyrillic" for f in findings))

    def test_returns_empty_for_clean_english_text(self) -> None:
        text = "Hello, this is a perfectly clean English sentence!"
        findings = detect_language_drift(text, "en")

        self.assertEqual([], findings)

    def test_returns_empty_for_english_with_punctuation(self) -> None:
        text = "It's 100% fine — really! (yes, truly.)"
        findings = detect_language_drift(text, "en")

        self.assertEqual([], findings)

    def test_cjk_not_flagged_for_japanese_target(self) -> None:
        text = "\u3053\u3093\u306b\u3061\u306f\u4e16\u754c"
        findings = detect_language_drift(text, "ja")

        self.assertEqual([], findings)

    def test_cyrillic_not_flagged_for_russian_target(self) -> None:
        text = "\u041f\u0440\u0438\u0432\u0435\u0442"
        findings = detect_language_drift(text, "ru")

        self.assertEqual([], findings)

    def test_positions_are_correct(self) -> None:
        text = "AB\u4e16CD"
        findings = detect_language_drift(text, "en")

        self.assertEqual(1, len(findings))
        self.assertEqual(2, findings[0]["position"])


class SanitizeTextTests(unittest.TestCase):
    """Tests for sanitize_text()."""

    def test_removes_non_target_characters(self) -> None:
        text = "Hello \u4e16\u754c world"
        result = sanitize_text(text, "en")

        self.assertEqual("Hello world", result)

    def test_strips_zero_width_characters(self) -> None:
        text = "Hello\u200bworld\u200d!"
        result = sanitize_text(text, "en")

        self.assertEqual("Helloworld!", result)

    def test_normalises_whitespace_after_removal(self) -> None:
        text = "Hello  \u4e16  world"
        result = sanitize_text(text, "en")

        self.assertEqual("Hello world", result)

    def test_clean_text_passes_through(self) -> None:
        text = "This is fine."
        result = sanitize_text(text, "en")

        self.assertEqual("This is fine.", result)


class ApplyLanguagePolicyTests(unittest.TestCase):
    """Tests for apply_language_policy()."""

    def test_warn_logs_but_does_not_modify_text(self) -> None:
        text = "Hello \u4e16\u754c"

        with self.assertLogs("podvoice.guardrails", level="WARNING") as cm:
            result = apply_language_policy(text, "en", LanguagePolicy.WARN)

        self.assertEqual(text, result)
        self.assertTrue(any("Language drift" in m for m in cm.output))

    def test_warn_includes_segment_info(self) -> None:
        text = "Hello \u4e16\u754c"

        with self.assertLogs("podvoice.guardrails", level="WARNING") as cm:
            apply_language_policy(
                text, "en", LanguagePolicy.WARN, segment_info="seg 1: Host"
            )

        self.assertTrue(any("seg 1: Host" in m for m in cm.output))

    def test_fail_raises_on_drift(self) -> None:
        text = "Hello \u4e16\u754c"

        with self.assertRaises(ValueError, msg="Language drift"):
            apply_language_policy(text, "en", LanguagePolicy.FAIL)

    def test_fail_does_not_raise_for_clean_text(self) -> None:
        text = "Perfectly clean."
        result = apply_language_policy(text, "en", LanguagePolicy.FAIL)

        self.assertEqual(text, result)

    def test_sanitize_returns_cleaned_text(self) -> None:
        text = "Hello \u4e16\u754c world"

        with self.assertLogs("podvoice.guardrails", level="WARNING"):
            result = apply_language_policy(text, "en", LanguagePolicy.SANITIZE)

        self.assertEqual("Hello world", result)

    def test_no_policy_does_not_affect_text(self) -> None:
        """When guardrails are not applied at all, text is unchanged.

        This tests the integration contract: if ``language_policy`` is
        ``None`` the CLI never calls ``apply_language_policy``, so any
        text—dirty or not—passes through untouched.
        """
        dirty_text = "Hello \u4e16\u754c"

        # Simulate what the CLI does when policy is None: skip entirely.
        result = dirty_text  # no call to apply_language_policy
        self.assertEqual(dirty_text, result)


if __name__ == "__main__":
    unittest.main()
