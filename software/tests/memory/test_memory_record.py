import unittest
from memory.memory_record import MemoryRecord, MemoryType, Importance

class TestRecord(unittest.TestCase):
    def test_defaults(self):
        r = MemoryRecord(MemoryType.FACT, {"x": 1})
        self.assertEqual(r.importance, Importance.MEDIUM)
        self.assertTrue(r.memory_id)
        self.assertIsNone(r.expires_at)

    def test_is_expired(self):
        r = MemoryRecord(MemoryType.FACT, {}, expires_at=100.0)
        self.assertTrue(r.is_expired(now=101.0))
        self.assertFalse(r.is_expired(now=99.0))

    def test_never_expires_without_expiry(self):
        r = MemoryRecord(MemoryType.FACT, {})
        self.assertFalse(r.is_expired(now=1e12))

    def test_evolve_updates_timestamp(self):
        r = MemoryRecord(MemoryType.FACT, {"a": 1}, updated_at=1.0)
        r2 = r.evolve(clock=lambda: 5.0, content={"a": 2})
        self.assertEqual(r2.content, {"a": 2})
        self.assertEqual(r2.updated_at, 5.0)
        self.assertEqual(r2.memory_id, r.memory_id)   # identity preserved

    def test_roundtrip(self):
        r = MemoryRecord(MemoryType.QUIZ_RESULT, {"score": 90},
                         importance=Importance.HIGH, tags=("a", "b"))
        r2 = MemoryRecord.from_dict(r.to_dict())
        self.assertEqual(r2.memory_type, MemoryType.QUIZ_RESULT)
        self.assertEqual(r2.importance, Importance.HIGH)
        self.assertEqual(r2.tags, ("a", "b"))

    def test_importance_ordering(self):
        self.assertGreater(Importance.CRITICAL.value, Importance.TEMPORARY.value)

if __name__ == "__main__":
    unittest.main()
