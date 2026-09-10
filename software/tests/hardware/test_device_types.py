import unittest
from hardware.device_types import (
    DeviceType, ConnectionState, HealthState, CommandPriority)

class TestDeviceTypes(unittest.TestCase):
    def test_device_types_cover_spec(self):
        for name in ("ESP32", "SERVO", "SPEAKER", "DISPLAY", "PROPELLER",
                     "LED", "BATTERY", "CAMERA", "MICROPHONE"):
            self.assertTrue(hasattr(DeviceType, name))

    def test_connection_states(self):
        for name in ("DISCONNECTED", "CONNECTING", "CONNECTED",
                     "RECONNECTING", "ERROR"):
            self.assertTrue(hasattr(ConnectionState, name))

    def test_health_states(self):
        for name in ("UNKNOWN", "HEALTHY", "DEGRADED", "FAULT"):
            self.assertTrue(hasattr(HealthState, name))

    def test_priority_ordering(self):
        # lower value = higher priority (sent sooner)
        self.assertLess(CommandPriority.CRITICAL, CommandPriority.HIGH)
        self.assertLess(CommandPriority.HIGH, CommandPriority.NORMAL)
        self.assertLess(CommandPriority.NORMAL, CommandPriority.LOW)

if __name__ == "__main__":
    unittest.main()
