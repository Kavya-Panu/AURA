import os
import tempfile
import threading
import unittest
from memory.memory_provider import (
    InMemoryProvider, JSONProvider, SQLiteProvider, VectorProvider, MemoryProvider)
from memory.memory_record import MemoryRecord, MemoryType, Importance
from memory.memory_exceptions import ProviderError

def rec(**kw):
    return MemoryRecord(kw.pop("t", MemoryType.FACT), kw.pop("c", {"x": 1}), **kw)

class ProviderContract:
    """Shared contract tests run against every concrete provider."""
    def make(self) -> MemoryProvider: raise NotImplementedError

    def test_is_provider(self):
        self.assertIsInstance(self.make(), MemoryProvider)

    def test_put_get(self):
        p = self.make(); r = rec()
        p.put(r)
        self.assertEqual(p.get(r.memory_id).memory_id, r.memory_id)

    def test_get_missing_none(self):
        self.assertIsNone(self.make().get("nope"))

    def test_delete(self):
        p = self.make(); r = rec(); p.put(r)
        self.assertTrue(p.delete(r.memory_id))
        self.assertFalse(p.delete(r.memory_id))
        self.assertIsNone(p.get(r.memory_id))

    def test_all_and_clear(self):
        p = self.make()
        for _ in range(3): p.put(rec())
        self.assertEqual(len(p.all()), 3)
        p.clear()
        self.assertEqual(len(p.all()), 0)

    def test_replace_on_same_id(self):
        p = self.make(); r = rec(c={"v": 1}); p.put(r)
        p.put(r.evolve(content={"v": 2}))
        self.assertEqual(p.get(r.memory_id).content["v"], 2)
        self.assertEqual(len(p.all()), 1)

class TestInMemory(ProviderContract, unittest.TestCase):
    def make(self): return InMemoryProvider()

    def test_thread_safe_writes(self):
        p = InMemoryProvider()
        def worker():
            for _ in range(200): p.put(rec())
        ts = [threading.Thread(target=worker) for _ in range(8)]
        for t in ts: t.start()
        for t in ts: t.join()
        self.assertEqual(len(p.all()), 1600)

class TestSQLite(ProviderContract, unittest.TestCase):
    def make(self): return SQLiteProvider(":memory:")

class TestJSON(ProviderContract, unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "mem.json")
    def make(self): return JSONProvider(self.path)

    def test_persists_across_instances(self):
        p1 = JSONProvider(self.path); r = rec(); p1.put(r)
        p2 = JSONProvider(self.path)                 # reload from disk
        self.assertEqual(p2.get(r.memory_id).memory_id, r.memory_id)

class TestVectorStub(unittest.TestCase):
    def test_is_provider_but_raises(self):
        v = VectorProvider()
        self.assertIsInstance(v, MemoryProvider)
        with self.assertRaises(ProviderError):
            v.put(rec())

if __name__ == "__main__":
    unittest.main()
