"""Parameter extraction + validation across formats."""
import unittest
from intent import IntentEngine, Intent

E = IntentEngine()

class TestParameters(unittest.TestCase):
    def test_duration_formats(self):
        for text, minutes in (("focus for 2 hours", 120),
                              ("focus for 180 minutes", 180),
                              ("focus for 90 mins", 90),
                              ("focus for half an hour", 30),
                              ("focus for an hour", 60),
                              ("focus for 1 hour 30 minutes", 90)):
            r = E.process(f"Aura {text}", "NORMAL")
            self.assertEqual(r.parameters.get("duration_minutes"), minutes, text)

    def test_duration_clamped_to_spec_range(self):
        r = E.process("Aura focus for 10 hours", "NORMAL")
        self.assertEqual(r.parameters["duration_minutes"], 240)   # max clamp
        r = E.process("Aura focus for 5 minutes", "NORMAL")
        self.assertEqual(r.parameters["duration_minutes"], 15)    # min clamp

    def test_timer_seconds(self):
        r = E.process("Aura set a timer for 10 minutes", "NORMAL")
        self.assertEqual(r.intent, Intent.SET_TIMER)
        self.assertEqual(r.parameters["timer_seconds"], 600)
        r = E.process("Aura timer for 30 seconds", "NORMAL")
        self.assertEqual(r.parameters["timer_seconds"], 30)

    def test_reminder_text_and_time(self):
        r = E.process("Aura remind me to drink water at 5 pm", "NORMAL")
        self.assertEqual(r.intent, Intent.SET_REMINDER)
        self.assertEqual(r.parameters["reminder_text"], "drink water")
        self.assertEqual(r.parameters["reminder_time"], "17:00")

    def test_date_words(self):
        r = E.process("Aura remind me about the exam tomorrow", "NORMAL")
        self.assertEqual(r.intent, Intent.SET_REMINDER)
        self.assertEqual(r.parameters["reminder_time"], "tomorrow")

    def test_difficulty_canonicalised(self):
        r = E.process("Aura quiz me on math make it hard", "NORMAL")
        self.assertEqual(r.parameters["difficulty"], "advanced")
        self.assertEqual(r.parameters["subject"], "math")

    def test_calculator_expression(self):
        r = E.process("Aura what's 15% of 240", "NORMAL")
        self.assertEqual(r.intent, Intent.CALCULATE)
        self.assertIn("15%", r.parameters["expression"])
        self.assertIn("240", r.parameters["expression"])

    def test_unknown_language_dropped_then_clarified(self):
        r = E.process("Aura translate to klingon", "NORMAL")
        self.assertEqual(r.intent, Intent.START_TRANSLATION)
        self.assertNotIn("target_language", r.parameters)
        self.assertTrue(r.clarification_needed)

if __name__ == "__main__":
    unittest.main()
