"""HAL runs under the real LifecycleManager; Speech-style EMOTION_CHANGED reaches the ESP32."""
import unittest
from core.event_bus import EventBus
from core.constants import RobotEvent
from core.lifecycle import LifecycleManager
from core.state_machine import build_aura_state_machine
from hardware import HardwareManager, HardwareConfig, MockSerialTransport
from hardware.tests._helpers import quiet_config, wait_until

class TestIntegration(unittest.TestCase):
    def test_lifecycle_and_face_forwarding(self):
        bus = EventBus()
        sm = build_aura_state_machine(bus)
        life = LifecycleManager(bus, sm)
        transport = MockSerialTransport(ports=["MOCK-ESP32"])
        hal = HardwareManager(bus, quiet_config(), transport)
        life.register(hal)
        life.startup()
        self.assertTrue(life.health_report()["hardware"])
        wait_until(lambda: hal.serial_state.name == "CONNECTED")
        # Simulate the Speech Manager announcing an emotion; HAL drives the face.
        bus.emit(RobotEvent.EMOTION_CHANGED, {"emotion": "CELEBRATE"}, source="speech")
        self.assertTrue(wait_until(lambda: "CELEBRATE" in transport.written))
        life.shutdown()

if __name__ == "__main__":
    unittest.main()
