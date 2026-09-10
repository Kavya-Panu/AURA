import threading
import unittest
from hardware.device_registry import (
    DeviceRegistry, MockDevice, SerialDevice, Device)
from hardware.device_types import DeviceType, HealthState, CommandPriority
from hardware.hardware_exceptions import DeviceError, DeviceNotFound

class TestRegistry(unittest.TestCase):
    def test_register_and_get(self):
        reg = DeviceRegistry()
        reg.register(MockDevice("battery", DeviceType.BATTERY))
        self.assertIsInstance(reg.get("battery"), Device)

    def test_duplicate_rejected(self):
        reg = DeviceRegistry()
        reg.register(MockDevice("led", DeviceType.LED))
        with self.assertRaises(DeviceError):
            reg.register(MockDevice("led", DeviceType.LED))

    def test_non_device_rejected(self):
        with self.assertRaises(DeviceError):
            DeviceRegistry().register(object())

    def test_get_missing_raises(self):
        with self.assertRaises(DeviceNotFound):
            DeviceRegistry().get("nope")

    def test_by_type(self):
        reg = DeviceRegistry()
        reg.register(MockDevice("s1", DeviceType.SERVO))
        reg.register(MockDevice("s2", DeviceType.SERVO))
        reg.register(MockDevice("led", DeviceType.LED))
        self.assertEqual(len(reg.by_type(DeviceType.SERVO)), 2)

    def test_unregister(self):
        reg = DeviceRegistry()
        reg.register(MockDevice("cam", DeviceType.CAMERA))
        self.assertTrue(reg.unregister("cam"))
        self.assertFalse(reg.unregister("cam"))

    def test_mock_device_records_commands(self):
        d = MockDevice("led", DeviceType.LED)
        d.connect()
        d.send_command("ON")
        self.assertEqual(d.commands, ["ON"])

    def test_mock_device_command_when_disconnected_raises(self):
        d = MockDevice("led", DeviceType.LED)
        with self.assertRaises(DeviceError):
            d.send_command("ON")

    def test_serial_device_uses_injected_send(self):
        sent = []
        link_up = True
        dev = SerialDevice("esp32", DeviceType.ESP32,
                           send=lambda c, p: (sent.append((c, p)) or True),
                           is_link_up=lambda: link_up)
        dev.connect()
        dev.send_command("HAPPY", CommandPriority.HIGH)
        self.assertEqual(sent[0][0], "HAPPY")

    def test_serial_device_fails_when_link_down(self):
        dev = SerialDevice("esp32", DeviceType.ESP32,
                           send=lambda c, p: True, is_link_up=lambda: False)
        dev.connect()
        with self.assertRaises(DeviceError):
            dev.send_command("HAPPY")

    def test_thread_safe_registration(self):
        reg = DeviceRegistry()
        def worker(i):
            for j in range(50):
                reg.register(MockDevice(f"d{i}-{j}", DeviceType.LED))
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(len(reg.all()), 300)

if __name__ == "__main__":
    unittest.main()
