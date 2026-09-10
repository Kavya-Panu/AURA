import unittest
from voice.backends import FakeSTT
from voice.speech_recognizer import SpeechRecognizer, normalize_transcript
from voice.noise_filter import NoiseFilter
from voice.voice_config import VoiceConfig
from voice.tests._audio import tone_frame

class TestRecognizer(unittest.TestCase):
    def setUp(self):
        self.cfg = VoiceConfig()
        self.stt = FakeSTT()
        self.rec = SpeechRecognizer(self.cfg, self.stt,
                                    noise=NoiseFilter(self.cfg.audio, self.cfg.noise))
        self.rec.load()

    def test_transcribes_text(self):
        self.stt.queue("aura start focus", "en", 0.95)
        r = self.rec.recognize(tone_frame(16000))
        self.assertEqual(r.text, "AURA start focus")
        self.assertEqual(r.language, "en")
        self.assertFalse(r.is_empty)

    def test_empty_when_no_speech(self):
        r = self.rec.recognize(tone_frame(1600))
        self.assertTrue(r.is_empty)

    def test_language_passthrough(self):
        self.cfg.stt.language = None
        self.stt.queue("hola", "es", 0.9)
        r = self.rec.recognize(tone_frame(16000))
        self.assertEqual(r.language, "es")

    def test_normalizes_robotics_terms(self):
        text = normalize_transcript(
            "hey ora, connect e s p thirty two to platform i o and open c v"
        )
        self.assertEqual(
            text,
            "AURA, connect ESP32 to PlatformIO and OpenCV",
        )

    def test_removes_adjacent_repeated_sentence(self):
        self.assertEqual(
            normalize_transcript("What do you think? What do you think?"),
            "What do you think?",
        )

    def test_recognize_before_load_raises(self):
        from voice.voice_exceptions import STTError
        rec = SpeechRecognizer(self.cfg, FakeSTT())
        with self.assertRaises(STTError):
            rec.recognize(b"")

if __name__ == "__main__":
    unittest.main()
