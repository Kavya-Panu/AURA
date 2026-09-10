import unittest
from speech.timing_controller import TimingController
from speech.speech_config import TimingConfig

class TestTiming(unittest.TestCase):
    def setUp(self):
        self.slept = []
        self.tc = TimingController(TimingConfig(thinking_pause_s=0.4,
                                                sentence_gap_s=0.25),
                                   sleep=self.slept.append)

    def test_thinking_pause_uses_config(self):
        self.tc.thinking_pause()
        self.assertEqual(self.slept, [0.4])

    def test_sentence_gap(self):
        self.tc.sentence_gap()
        self.assertEqual(self.slept, [0.25])

    def test_split_sentences(self):
        parts = self.tc.split_sentences("Hello there. How are you? Good!")
        self.assertEqual(parts, ["Hello there.", "How are you?", "Good!"])

    def test_split_single(self):
        self.assertEqual(self.tc.split_sentences("just one"), ["just one"])

    def test_split_empty(self):
        self.assertEqual(self.tc.split_sentences("  "), [])

if __name__ == "__main__":
    unittest.main()
