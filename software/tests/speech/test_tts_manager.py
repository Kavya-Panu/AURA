import unittest
from speech.tts_manager import (
    TTSManager, FakeTTS, TTSEngine, Pyttsx3Engine, EdgeTTSEngine, PiperEngine)
from speech.voice_profiles import VoiceProfileRegistry
from speech.speech_exceptions import TTSUnavailable, TTSError

class TestTTS(unittest.TestCase):
    def setUp(self):
        self.profile = VoiceProfileRegistry().get("friendly")

    def test_fake_is_engine(self):
        self.assertIsInstance(FakeTTS(), TTSEngine)

    def test_synthesize_returns_duration(self):
        r = FakeTTS().synthesize("hello world", self.profile)
        self.assertGreater(r.duration_s, 0)
        self.assertEqual(r.engine, "fake")

    def test_unavailable_raises(self):
        with self.assertRaises(TTSUnavailable):
            FakeTTS(available=False).synthesize("x", self.profile)

    def test_manager_picks_available(self):
        down = FakeTTS("down", available=False)
        up = FakeTTS("up")
        mgr = TTSManager([down, up])
        r = mgr.synthesize("hi", self.profile)
        self.assertEqual(r.engine, "up")

    def test_manager_prefers_preferred(self):
        mgr = TTSManager([FakeTTS("a"), FakeTTS("b")], preferred="b")
        self.assertEqual(mgr.available_engine().name, "b")

    def test_no_engine_raises(self):
        mgr = TTSManager([FakeTTS("x", available=False)])
        with self.assertRaises(TTSUnavailable):
            mgr.synthesize("hi", self.profile)

    def test_real_engines_satisfy_interface_and_report_unavailable(self):
        for eng in (Pyttsx3Engine(), EdgeTTSEngine(), PiperEngine()):
            self.assertIsInstance(eng, TTSEngine)
            self.assertFalse(eng.is_available())    # no libs in sandbox

    def test_slower_profile_longer_duration(self):
        fast = VoiceProfileRegistry().get("excited")
        slow = VoiceProfileRegistry().get("calm")
        e = FakeTTS()
        self.assertGreater(e.synthesize("same text here", slow).duration_s,
                           e.synthesize("same text here", fast).duration_s)

if __name__ == "__main__":
    unittest.main()
