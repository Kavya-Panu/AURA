"""Confidence banding, UNKNOWN fallback, and the <50ms performance budget."""
import time
import unittest
from intent import IntentEngine, Intent
from intent.confidence import ConfidenceLevel, level

E = IntentEngine()

class TestConfidence(unittest.TestCase):
    def test_bands(self):
        self.assertIs(level(0.95), ConfidenceLevel.EXECUTE)
        self.assertIs(level(0.80), ConfidenceLevel.EXECUTE_LOG)
        self.assertIs(level(0.55), ConfidenceLevel.CLARIFY)
        self.assertIs(level(0.20), ConfidenceLevel.UNKNOWN)

    def test_exact_phrase_high_confidence(self):
        r = E.process("Aura start focus", "NORMAL")
        self.assertGreater(r.confidence, 0.90)

    def test_gibberish_is_unknown(self):
        r = E.process("Aura zorp flimble quang", "NORMAL")
        self.assertEqual(r.intent, Intent.UNKNOWN)
        self.assertTrue(r.clarification_needed)

    def test_result_fields_complete(self):
        r = E.process("Aura start focus", "NORMAL")
        d = r.to_dict()
        for key in ("intent", "confidence", "parameters",
                    "missing_parameters", "clarification_needed",
                    "clarification_question", "response_hint",
                    "raw_text", "timestamp"):
            self.assertIn(key, d)
        self.assertEqual(r.raw_text, "Aura start focus")

    def test_performance_under_50ms(self):
        samples = ["Aura help me focus for two hours",
                   "Aura translate English to Japanese",
                   "Aura quiz me on chemistry", "thank you",
                   "Aura remind me to drink water at 5 pm"]
        start = time.perf_counter()
        n = 200
        for i in range(n):
            E.process(samples[i % len(samples)], "NORMAL")
        avg_ms = (time.perf_counter() - start) / n * 1000
        self.assertLess(avg_ms, 50.0, f"avg {avg_ms:.2f} ms")

if __name__ == "__main__":
    unittest.main()
