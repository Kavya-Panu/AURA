import unittest
from voice.wake_word import WakeWordDetector, FakeWakeWord
from voice.voice_config import WakeWordConfig

class Clock:
    def __init__(self): self.t = 100.0
    def __call__(self): return self.t

class TestWakeWord(unittest.TestCase):
    def test_streaming_fires_above_threshold(self):
        clk = Clock()
        det = WakeWordDetector(WakeWordConfig(confidence_threshold=0.7),
                               FakeWakeWord([0.2, 0.9]), clock=clk)
        self.assertFalse(det.process_frame(b""))
        self.assertTrue(det.process_frame(b""))

    def test_cooldown_blocks_retrigger(self):
        clk = Clock()
        det = WakeWordDetector(WakeWordConfig(confidence_threshold=0.5,
                                              cooldown_s=1.5),
                               FakeWakeWord([0.9, 0.9]), clock=clk)
        self.assertTrue(det.process_frame(b""))      # fires
        self.assertFalse(det.process_frame(b""))     # within cooldown
        clk.t += 2.0
        det2 = FakeWakeWord([0.9]); det._backend = det2
        self.assertTrue(det.process_frame(b""))      # cooled down

    def test_text_detection_strips_phrase(self):
        det = WakeWordDetector(WakeWordConfig())
        fired, rest = det.check_text("Aura start focus")
        self.assertTrue(fired)
        self.assertEqual(rest, "start focus")

    def test_text_no_wake(self):
        det = WakeWordDetector(WakeWordConfig())
        fired, rest = det.check_text("start focus")
        self.assertFalse(fired)

if __name__ == "__main__":
    unittest.main()
