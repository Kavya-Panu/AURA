import threading
import unittest
from hardware.hardware_context import HardwareContext, HardwareSnapshot
from hardware.device_types import ConnectionState, HealthState

class TestHardwareContext(unittest.TestCase):
    def test_device_and_connection_state(self):
        ctx = HardwareContext()
        ctx.set_connected("esp32", True)
        ctx.set_connected("battery", True)
        ctx.set_connection_state(ConnectionState.CONNECTED)
        self.assertEqual(ctx.connected_devices, ("battery", "esp32"))
        self.assertEqual(ctx.snapshot().connection_state, "CONNECTED")

    def test_battery_and_face(self):
        ctx = HardwareContext()
        ctx.set_battery(75.0, True)
        ctx.set_face_emotion("HAPPY")
        snap = ctx.snapshot()
        self.assertEqual(snap.battery_percent, 75.0)
        self.assertTrue(snap.battery_charging)
        self.assertEqual(snap.face_emotion, "HAPPY")

    def test_servo_led_propeller_state(self):
        ctx = HardwareContext()
        ctx.set_servo("pan", 90.0)
        ctx.set_led({"color": "0,255,0", "brightness": 1.0})
        ctx.set_propeller(True, 80)
        snap = ctx.snapshot()
        self.assertEqual(snap.servo_positions["pan"], 90.0)
        self.assertEqual(snap.led_state["color"], "0,255,0")
        self.assertTrue(snap.propeller_running)
        self.assertEqual(snap.propeller_speed, 80)

    def test_command_and_stats(self):
        ctx = HardwareContext()
        ctx.record_command("esp32", "HAPPY")
        ctx.record_command("esp32", "BLINK:1")
        ctx.record_error()
        snap = ctx.snapshot()
        self.assertEqual(snap.last_command, ("esp32", "BLINK:1"))
        self.assertEqual(snap.stats["commands"], 2)
        self.assertEqual(snap.stats["errors"], 1)

    def test_health(self):
        ctx = HardwareContext()
        ctx.set_health(HealthState.HEALTHY)
        self.assertEqual(ctx.snapshot().health, "HEALTHY")

    def test_snapshot_is_immutable_copy(self):
        ctx = HardwareContext()
        ctx.set_servo("pan", 45.0)
        snap = ctx.snapshot()
        snap.servo_positions["pan"] = 999      # mutate the copy
        self.assertEqual(ctx.snapshot().servo_positions["pan"], 45.0)  # unaffected

    def test_thread_safe(self):
        ctx = HardwareContext()
        def worker(i):
            for j in range(200):
                ctx.record_command(f"d{i}", f"c{j}")
                ctx.set_servo(f"s{i}", float(j))
                ctx.snapshot()
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(ctx.snapshot().stats["commands"], 1200)

if __name__ == "__main__":
    unittest.main()
