"""Stage 2 drivers route through the REAL Stage 1 HardwareManager to the ESP32."""
import time
import unittest
from core.event_bus import EventBus
from core.constants import RobotEvent
from core.lifecycle import LifecycleManager
from core.state_machine import build_aura_state_machine
from hardware import (HardwareManager, HardwareConfig, MockSerialTransport,
                      FaceDriver, ServoDriver, LedDriver, PropellerDriver,
                      CommandRouter, HardwareCommand, Color)

def quiet_cfg():
    cfg = HardwareConfig(); cfg.health.enabled = False
    cfg.serial.reconnect_delay_s = 0.02
    return cfg

def wait_until(pred, t=2.0):
    end = time.monotonic() + t
    while time.monotonic() < end:
        if pred(): return True
        time.sleep(0.004)
    return pred()

class TestStage2Integration(unittest.TestCase):
    def _hal(self, bus, transport):
        hal = HardwareManager(bus, quiet_cfg(), transport)
        hal.initialize(); hal.start()
        wait_until(lambda: hal.serial_state.name == "CONNECTED")
        return hal

    def test_all_drivers_route_through_manager(self):
        bus = EventBus()
        transport = MockSerialTransport(ports=["MOCK-ESP32"])
        hal = self._hal(bus, transport)
        FaceDriver(hal.send_command).set_emotion("HAPPY")
        ServoDriver(hal.send_command, "pan").move_to(90)
        LedDriver(hal.send_command).set_color(Color(0, 255, 0))
        p = PropellerDriver(hal.send_command, safety_timeout_s=5)
        p.start(50); p.stop()
        self.assertTrue(wait_until(lambda: "HAPPY" in transport.written))
        self.assertTrue(wait_until(
            lambda: any("SERVO:pan:90" in w for w in transport.written)))
        self.assertTrue(wait_until(
            lambda: any("LED:led:0,255,0" in w for w in transport.written)))
        hal.stop()

    def test_router_dispatches_to_driver_via_manager(self):
        bus = EventBus()
        transport = MockSerialTransport(ports=["MOCK-ESP32"])
        hal = self._hal(bus, transport)
        face = FaceDriver(hal.send_command)
        router = CommandRouter(); router.start()
        router.submit(HardwareCommand("face", lambda: face.set_emotion("EXCITED")))
        self.assertTrue(wait_until(lambda: "EXCITED" in transport.written))
        router.stop(); hal.stop()

    def test_runs_under_lifecycle(self):
        bus = EventBus()
        sm = build_aura_state_machine(bus)
        life = LifecycleManager(bus, sm)
        transport = MockSerialTransport(ports=["MOCK-ESP32"])
        hal = HardwareManager(bus, quiet_cfg(), transport)
        life.register(hal)
        life.startup()
        wait_until(lambda: hal.serial_state.name == "CONNECTED")
        FaceDriver(hal.send_command).set_emotion("LOVE")
        self.assertTrue(wait_until(lambda: "LOVE" in transport.written))
        life.shutdown()

if __name__ == "__main__":
    unittest.main()
