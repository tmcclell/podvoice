import unittest

from podvoice.parser import merge_adjacent_segments
from podvoice.utils import Segment


class MergeAdjacentSegmentsTests(unittest.TestCase):
    def test_merges_when_speaker_and_emotion_match(self) -> None:
        segments = [
            Segment(speaker="Host", emotion="calm", text="Hello"),
            Segment(speaker="Host", emotion="calm", text="World"),
            Segment(speaker="Guest", emotion="warm", text="Hi"),
        ]

        merged = merge_adjacent_segments(segments)

        self.assertEqual(2, len(merged))
        self.assertEqual("Host", merged[0].speaker)
        self.assertEqual("calm", merged[0].emotion)
        self.assertEqual("Hello\n\nWorld", merged[0].text)

    def test_does_not_merge_when_emotion_differs(self) -> None:
        segments = [
            Segment(speaker="Host", emotion="calm", text="First"),
            Segment(speaker="Host", emotion="excited", text="Second"),
        ]

        merged = merge_adjacent_segments(segments)

        self.assertEqual(2, len(merged))
        self.assertEqual("First", merged[0].text)
        self.assertEqual("Second", merged[1].text)


if __name__ == "__main__":
    unittest.main()
