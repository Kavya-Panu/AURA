"""Translation intents: language pairs, continuous mode, stop precedence."""
import unittest
from intent import IntentEngine, Intent

E = IntentEngine()

class TestTranslation(unittest.TestCase):
    def test_start_variations(self):
        for text in ("Aura translate everything",
                     "Aura translate everything I say",
                     "Aura start translation", "Aura be our interpreter",
                     "Aura start translating"):
            r = E.process(text, "NORMAL")
            self.assertEqual(r.intent, Intent.START_TRANSLATION, text)

    def test_language_pair(self):
        r = E.process("Aura translate English to Japanese", "NORMAL")
        self.assertEqual(r.intent, Intent.START_TRANSLATION)
        self.assertEqual(r.parameters["source_language"], "English")
        self.assertEqual(r.parameters["target_language"], "Japanese")

    def test_hindi_to_english(self):
        r = E.process("Aura translate Hindi to English", "NORMAL")
        self.assertEqual(r.parameters["source_language"], "Hindi")
        self.assertEqual(r.parameters["target_language"], "English")

    def test_bare_translate_asks_languages(self):
        r = E.process("Aura translate", "NORMAL")
        self.assertEqual(r.intent, Intent.START_TRANSLATION)
        self.assertTrue(r.clarification_needed)
        self.assertIn("target_language", r.missing_parameters)

    def test_free_speech_becomes_utterance(self):
        r = E.process("the weather is lovely today isn't it", "TRANSLATION")
        self.assertEqual(r.intent, Intent.TRANSLATE_UTTERANCE)
        self.assertIn("query", r.parameters)

    def test_stop_always_wins_in_translation(self):
        self.assertEqual(E.process("Aura stop", "TRANSLATION").intent,
                         Intent.STOP_TRANSLATION)
        self.assertEqual(E.process("Aura stop translation", "TRANSLATION").intent,
                         Intent.STOP_TRANSLATION)

    def test_change_language_mid_session(self):
        r = E.process("Aura now translate to French", "TRANSLATION")
        self.assertEqual(r.intent, Intent.SET_TRANSLATION_LANGUAGE)
        self.assertEqual(r.parameters["target_language"], "French")

    def test_pause_resume(self):
        self.assertEqual(E.process("Aura pause translation", "TRANSLATION").intent,
                         Intent.PAUSE_TRANSLATION)
        self.assertEqual(E.process("Aura resume translation", "TRANSLATION").intent,
                         Intent.RESUME_TRANSLATION)

if __name__ == "__main__":
    unittest.main()
