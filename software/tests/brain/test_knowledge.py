import unittest
from brain.knowledge_service import KnowledgeService, KnowledgeRequest
from brain.brain_config import TaskKind

class TestKnowledge(unittest.TestCase):
    def setUp(self):
        self.svc = KnowledgeService()

    def test_summary_task(self):
        self.assertEqual(
            self.svc.classify(KnowledgeRequest("x", style="summary")),
            TaskKind.SUMMARY)

    def test_stepwise_is_teaching(self):
        self.assertEqual(
            self.svc.classify(KnowledgeRequest("x", style="stepwise")),
            TaskKind.TEACHING)

    def test_math_subject_is_teaching(self):
        self.assertEqual(
            self.svc.classify(KnowledgeRequest("2+2?", subject="math")),
            TaskKind.TEACHING)

    def test_short_general_is_simple(self):
        self.assertEqual(
            self.svc.classify(KnowledgeRequest("hi", subject="general")),
            TaskKind.SIMPLE_QA)

    def test_long_general_is_complex(self):
        long_q = "explain " + "word " * 50
        self.assertEqual(
            self.svc.classify(KnowledgeRequest(long_q, subject="general")),
            TaskKind.COMPLEX_REASONING)

    def test_prompt_augmentation(self):
        out = self.svc.augment_prompt(
            "base", KnowledgeRequest("q", subject="electronics", style="stepwise"))
        self.assertIn("base", out)
        self.assertIn("electronics", out.lower())
        self.assertIn("step", out.lower())

if __name__ == "__main__":
    unittest.main()
