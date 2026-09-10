import unittest
from brain.prompt_manager import PromptManager
from brain.brain_exceptions import PromptError

class TestPrompts(unittest.TestCase):
    def test_mode_prompts_distinct(self):
        pm = PromptManager()
        self.assertNotEqual(pm.get_prompt("TEACHER"), pm.get_prompt("TRANSLATION"))

    def test_all_required_modes_present(self):
        pm = PromptManager()
        for mode in ("ASSISTANT", "TEACHER", "HOMEWORK", "QUIZ",
                     "TRANSLATION", "PRESENTATION", "FOCUS"):
            self.assertTrue(pm.get_prompt(mode))

    def test_unknown_mode_falls_back(self):
        pm = PromptManager()
        self.assertEqual(pm.get_prompt("NONEXISTENT"), pm.get_prompt("DEFAULT"))

    def test_none_mode_falls_back(self):
        pm = PromptManager()
        self.assertEqual(pm.get_prompt(None), pm.get_prompt("DEFAULT"))

    def test_override_and_add_future_mode(self):
        pm = PromptManager()
        pm.set_prompt("DREAM_MODE", "You are AURA dreaming.")
        self.assertIn("dreaming", pm.get_prompt("dream_mode"))

    def test_empty_prompt_rejected(self):
        with self.assertRaises(PromptError):
            PromptManager().set_prompt("X", "   ")

    def test_custom_prompts_at_construction(self):
        pm = PromptManager({"TEACHER": "custom teacher"})
        self.assertEqual(pm.get_prompt("TEACHER"), "custom teacher")

if __name__ == "__main__":
    unittest.main()
