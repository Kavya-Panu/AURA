"""MemoryManager: store/retrieve/update/delete, retention, expiry, summarize, forget, events, threads."""
import threading
import unittest
from core.constants import RobotEvent
from core.lifecycle import Module
from memory import (MemoryManager, MemoryConfig, MemoryType, Importance,
                    SearchQuery, InMemoryProvider, SQLiteProvider)
from memory.memory_config import RetentionPolicy, CleanupConfig
from memory.memory_exceptions import MemoryNotFound, MemoryValidationError
from memory.tests._helpers import build_memory, collect, FakeClock, wait_until

class TestMemoryManager(unittest.TestCase):
    def test_is_module(self):
        bus, mem = build_memory()
        self.assertIsInstance(mem, Module)

    def test_store_and_retrieve(self):
        bus, mem = build_memory(); seen = collect(bus)
        r = mem.store(MemoryType.USER_PROFILE, {"name": "Sky"})
        self.assertEqual(mem.retrieve(r.memory_id).content["name"], "Sky")
        self.assertIn(RobotEvent.MEMORY_STORED, [t for t, _ in seen])

    def test_retrieve_missing_raises(self):
        bus, mem = build_memory()
        with self.assertRaises(MemoryNotFound):
            mem.retrieve("nope")

    def test_validation(self):
        bus, mem = build_memory()
        with self.assertRaises(MemoryValidationError):
            mem.store(MemoryType.FACT, "not a dict")
        with self.assertRaises(MemoryValidationError):
            mem.store(MemoryType.FACT, {}, confidence=2.0)

    def test_update(self):
        bus, mem = build_memory(); seen = collect(bus)
        r = mem.store(MemoryType.PREFERENCE, {"theme": "dark"})
        u = mem.update(r.memory_id, content={"theme": "light"})
        self.assertEqual(u.content["theme"], "light")
        self.assertIn(RobotEvent.MEMORY_UPDATED, [t for t, _ in seen])

    def test_delete(self):
        bus, mem = build_memory(); seen = collect(bus)
        r = mem.store(MemoryType.FACT, {"x": 1})
        self.assertTrue(mem.delete(r.memory_id))
        self.assertIsNone(mem.get(r.memory_id))
        self.assertIn(RobotEvent.MEMORY_DELETED, [t for t, _ in seen])

    def test_importance_drives_default_expiry(self):
        clk = FakeClock()
        bus, mem = build_memory(clock=clk)
        crit = mem.store(MemoryType.USER_PROFILE, {"n": 1}, importance=Importance.CRITICAL)
        temp = mem.store(MemoryType.TEMPORARY_CONTEXT, {"n": 2}, importance=Importance.TEMPORARY)
        self.assertIsNone(crit.expires_at)                 # critical never expires
        self.assertIsNotNone(temp.expires_at)

    def test_expired_not_retrievable(self):
        clk = FakeClock()
        cfg = MemoryConfig(retention=RetentionPolicy(temporary_ttl_s=10))
        bus, mem = build_memory(config=cfg, clock=clk)
        r = mem.store(MemoryType.TEMPORARY_CONTEXT, {"n": 1}, importance=Importance.TEMPORARY)
        clk.advance(11)
        with self.assertRaises(MemoryNotFound):
            mem.retrieve(r.memory_id)

    def test_run_cleanup_expires(self):
        clk = FakeClock()
        cfg = MemoryConfig(retention=RetentionPolicy(temporary_ttl_s=10),
                           cleanup=CleanupConfig(enabled=False))
        bus, mem = build_memory(config=cfg, clock=clk); seen = collect(bus)
        mem.store(MemoryType.TEMPORARY_CONTEXT, {"n": 1}, importance=Importance.TEMPORARY)
        clk.advance(11)
        stats = mem.run_cleanup()
        self.assertEqual(stats["expired"], 1)
        self.assertIn(RobotEvent.MEMORY_EXPIRED, [t for t, _ in seen])
        self.assertIn(RobotEvent.MEMORY_CLEANUP_COMPLETED, [t for t, _ in seen])

    def test_critical_survives_cleanup(self):
        clk = FakeClock()
        cfg = MemoryConfig(cleanup=CleanupConfig(enabled=False))
        bus, mem = build_memory(config=cfg, clock=clk)
        r = mem.store(MemoryType.USER_PROFILE, {"n": 1}, importance=Importance.CRITICAL)
        clk.advance(10**9)
        mem.run_cleanup()
        self.assertIsNotNone(mem.get(r.memory_id))       # still there

    def test_forget_unimportant(self):
        bus, mem = build_memory(); seen = collect(bus)
        mem.store(MemoryType.FACT, {"n": 1}, importance=Importance.LOW)
        mem.store(MemoryType.FACT, {"n": 2}, importance=Importance.LOW)
        mem.store(MemoryType.USER_PROFILE, {"n": 3}, importance=Importance.CRITICAL)
        forgotten = mem.forget_unimportant(max_importance=Importance.LOW)
        self.assertEqual(forgotten, 2)
        self.assertEqual(len(mem.all_live()), 1)         # critical remains
        self.assertIn(RobotEvent.MEMORY_FORGOTTEN, [t for t, _ in seen])

    def test_temporary_cap_enforced(self):
        clk = FakeClock()
        cfg = MemoryConfig(retention=RetentionPolicy(max_temporary_total=3,
                                                     temporary_ttl_s=10**9),
                           cleanup=CleanupConfig(enabled=False))
        bus, mem = build_memory(config=cfg, clock=clk)
        for i in range(6):
            mem.store(MemoryType.TEMPORARY_CONTEXT, {"i": i},
                      importance=Importance.TEMPORARY)
            clk.advance(1)
        mem.run_cleanup()
        temps = mem.by_type(MemoryType.TEMPORARY_CONTEXT)
        self.assertEqual(len(temps), 3)                  # oldest 3 dropped

    def test_summarize(self):
        cfg = MemoryConfig()
        cfg.summarization.min_records_to_summarize = 3
        bus, mem = build_memory(config=cfg); seen = collect(bus)
        for i in range(5):
            mem.store(MemoryType.CONVERSATION, {"turn": i}, importance=Importance.LOW)
        summary = mem.summarize(MemoryType.CONVERSATION)
        self.assertIsNotNone(summary)
        self.assertEqual(summary.metadata["summarized_count"], 5)
        # originals replaced by the single summary
        convos = mem.by_type(MemoryType.CONVERSATION)
        self.assertEqual(len(convos), 1)
        self.assertTrue(convos[0].metadata.get("summary"))
        self.assertIn(RobotEvent.MEMORY_SUMMARIZED, [t for t, _ in seen])

    def test_summarize_uses_injected_summarizer_not_llm(self):
        called = {"n": 0}
        def summarizer(records):
            called["n"] += 1
            return {"summary": "custom", "count": len(records)}
        cfg = MemoryConfig(); cfg.summarization.min_records_to_summarize = 2
        bus, mem = build_memory(config=cfg, summarizer=summarizer)
        for i in range(3):
            mem.store(MemoryType.STUDY_SESSION, {"i": i})
        s = mem.summarize(MemoryType.STUDY_SESSION)
        self.assertEqual(called["n"], 1)
        self.assertEqual(s.content["summary"], "custom")

    def test_summarize_below_threshold_noop(self):
        cfg = MemoryConfig(); cfg.summarization.min_records_to_summarize = 10
        bus, mem = build_memory(config=cfg)
        mem.store(MemoryType.CONVERSATION, {"turn": 1})
        self.assertIsNone(mem.summarize(MemoryType.CONVERSATION))

    def test_search(self):
        bus, mem = build_memory()
        mem.store(MemoryType.FACT, {"text": "loves physics"}, tags=("science",))
        mem.store(MemoryType.FACT, {"text": "hates mornings"})
        hits = mem.search(SearchQuery(text="physics"))
        self.assertEqual(len(hits), 1)

    def test_search_excludes_expired(self):
        clk = FakeClock()
        cfg = MemoryConfig(retention=RetentionPolicy(temporary_ttl_s=5))
        bus, mem = build_memory(config=cfg, clock=clk)
        mem.store(MemoryType.TEMPORARY_CONTEXT, {"text": "temp physics note"},
                  importance=Importance.TEMPORARY)
        clk.advance(6)
        self.assertEqual(len(mem.search(SearchQuery(text="physics"))), 0)

    def test_provider_swap_migrates(self):
        bus, mem = build_memory(provider=InMemoryProvider())
        r = mem.store(MemoryType.USER_PROFILE, {"name": "Sky"},
                      importance=Importance.CRITICAL)
        mem.set_provider(SQLiteProvider(":memory:"))
        self.assertEqual(mem.provider.name, "sqlite")
        self.assertIsNotNone(mem.get(r.memory_id))       # migrated

    def test_health_check(self):
        bus, mem = build_memory()
        self.assertTrue(mem.health_check())

    def test_never_reasons_or_controls(self):
        import ast, memory.memory_manager as m
        tree = ast.parse(open(m.__file__).read())
        mods = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module:
                mods.add(n.module)
        # must not import brain/LLM, speech, hardware, emotion, or mode managers
        self.assertFalse(any(("brain" in x or "speech" in x or "hardware" in x
                              or "emotion" in x or "mode." in x) for x in mods))

    def test_thread_safety_concurrent_store(self):
        bus, mem = build_memory()
        def worker(i):
            for j in range(50):
                mem.store(MemoryType.FACT, {"i": i, "j": j})
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(len(mem.all_live()), 400)

if __name__ == "__main__":
    unittest.main()
