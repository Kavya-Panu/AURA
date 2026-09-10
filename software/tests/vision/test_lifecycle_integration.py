"""VisionManager works under the real LifecycleManager + StateMachine."""
import unittest
from core.event_bus import EventBus
from core.constants import RobotEvent, RobotState
from core.lifecycle import LifecycleManager
from core.state_machine import build_aura_state_machine
from vision.vision_manager import VisionManager


class FakeDetector:
    name = "face"
    def initialize(self): pass
    def start(self): pass
    def stop(self): pass
    def health_check(self): return True


class TestLifecycleIntegration(unittest.TestCase):
    def test_registered_and_run_by_lifecycle(self):
        bus = EventBus()
        sm = build_aura_state_machine(bus)
        lifecycle = LifecycleManager(bus, sm)
        vm = VisionManager(bus)
        vm.register_detector(FakeDetector())
        lifecycle.register(vm)

        started = []
        bus.subscribe(RobotEvent.VISION_STARTED, lambda e: started.append(1))

        lifecycle.startup()
        self.assertTrue(vm.context.snapshot().running)
        self.assertEqual(sm.state, RobotState.IDLE)
        self.assertTrue(started)

        report = lifecycle.health_report()
        self.assertIn("vision", report)
        self.assertTrue(report["vision"])

        lifecycle.shutdown()
        self.assertFalse(vm.context.snapshot().running)


if __name__ == "__main__":
    unittest.main()
