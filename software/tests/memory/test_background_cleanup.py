"""The background cleanup thread expires memories on its own (deterministic via trigger)."""
import unittest
from memory import MemoryManager, MemoryConfig, MemoryType, Importance
from memory.memory_config import RetentionPolicy, CleanupConfig
from memory.tests._helpers import build_memory, collect, FakeClock, wait_until
from core.constants import RobotEvent

class TestBackgroundCleanup(unittest.TestCase):
    def test_background_thread_expires(self):
        clk = FakeClock()
        cfg = MemoryConfig(
            retention=RetentionPolicy(temporary_ttl_s=10),
            cleanup=CleanupConfig(enabled=True, interval_s=0.05))
        bus, mem = build_memory(config=cfg, clock=clk, start=True)
        seen = collect(bus)
        r = mem.store(MemoryType.TEMPORARY_CONTEXT, {"n": 1},
                      importance=Importance.TEMPORARY)
        clk.advance(11)                      # now past expiry
        mem.trigger_cleanup()                # wake the loop immediately
        ok = wait_until(lambda: mem.provider.get(r.memory_id) is None, timeout_s=2.0)
        mem.stop()
        self.assertTrue(ok)
        self.assertIn(RobotEvent.MEMORY_CLEANUP_COMPLETED, [t for t, _ in seen])

    def test_cleanup_thread_starts_and_stops(self):
        cfg = MemoryConfig(cleanup=CleanupConfig(enabled=True, interval_s=0.05))
        bus, mem = build_memory(config=cfg, start=True)
        self.assertTrue(mem.health_check())
        mem.stop()                            # should join cleanly
        self.assertIsNone(mem._cleanup_thread)

    def test_disabled_cleanup_no_thread(self):
        cfg = MemoryConfig(cleanup=CleanupConfig(enabled=False))
        bus, mem = build_memory(config=cfg, start=True)
        self.assertIsNone(mem._cleanup_thread)
        mem.stop()

if __name__ == "__main__":
    unittest.main()
