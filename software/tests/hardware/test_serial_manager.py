import unittest
import time
from core.event_bus import EventBus
from core.constants import RobotEvent
from hardware.serial_manager import SerialManager, MockSerialTransport, PySerialTransport, SerialTransport
from hardware.hardware_config import SerialConfig
from hardware.device_types import ConnectionState, CommandPriority


def wait_until(predicate, timeout_s=1.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


def collect(bus):
    seen = []
    bus.subscribe_all(lambda event: seen.append((event.type, event)))
    return seen

def build_serial(transport=None, on_line=None, cfg=None):
    bus = EventBus()
    transport = transport or MockSerialTransport(ports=["MOCK-ESP32"])
    sm = SerialManager(bus, cfg or SerialConfig(reconnect_delay_s=0.02),
                       transport, on_line=on_line)
    return bus, sm, transport

class TestSerialManager(unittest.TestCase):
    def test_transports_satisfy_interface(self):
        self.assertIsInstance(MockSerialTransport(), SerialTransport)
        self.assertIsInstance(PySerialTransport(), SerialTransport)

    def test_connects_and_emits(self):
        bus, sm, t = build_serial(); seen = collect(bus)
        sm.start()
        self.assertTrue(wait_until(lambda: sm.connected))
        self.assertIn(RobotEvent.SERIAL_CONNECTED, [ty for ty, _ in seen])
        sm.stop()

    def test_auto_detect_port_by_hint(self):
        t = MockSerialTransport(ports=["/dev/ttyRANDOM", "/dev/ttyUSB0"])
        bus, sm, _ = build_serial(transport=t)
        sm.start()
        self.assertTrue(wait_until(lambda: sm.connected))
        # picked the USB-hinted port
        self.assertTrue(any("USB" in p for p in [sm._port]))
        sm.stop()

    def test_send_writes_to_transport(self):
        bus, sm, t = build_serial()
        sm.start(); wait_until(lambda: sm.connected)
        sm.send("HAPPY")
        self.assertTrue(wait_until(lambda: "HAPPY" in t.written))
        sm.stop()

    def test_exclusive_audio_session_pauses_only_queued_writes(self):
        bus, sm, t = build_serial()
        sm.start(); wait_until(lambda: sm.connected)
        sm.pause_queued_writes()
        sm.send("GAZE 0.5 0.0", CommandPriority.LOW)
        self.assertTrue(sm.send_immediate("MIC START"))
        self.assertTrue(wait_until(lambda: "MIC START" in t.written))
        self.assertNotIn("GAZE 0.5 0.0", t.written)
        sm.resume_queued_writes()
        self.assertTrue(wait_until(lambda: "GAZE 0.5 0.0" in t.written))
        sm.stop()

    def test_priority_ordering(self):
        # a fresh, not-yet-started manager: enqueue then check heap order
        bus, sm, t = build_serial()
        sm.send("low", CommandPriority.LOW)
        sm.send("critical", CommandPriority.CRITICAL)
        # peek the heap: critical must come first
        first = min(sm._heap)
        self.assertEqual(first.line, "critical")

    def test_queue_full_returns_false(self):
        bus, sm, t = build_serial()
        sm._queue_max = 2
        self.assertTrue(sm.send("a"))
        self.assertTrue(sm.send("b"))
        self.assertFalse(sm.send("c"))

    def test_receive_invokes_on_line(self):
        got = []
        t = MockSerialTransport(responder=lambda line: ["BATTERY:15"])
        bus, sm, _ = build_serial(transport=t, on_line=got.append)
        sm.start(); wait_until(lambda: sm.connected)
        sm.send("PING")
        self.assertTrue(wait_until(lambda: "BATTERY:15" in got))
        sm.stop()

    def test_reconnect_after_disconnect(self):
        bus, sm, t = build_serial(); seen = collect(bus)
        sm.start(); wait_until(lambda: sm.connected)
        t.simulate_disconnect()                    # link drops
        sm.send("trigger")                          # write fails -> reconnect
        # wait for the disconnect to be observed (sm.connected flips back fast on
        # reconnect, so wait on the event, not the flag)
        self.assertTrue(wait_until(
            lambda: RobotEvent.SERIAL_DISCONNECTED in [ty for ty, _ in seen],
            timeout_s=2.0))
        self.assertTrue(wait_until(lambda: sm.connected, timeout_s=2.0))  # recovered
        sm.stop()

    def test_connect_failure_sets_error(self):
        t = MockSerialTransport(ports=[])           # no ports -> cannot connect
        bus, sm, _ = build_serial(transport=t)
        sm.start()
        self.assertEqual(sm.state, ConnectionState.ERROR)
        sm.stop()

if __name__ == "__main__":
    unittest.main()
