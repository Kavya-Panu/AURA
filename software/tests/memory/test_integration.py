"""MemoryManager runs under the real LifecycleManager; Brain-style access via the manager only."""
import unittest
from core.event_bus import EventBus
from core.constants import RobotEvent
from core.lifecycle import LifecycleManager
from core.state_machine import build_aura_state_machine
from memory import MemoryManager, MemoryConfig, MemoryType, Importance, SearchQuery, SQLiteProvider

class TestIntegration(unittest.TestCase):
    def test_lifecycle_runs_memory(self):
        bus = EventBus()
        sm = build_aura_state_machine(bus)
        life = LifecycleManager(bus, sm)
        mem = MemoryManager(bus, MemoryConfig(), provider=SQLiteProvider(":memory:"))
        life.register(mem)
        life.startup()
        self.assertTrue(life.health_report()["memory"])
        # Brain-style usage: store a profile fact, later recall it - all via the
        # manager API (storage backend is invisible to callers).
        mem.store(MemoryType.USER_PROFILE, {"name": "Sky", "subject": "physics"},
                  importance=Importance.CRITICAL, tags=("profile",))
        hits = mem.search(SearchQuery(text="physics"))
        self.assertTrue(hits)
        life.shutdown()

if __name__ == "__main__":
    unittest.main()
