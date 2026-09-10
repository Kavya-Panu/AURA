import unittest
from memory.memory_retention import (
    MemoryRetention, RetentionAction, DecisionPolicy, RetentionReport)
from memory.memory_config import RetentionPolicy
from memory.memory_record import MemoryRecord, MemoryType, Importance

NOW = 1_000_000_000.0
DAY = 60 * 60 * 24

def rec(importance, age_days=0.0, confidence=1.0, expires_at=None, meta=None):
    return MemoryRecord(MemoryType.FACT, {"x": 1}, importance,
                        confidence=confidence,
                        created_at=NOW - age_days * DAY,
                        updated_at=NOW - age_days * DAY,
                        expires_at=expires_at, metadata=meta or {})

class TestRetention(unittest.TestCase):
    def setUp(self):
        self.r = MemoryRetention(clock=lambda: NOW)

    def _action(self, record):
        return self.r.decide(record, now=NOW).action

    def test_critical_never_removed(self):
        self.assertEqual(self._action(rec(Importance.CRITICAL, age_days=100000)),
                         RetentionAction.KEEP)

    def test_high_kept_indefinitely(self):
        self.assertEqual(self._action(rec(Importance.HIGH, age_days=100000)),
                         RetentionAction.KEEP)

    def test_medium_summarized_after_period(self):
        self.assertEqual(self._action(rec(Importance.MEDIUM, age_days=40)),
                         RetentionAction.SUMMARIZE)
        self.assertEqual(self._action(rec(Importance.MEDIUM, age_days=5)),
                         RetentionAction.KEEP)

    def test_low_archived_then_removed(self):
        self.assertEqual(self._action(rec(Importance.LOW, age_days=20)),
                         RetentionAction.ARCHIVE)
        self.assertEqual(self._action(rec(Importance.LOW, age_days=90)),
                         RetentionAction.REMOVE)
        self.assertEqual(self._action(rec(Importance.LOW, age_days=2)),
                         RetentionAction.KEEP)

    def test_temporary_expires(self):
        self.assertEqual(self._action(rec(Importance.TEMPORARY, expires_at=NOW - 1)),
                         RetentionAction.REMOVE)

    def test_hard_expiry_always_removes(self):
        # even a HIGH memory past an explicit expires_at is removed
        self.assertEqual(self._action(rec(Importance.HIGH, expires_at=NOW - 1)),
                         RetentionAction.REMOVE)

    def test_low_confidence_low_removed_early(self):
        self.assertEqual(
            self._action(rec(Importance.LOW, age_days=1, confidence=0.1)),
            RetentionAction.REMOVE)

    def test_frequently_used_is_sticky(self):
        # a low memory old enough to archive, but heavily used -> KEEP
        self.assertEqual(
            self._action(rec(Importance.LOW, age_days=20,
                             meta={"use_count": 10})),
            RetentionAction.KEEP)

    def test_evaluate_batch_report(self):
        records = [rec(Importance.CRITICAL), rec(Importance.LOW, age_days=20),
                   rec(Importance.TEMPORARY, expires_at=NOW - 1),
                   rec(Importance.MEDIUM, age_days=40)]
        report = self.r.evaluate(records, now=NOW)
        self.assertIsInstance(report, RetentionReport)
        self.assertEqual(len(report.to_remove), 1)
        self.assertEqual(len(report.to_archive), 1)
        self.assertEqual(len(report.to_summarize), 1)
        self.assertEqual(report.counts()["KEEP"], 1)

    def test_configurable_policy(self):
        pol = DecisionPolicy(medium_summarize_after_s=DAY)   # 1 day
        r = MemoryRetention(decision_policy=pol, clock=lambda: NOW)
        self.assertEqual(r.decide(rec(Importance.MEDIUM, age_days=2), now=NOW).action,
                         RetentionAction.SUMMARIZE)

    def test_decision_only_no_delete(self):
        # returns actions; must not import providers or delete anything
        import ast, pathlib, memory.memory_retention as m
        mods = {n.module for n in ast.walk(ast.parse(pathlib.Path(m.__file__).read_text()))
                if isinstance(n, ast.ImportFrom) and n.module}
        self.assertNotIn("memory.memory_provider", mods)
        self.assertNotIn("memory.memory_manager", mods)

if __name__ == "__main__":
    unittest.main()
