import time
import unittest

from brain import BrainConfig, BrainManager, MockProvider, ProviderConfig, SelectionRules
from core.constants import RobotEvent
from core.event_bus import EventBus
from hardware import HardwareConfig, HardwareManager, HealthConfig, MockSerialTransport
from integration import BrainHardwareBridge


def wait_until(predicate, timeout_s=2.0):
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class TestBrainHardwareBridge(unittest.TestCase):
    def test_question_drives_thinking_then_answer_emotion(self):
        bus = EventBus()

        hw_cfg = HardwareConfig()
        hw_cfg.health = HealthConfig(enabled=False)
        transport = MockSerialTransport(
            ports=["MOCK-ESP32"],
            responder=lambda line: ["PONG"] if line == "PING" else ["OK"],
        )
        hardware = HardwareManager(bus, hw_cfg, transport)
        hardware.initialize()
        hardware.start()

        provider_cfg = ProviderConfig(
            name="mock", model="mock", priority=1, is_local=True)
        brain_cfg = BrainConfig(
            providers=[provider_cfg],
            selection=SelectionRules(default_chain=["mock"]),
        )
        brain = BrainManager(bus, brain_cfg)
        brain.register_provider(MockProvider(
            "mock",
            is_local=True,
            responder=lambda _req: "The answer is 42.",
        ))
        bridge = BrainHardwareBridge(bus)

        brain.initialize()
        bridge.initialize()
        brain.start()
        bridge.start()

        try:
            bus.emit(
                RobotEvent.QUESTION_RECEIVED,
                {"text": "Say hello", "mode": "ASSISTANT"},
                source="test",
            )
            self.assertTrue(wait_until(lambda: "THINK" in transport.written))
            self.assertTrue(wait_until(lambda: "NEUTRAL" in transport.written))
        finally:
            bridge.stop()
            brain.stop()
            hardware.stop()


if __name__ == "__main__":
    unittest.main()
