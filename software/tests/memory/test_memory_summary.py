import unittest
from memory.memory_summary import (
    MemorySummary, HeuristicSummary, CallableSummaryStrategy, SummaryStrategy,
    SummaryOutcome)
from memory.memory_config import SummarizationConfig
from memory.memory_record import MemoryRecord, MemoryType, Importance

def convo(n, importance=Importance.LOW):
    return [MemoryRecord(MemoryType.CONVERSATION, {"turn": i, "text": f"msg {i}"},
                         importance, created_at=float(i), updated_at=float(i))
            for i in range(n)]

class TestMemorySummary(unittest.TestCase):
    def test_heuristic_is_strategy(self):
        self.assertIsInstance(HeuristicSummary(), SummaryStrategy)

    def test_returns_memory_record(self):
        s = MemorySummary()
        out = s.summarize(convo(5), force=True)
        self.assertIsInstance(out, SummaryOutcome)
        self.assertIsInstance(out.summary, MemoryRecord)
        self.assertEqual(out.summary.content["count"], 5)
        self.assertEqual(len(out.source_ids), 5)

    def test_summary_marked_and_tagged(self):
        out = MemorySummary().summarize(convo(3), force=True)
        self.assertTrue(out.summary.metadata["summary"])
        self.assertIn("summary", out.summary.tags)
        self.assertEqual(out.summary.metadata["strategy"], "heuristic")

    def test_threshold_respected(self):
        cfg = SummarizationConfig(min_records_to_summarize=10)
        s = MemorySummary(cfg)
        self.assertIsNone(s.summarize(convo(5)))          # below threshold
        self.assertIsNotNone(s.summarize(convo(5), force=True))

    def test_empty_returns_none(self):
        self.assertIsNone(MemorySummary().summarize([]))

    def test_preserves_time_span_and_tags(self):
        recs = convo(4)
        recs[0] = recs[0].evolve(tags=("important",))
        out = MemorySummary().summarize(recs, force=True)
        self.assertEqual(out.summary.content["from"], 0.0)
        self.assertIn("important", out.summary.content["tags"])

    def test_dominant_type_inference(self):
        recs = convo(3) + [MemoryRecord(MemoryType.QUIZ_RESULT, {"s": 1})]
        out = MemorySummary().summarize(recs, force=True)
        self.assertEqual(out.summary.memory_type, MemoryType.CONVERSATION)

    def test_named_wrappers(self):
        s = MemorySummary()
        self.assertEqual(
            s.summarize_quiz_history(convo(3), force=True).summary.memory_type,
            MemoryType.QUIZ_RESULT)
        self.assertEqual(
            s.summarize_focus_sessions(convo(3), force=True).summary.memory_type,
            MemoryType.FOCUS_SESSION)

    def test_compress_low_importance_keeps_medium(self):
        recs = convo(4, importance=Importance.LOW)
        out = MemorySummary().compress_low_importance(recs, force=True)
        self.assertEqual(out.summary.importance, Importance.MEDIUM)

    def test_pluggable_llm_style_strategy(self):
        # A callable stands in for a future LLM summarizer; the service never
        # calls an LLM itself - reasoning lives in the injected callable.
        calls = {"n": 0}
        def fake_llm(records):
            calls["n"] += 1
            return {"summary": "LLM digest", "count": len(records)}
        s = MemorySummary(strategy=CallableSummaryStrategy(fake_llm, "llm"))
        out = s.summarize(convo(3), force=True)
        self.assertEqual(out.summary.content["summary"], "LLM digest")
        self.assertEqual(out.summary.metadata["strategy"], "llm")
        self.assertEqual(calls["n"], 1)

    def test_set_strategy_runtime_swap(self):
        s = MemorySummary()
        self.assertEqual(s.strategy_name, "heuristic")
        s.set_strategy(CallableSummaryStrategy(lambda r: {"x": 1}, "custom"))
        self.assertEqual(s.strategy_name, "custom")

    def test_never_touches_storage(self):
        # module must not import providers or the manager
        import ast, pathlib, memory.memory_summary as m
        mods = {n.module for n in ast.walk(ast.parse(pathlib.Path(m.__file__).read_text()))
                if isinstance(n, ast.ImportFrom) and n.module}
        self.assertNotIn("memory.memory_provider", mods)
        self.assertNotIn("memory.memory_manager", mods)
        # and must not import any brain/LLM
        self.assertFalse(any("brain" in x for x in mods))

if __name__ == "__main__":
    unittest.main()
