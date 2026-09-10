import threading
import unittest
from memory.memory_context import MemoryContext, CacheStats, MemoryContextSnapshot
from memory.memory_record import MemoryRecord, MemoryType, Importance

def rec(**c):
    return MemoryRecord(MemoryType.FACT, c or {"x": 1})

class TestMemoryContext(unittest.TestCase):
    def test_session_and_provider(self):
        ctx = MemoryContext()
        ctx.set_conversation("conv-1"); ctx.set_session("sess-1")
        ctx.set_provider("sqlite")
        self.assertEqual(ctx.conversation_id, "conv-1")
        self.assertEqual(ctx.session_id, "sess-1")
        self.assertEqual(ctx.provider, "sqlite")

    def test_recent_tracking_bounded(self):
        ctx = MemoryContext(recent_capacity=3)
        for i in range(5):
            ctx.record_stored(rec(i=i))
        self.assertEqual(len(ctx.recent_stored()), 3)     # bounded

    def test_cache_hit_miss_stats(self):
        ctx = MemoryContext()
        r = rec()
        ctx.cache_put(r)
        self.assertIsNotNone(ctx.cache_get(r.memory_id))  # hit
        self.assertIsNone(ctx.cache_get("missing"))       # miss
        stats = ctx.cache_stats()
        self.assertEqual(stats.hits, 1)
        self.assertEqual(stats.misses, 1)
        self.assertEqual(stats.hit_rate, 0.5)

    def test_cache_lru_eviction(self):
        ctx = MemoryContext(cache_capacity=2)
        a, b, c = rec(a=1), rec(b=2), rec(c=3)
        ctx.cache_put(a); ctx.cache_put(b)
        ctx.cache_get(a.memory_id)          # touch a -> b now LRU
        ctx.cache_put(c)                    # evicts b
        self.assertIsNotNone(ctx.cache_get(a.memory_id))
        self.assertIsNone(ctx.cache_get(b.memory_id))     # evicted
        self.assertIsNotNone(ctx.cache_get(c.memory_id))

    def test_cache_invalidate(self):
        ctx = MemoryContext()
        r = rec(); ctx.cache_put(r)
        ctx.cache_invalidate(r.memory_id)
        self.assertIsNone(ctx.cache_get(r.memory_id))

    def test_maintenance_markers(self):
        t = [500.0]
        ctx = MemoryContext(clock=lambda: t[0])
        ctx.mark_cleanup(); ctx.mark_summary()
        self.assertEqual(ctx.last_cleanup_at, 500.0)
        self.assertEqual(ctx.last_summary_at, 500.0)

    def test_snapshot(self):
        ctx = MemoryContext()
        ctx.set_conversation("c"); ctx.set_provider("json")
        ctx.record_stored(rec()); ctx.record_retrieved(rec())
        snap = ctx.snapshot()
        self.assertIsInstance(snap, MemoryContextSnapshot)
        self.assertEqual(snap.conversation_id, "c")
        self.assertEqual(snap.provider, "json")
        self.assertEqual(len(snap.recent_stored), 1)
        self.assertIsInstance(snap.cache, CacheStats)

    def test_reset_clears_runtime_state(self):
        ctx = MemoryContext()
        ctx.set_conversation("c"); ctx.record_stored(rec()); ctx.cache_put(rec())
        ctx.reset()
        self.assertIsNone(ctx.conversation_id)
        self.assertEqual(ctx.recent_stored(), [])
        self.assertEqual(ctx.cache_stats().size, 0)

    def test_does_not_persist(self):
        # runtime only: must not import providers/manager or do file/db IO
        import ast, pathlib, memory.memory_context as m
        src = pathlib.Path(m.__file__).read_text()
        mods = {n.module for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.ImportFrom) and n.module}
        self.assertNotIn("memory.memory_provider", mods)
        self.assertNotIn("memory.memory_manager", mods)
        for io in ("open(", "json.dump", "sqlite3", "os.replace"):
            self.assertNotIn(io, src)

    def test_thread_safety(self):
        ctx = MemoryContext(cache_capacity=10000)
        def worker(i):
            for j in range(200):
                r = rec(i=i, j=j)
                ctx.record_stored(r)
                ctx.cache_get(r.memory_id)
                ctx.snapshot()
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
        for t in threads: t.start()
        for t in threads: t.join()
        # 6*200 puts, all hits
        self.assertEqual(ctx.cache_stats().hits, 1200)

if __name__ == "__main__":
    unittest.main()
