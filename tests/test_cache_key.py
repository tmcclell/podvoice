import unittest

from podvoice.utils import build_segment_cache_key


class SegmentCacheKeyTests(unittest.TestCase):
    def test_cache_key_is_deterministic(self) -> None:
        key1 = build_segment_cache_key(
            model_name="tts_models/multilingual/multi-dataset/xtts_v2",
            language="en",
            speaker="Host",
            emotion="calm",
            text="Hello world",
        )
        key2 = build_segment_cache_key(
            model_name="tts_models/multilingual/multi-dataset/xtts_v2",
            language="en",
            speaker="Host",
            emotion="calm",
            text="Hello world",
        )

        self.assertEqual(key1, key2)

    def test_cache_key_changes_when_text_changes(self) -> None:
        key1 = build_segment_cache_key(
            model_name="tts_models/multilingual/multi-dataset/xtts_v2",
            language="en",
            speaker="Host",
            emotion="calm",
            text="Hello world",
        )
        key2 = build_segment_cache_key(
            model_name="tts_models/multilingual/multi-dataset/xtts_v2",
            language="en",
            speaker="Host",
            emotion="calm",
            text="Hello world!",
        )

        self.assertNotEqual(key1, key2)


if __name__ == "__main__":
    unittest.main()
