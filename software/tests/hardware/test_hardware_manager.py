"""HardwareManager: the single hardware boundary - devices, commands, face forwarding, health, threads."""
import threading
import time
import unittest
from core.constants import RobotEvent
from core.lifecycle import Module
from hardware import (HardwareManager, HardwareConfig, MockSerialTransport,
                      MockDevice, DeviceType, CommandPriority, HealthState)
from hardware.hardware_exceptions import DeviceNotFound, DeviceError
from hardware.tests._helpers import build_hal, collect, quiet_config, wait_until

class TestHardwareManager(unittest.TestCase):
    def test_is_module(self):
        bus, hal, t = build_hal(start=False)
        self.assertIsInstance(hal, Module)
        hal.stop()

    def test_start_registers_esp32_and_connects(self):
        bus, hal, t = build_hal(); seen = collect(bus)
        self.assertIn("esp32", hal.devices)
        self.assertTrue(wait_until(lambda: hal.serial_state.name == "CONNECTED"))
        hal.stop()

    def test_emotion_changed_forwarded_to_esp32(self):
        bus, hal, t = build_hal()
        wait_until(lambda: hal.serial_state.name == "CONNECTED")
        bus.emit(RobotEvent.EMOTION_CHANGED, {"emotion": "HAPPY"}, source="speech")
        self.assertTrue(wait_until(lambda: "HAPPY" in t.written))
        hal.stop()

    def test_mouth_command_suppressed_until_firmware_supports_it(self):
        bus, hal, t = build_hal()
        wait_until(lambda: hal.serial_state.name == "CONNECTED")
        before = list(t.written)
        bus.emit(RobotEvent.EMOTION_CHANGED, {"mouth": "MOUTH_WIDE"}, source="speech.mouth")
        time.sleep(0.05)
        self.assertEqual(t.written, before)
        hal.stop()

    def test_set_emotion_helper(self):
        bus, hal, t = build_hal()
        wait_until(lambda: hal.serial_state.name == "CONNECTED")
        hal.set_emotion("EXCITED")
        self.assertTrue(wait_until(lambda: "EXCITED" in t.written))
        hal.stop()

    def test_register_device_at_runtime(self):
        bus, hal, t = build_hal(); seen = collect(bus)
        hal.register_device(MockDevice("led", DeviceType.LED))
        self.assertIn("led", hal.devices)
        self.assertIn(RobotEvent.DEVICE_CONNECTED,
                      [ty for ty, _ in seen])       # connected on registration
        hal.stop()

    def test_send_command_to_device(self):
        bus, hal, t = build_hal()
        led = MockDevice("led", DeviceType.LED)
        hal.register_device(led)
        hal.send_command("led", "ON")
        self.assertIn("ON", led.commands)
        hal.stop()

    def test_send_to_unknown_device_raises(self):
        bus, hal, t = build_hal()
        with self.assertRaises(DeviceNotFound):
            hal.send_command("ghost", "ON")
        hal.stop()

    def test_discover_devices(self):
        bus, hal, t = build_hal()
        hal.register_device(MockDevice("battery", DeviceType.BATTERY))
        info = hal.discover_devices()
        self.assertIn("esp32", info)
        self.assertIn("battery", info)
        self.assertEqual(info["battery"]["type"], "battery")
        hal.stop()

    def test_battery_low_event(self):
        bus, hal, t = build_hal(); seen = collect(bus)
        hal._update_battery(10.0)
        low = [d for ty, d in seen if ty == RobotEvent.BATTERY_LOW]
        self.assertTrue(low)
        self.assertEqual(low[0]["percent"], 10.0)
        hal.stop()

    def test_battery_low_only_warns_once(self):
        bus, hal, t = build_hal(); seen = collect(bus)
        hal._update_battery(10.0)
        hal._update_battery(9.0)                     # still low, no repeat
        low = [d for ty, d in seen if ty == RobotEvent.BATTERY_LOW]
        self.assertEqual(len(low), 1)
        hal._update_battery(50.0)                    # recovers
        hal._update_battery(5.0)                     # low again -> new warning
        low = [d for ty, d in seen if ty == RobotEvent.BATTERY_LOW]
        self.assertEqual(len(low), 2)
        hal.stop()

    def test_battery_telemetry_from_serial_line(self):
        bus, hal, t = build_hal(); seen = collect(bus)
        hal._on_serial_line("BATTERY:12")
        self.assertTrue(any(ty == RobotEvent.BATTERY_LOW for ty, _ in seen))
        hal.stop()

    def test_health_check_reports_fault(self):
        bus, hal, t = build_hal()
        bad = MockDevice("servo", DeviceType.SERVO)
        hal.register_device(bad)
        bad.set_health(HealthState.FAULT)
        self.assertFalse(hal.health_check())
        hal.stop()

    def test_heartbeat_thread_pings(self):
        cfg = quiet_config(); cfg.health.enabled = True; cfg.health.interval_s = 0.05
        bus, hal, t = build_hal(config=cfg)
        wait_until(lambda: hal.serial_state.name == "CONNECTED")
        self.assertTrue(wait_until(lambda: any("PING" in w for w in t.written),
                                   timeout_s=2.0))
        hal.stop()

    def test_hardware_started_stopped_events(self):
        bus, hal, t = build_hal(start=False); seen = collect(bus)
        hal.start()
        hal.stop()
        types = [ty for ty, _ in seen]
        self.assertIn(RobotEvent.HARDWARE_STARTED, types)
        self.assertIn(RobotEvent.HARDWARE_STOPPED, types)

    def test_only_hal_touches_serialport(self):
        # sanity: no other AURA package imports pyserial/serial except the HAL
        import ast, os
        root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        offenders = []
        for pkg in ("brain", "speech", "vision", "voice", "behavior", "mode",
                    "intent", "memory", "core"):
            pdir = os.path.join(root, pkg)
            if not os.path.isdir(pdir):
                continue
            for dirpath, _, files in os.walk(pdir):
                for f in files:
                    if not f.endswith(".py"):
                        continue
                    src = open(os.path.join(dirpath, f), encoding="utf-8").read()
                    for n in ast.walk(ast.parse(src)):
                        if isinstance(n, ast.Import):
                            for a in n.names:
                                if a.name == "serial" or a.name.startswith("serial."):
                                    offenders.append(os.path.join(pkg, f))
                        elif isinstance(n, ast.ImportFrom) and n.module and \
                                n.module.split(".")[0] == "serial":
                            offenders.append(os.path.join(pkg, f))
        self.assertEqual(offenders, [], f"non-HAL modules import serial: {offenders}")

    def test_thread_safety_concurrent_commands(self):
        bus, hal, t = build_hal()
        led = MockDevice("led", DeviceType.LED)
        hal.register_device(led)
        def worker(i):
            for j in range(20):
                hal.send_command("led", f"CMD{i}-{j}")
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
        for t_ in threads: t_.start()
        for t_ in threads: t_.join()
        self.assertEqual(len(led.commands), 120)
        hal.stop()

if __name__ == "__main__":
    unittest.main()
