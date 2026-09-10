"""Focus intents: NL variations, durations, mode context, lifecycle."""
import unittest
from intent import IntentEngine, Intent

E = IntentEngine()

class TestFocus(unittest.TestCase):
    def test_all_start_variations(self):
        for text in ("Aura start focus", "Aura focus mode", "Aura let's study",
                     "Aura help me focus", "Aura study mode",
                     "Aura start studying", "Aura I need to concentrate"):
            r = E.process(text, "NORMAL")
            self.assertEqual(r.intent, Intent.START_FOCUS, text)
            self.assertGreater(r.confidence, 0.70, text)

    def test_duration_two_hours(self):
        r = E.process("Aura help me focus for two hours", "NORMAL")
        self.assertEqual(r.intent, Intent.START_FOCUS)
        self.assertEqual(r.parameters["duration_minutes"], 120)
        self.assertFalse(r.clarification_needed)

    def test_duration_90_mins(self):
        r = E.process("Aura focus for 90 mins", "NORMAL")
        self.assertEqual(r.intent, Intent.START_FOCUS)
        self.assertEqual(r.parameters["duration_minutes"], 90)

    def test_bare_focus_asks_duration(self):
        r = E.process("Aura focus", "NORMAL")
        self.assertEqual(r.intent, Intent.START_FOCUS)
        self.assertTrue(r.clarification_needed)
        self.assertIn("duration_minutes", r.missing_parameters)
        self.assertIn("How long", r.clarification_question)

    def test_stop_in_focus_mode(self):
        r = E.process("Aura stop", "FOCUS")
        self.assertEqual(r.intent, Intent.STOP_FOCUS)

    def test_pause_resume_break_status(self):
        self.assertEqual(E.process("Aura pause focus", "FOCUS").intent,
                         Intent.PAUSE_FOCUS)
        self.assertEqual(E.process("Aura resume focus", "FOCUS").intent,
                         Intent.RESUME_FOCUS)
        self.assertEqual(E.process("Aura I need a break", "FOCUS").intent,
                         Intent.START_BREAK)
        self.assertEqual(E.process("Aura how much time left", "FOCUS").intent,
                         Intent.FOCUS_STATUS)

    def test_adjust_duration_inside_focus(self):
        r = E.process("Aura make it 90 minutes", "FOCUS")
        self.assertEqual(r.intent, Intent.SET_FOCUS_DURATION)
        self.assertEqual(r.parameters["duration_minutes"], 90)

if __name__ == "__main__":
    unittest.main()
