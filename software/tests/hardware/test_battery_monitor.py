import unittest
from core.event_bus import EventBus
from core.constants import RobotEvent
from hardware.battery_monitor import BatteryMonitor, ChargeState

def collect(bus):
    seen = []
    bus.subscribe_all(lambda e: seen.append((e.type, e.data)))
    return seen

class TestBatteryMonitor(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()
        self.seen = collect(self.bus)
        self.bm = BatteryMonitor(self.bus, low_threshold=20, full_threshold=99)

    def types(self):
        return [t for t, _ in self.seen]

    def test_low_event(self):
        self.bm.update(percent=15, charging=False)
        self.assertIn(RobotEvent.BATTERY_LOW, self.types())

    def test_low_only_once(self):
        self.bm.update(percent=15, charging=False)
        self.bm.update(percent=12, charging=False)
        lows = [t for t in self.types() if t == RobotEvent.BATTERY_LOW]
        self.assertEqual(len(lows), 1)

    def test_charging_event(self):
        self.bm.update(percent=50, charging=True)
        self.assertIn(RobotEvent.BATTERY_CHARGING, self.types())

    def test_full_event(self):
        self.bm.update(percent=100, charging=True)
        self.assertIn(RobotEvent.BATTERY_FULL, self.types())

    def test_recovery_from_low_emits_ok(self):
        self.bm.update(percent=15, charging=False)   # LOW
        self.bm.update(percent=60, charging=False)   # recovered
        self.assertIn(RobotEvent.BATTERY_OK, self.types())

    def test_charge_state_derivation(self):
        self.bm.update(percent=50, charging=True)
        self.assertEqual(self.bm.status().charge_state, ChargeState.CHARGING.name)
        self.bm.update(percent=100, charging=True)
        self.assertEqual(self.bm.status().charge_state, ChargeState.FULL.name)
        self.bm.update(percent=80, charging=False)
        self.assertEqual(self.bm.status().charge_state, ChargeState.DISCHARGING.name)

    def test_voltage_health(self):
        self.bm.update(percent=90, voltage=3.9)
        self.assertEqual(self.bm.status().health, "GOOD")
        self.bm.update(percent=90, voltage=3.2)
        self.assertEqual(self.bm.status().health, "POOR")

    def test_percent_clamped(self):
        self.bm.update(percent=150)
        self.assertEqual(self.bm.percent, 100.0)

if __name__ == "__main__":
    unittest.main()
