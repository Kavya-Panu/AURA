import unittest
from speech.emotion_mapper import EmotionMapper
from core.constants import Emotion

class TestEmotionMapper(unittest.TestCase):
    def setUp(self):
        self.m = EmotionMapper()

    def test_greeting_is_happy(self):
        s = self.m.map("Hello there!", mode="NORMAL")
        self.assertEqual(s.emotion, Emotion.HAPPY.value)

    def test_congratulations_celebrate(self):
        s = self.m.map("Congratulations, well done!", mode="QUIZ")
        self.assertEqual(s.emotion, Emotion.CELEBRATE.value)

    def test_apology_sad(self):
        s = self.m.map("Sorry, I cannot do that.", mode="ASSISTANT")
        self.assertEqual(s.emotion, Emotion.SAD.value)

    def test_confused(self):
        s = self.m.map("I'm not sure I understand.", mode="ASSISTANT")
        self.assertEqual(s.emotion, Emotion.CONFUSED.value)

    def test_focus_reminder_worried(self):
        s = self.m.map("Careful, put your phone away and stay focused.",
                       mode="FOCUS")
        self.assertEqual(s.emotion, Emotion.WORRIED.value)

    def test_thinking(self):
        s = self.m.map("Hmm, let me think about that.", mode="ASSISTANT")
        self.assertEqual(s.emotion, Emotion.THINKING.value)

    def test_translation_stays_neutral_listening(self):
        # translation should NOT switch expressions on content cues
        s = self.m.map("Congratulations!", mode="TRANSLATION")
        self.assertEqual(s.emotion, Emotion.LISTENING.value)
        self.assertEqual(s.profile, "translator")

    def test_mode_profiles(self):
        self.assertEqual(self.m.map("x", mode="TEACHER").profile, "teacher")
        self.assertEqual(self.m.map("x", mode="QUIZ").profile, "excited")

    def test_explicit_hint_overrides(self):
        s = self.m.map("anything", mode="NORMAL", hint_emotion="love")
        self.assertEqual(s.emotion, "LOVE")

if __name__ == "__main__":
    unittest.main()
