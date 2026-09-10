"""Brain runs under the real LifecycleManager + StateMachine."""
import unittest
from core.event_bus import EventBus
from core.constants import RobotEvent
from core.lifecycle import LifecycleManager
from core.state_machine import build_aura_state_machine
from brain import BrainManager, BrainConfig, MockProvider

class TestIntegration(unittest.TestCase):
    def test_lifecycle_runs_brain(self):
        bus = EventBus()
        sm = build_aura_state_machine(bus)
        life = LifecycleManager(bus, sm)
        brain = BrainManager(bus, BrainConfig.default())
        brain.register_provider(MockProvider("ollama", is_local=True))
        brain.register_provider(MockProvider("claude"))
        life.register(brain)
        life.startup()
        self.assertTrue(life.health_report()["brain"])
        # end-to-end: a question on the bus yields an answer
        answers = []
        bus.subscribe(RobotEvent.ANSWER_READY, lambda e: answers.append(e.data))
        bus.emit(RobotEvent.QUESTION_RECEIVED, {"text": "hello", "mode": "ASSISTANT"},
                 source="intent")
        self.assertEqual(len(answers), 1)
        life.shutdown()

if __name__ == "__main__":
    unittest.main()
