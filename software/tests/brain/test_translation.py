import unittest
from core.constants import RobotEvent
from brain.brain_config import TaskKind
from brain.provider_registry import MockProvider, GenerationRequest
from brain.translation_service import TranslationService, TranslationRequest
from brain.brain_result import BrainResult
from brain.tests._helpers import build_brain, collect

class TestTranslation(unittest.TestCase):
    def test_service_returns_translation_field(self):
        def gen(request, task):
            # echo target so we can assert routing
            return BrainResult(response="hola", provider="mock",
                               confidence=0.9, success=True)
        svc = TranslationService(gen)
        r = svc.translate(TranslationRequest("hello", "en", "es"))
        self.assertEqual(r.translation, "hola")
        self.assertEqual(r.metadata["target_lang"], "es")

    def test_translation_uses_translation_task(self):
        seen_tasks = []
        def gen(request, task):
            seen_tasks.append(task)
            return BrainResult(response="x", provider="mock", success=True)
        TranslationService(gen).translate(TranslationRequest("hi", "en", "fr"))
        self.assertEqual(seen_tasks, [TaskKind.TRANSLATION])

    def test_manager_translate_emits_events(self):
        bus, brain = build_brain()
        seen = collect(bus)
        r = brain.translate("hello", "es")
        self.assertTrue(r.success)
        self.assertTrue(r.translation)
        types = [t for t, _ in seen]
        self.assertIn(RobotEvent.TRANSLATION_STARTED, types)
        self.assertIn(RobotEvent.TRANSLATION_COMPLETED, types)
        brain.stop()

    def test_detect_language_future_hook(self):
        svc = TranslationService(lambda r, t: BrainResult(success=True))
        self.assertIsNone(svc.detect_language("bonjour"))

if __name__ == "__main__":
    unittest.main()
