import unittest
from voice.audio_utils import rms, duration_s, bytes_to_int16, concat
from voice.tests._audio import silence_frame, tone_frame

class TestAudioUtils(unittest.TestCase):
    def test_rms_silence_is_zero(self):
        self.assertAlmostEqual(rms(silence_frame(320)), 0.0, places=6)

    def test_rms_tone_is_positive(self):
        self.assertGreater(rms(tone_frame(320)), 0.1)

    def test_duration(self):
        self.assertAlmostEqual(duration_s(tone_frame(16000), 16000), 1.0, places=3)

    def test_roundtrip(self):
        f = tone_frame(160)
        self.assertEqual(len(bytes_to_int16(f)), 160)

    def test_concat(self):
        self.assertEqual(len(concat([silence_frame(160), silence_frame(160)])), 640)

if __name__ == "__main__":
    unittest.main()
