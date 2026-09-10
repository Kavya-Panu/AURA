import unittest
from speech.voice_profiles import VoiceProfileRegistry, VoiceProfile
from speech.speech_exceptions import VoiceProfileError

class TestVoiceProfiles(unittest.TestCase):
    def test_default_profiles_present(self):
        reg = VoiceProfileRegistry()
        for name in ("friendly", "teacher", "translator", "assistant",
                     "calm", "excited"):
            self.assertTrue(reg.has(name))

    def test_profiles_define_voice_params(self):
        reg = VoiceProfileRegistry()
        teacher = reg.get("teacher")
        self.assertLess(teacher.speed, 1.0)          # slower
        excited = reg.get("excited")
        self.assertGreater(excited.speed, 1.0)       # faster
        self.assertGreater(excited.pitch, 1.0)

    def test_unknown_profile_raises(self):
        with self.assertRaises(VoiceProfileError):
            VoiceProfileRegistry().get("nope")

    def test_register_custom_voice(self):
        reg = VoiceProfileRegistry()
        reg.register(VoiceProfile("robot", speed=1.3, pitch=0.7))
        self.assertTrue(reg.has("robot"))
        self.assertEqual(reg.get("robot").pitch, 0.7)

if __name__ == "__main__":
    unittest.main()
