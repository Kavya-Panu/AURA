import unittest
from core.event_bus import EventBus
from core.constants import RobotEvent
from vision import Detector
from vision.fatigue_detector import FatigueDetector, FatigueConfig
from vision.tests._vhelpers import collect

class FakeClock:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t
    def advance(self, dt): self.t += dt

class TestFatigue(unittest.TestCase):
    def test_is_detector(self):
        self.assertIsInstance(FatigueDetector(EventBus()), Detector)

    def test_repeated_look_away_tires(self):
        bus = EventBus(); seen = collect(bus)
        clk = FakeClock()
        fd = FatigueDetector(bus, FatigueConfig(look_away_events_for_tired=4,
                                                window_s=60, cooldown_s=30), clk)
        fd.start()
        for _ in range(4):
            bus.emit(RobotEvent.LOOKING_AWAY, {"duration_s": 0.5}, source="eye")
            clk.advance(1.0)
        self.assertTrue(any(t == RobotEvent.USER_TIRED for t, _ in seen))
        fd.stop()

    def test_single_long_look_away_tires(self):
        bus = EventBus(); seen = collect(bus)
        fd = FatigueDetector(bus, FatigueConfig(long_look_away_s=6.0), FakeClock())
        fd.start()
        bus.emit(RobotEvent.LOOKING_AWAY, {"duration_s": 8.0}, source="eye")
        self.assertTrue(any(t == RobotEvent.USER_TIRED for t, _ in seen))
        fd.stop()

    def test_head_down_repeated_tires(self):
        bus = EventBus(); seen = collect(bus)
        clk = FakeClock()
        fd = FatigueDetector(bus, FatigueConfig(head_down_events_for_tired=3), clk)
        fd.start()
        for _ in range(3):
            bus.emit(RobotEvent.HEAD_DOWN, {}, source="head"); clk.advance(1.0)
        self.assertTrue(any(t == RobotEvent.USER_TIRED for t, _ in seen))
        fd.stop()

    def test_looking_back_resets_streak(self):
        bus = EventBus(); seen = collect(bus)
        clk = FakeClock()
        fd = FatigueDetector(bus, FatigueConfig(look_away_events_for_tired=4), clk)
        fd.start()
        for _ in range(3):
            bus.emit(RobotEvent.LOOKING_AWAY, {"duration_s": 0.5}, source="eye")
            clk.advance(1.0)
        bus.emit(RobotEvent.LOOKING_AT_ROBOT, {"duration_s": 1.0}, source="eye")
        bus.emit(RobotEvent.LOOKING_AWAY, {"duration_s": 0.5}, source="eye")
        self.assertFalse(any(t == RobotEvent.USER_TIRED for t, _ in seen))
        fd.stop()

    def test_cooldown_prevents_spam(self):
        bus = EventBus(); seen = collect(bus)
        clk = FakeClock()
        fd = FatigueDetector(bus, FatigueConfig(long_look_away_s=1.0,
                                                cooldown_s=30), clk)
        fd.start()
        bus.emit(RobotEvent.LOOKING_AWAY, {"duration_s": 5.0}, source="eye")
        clk.advance(2.0)
        bus.emit(RobotEvent.LOOKING_AWAY, {"duration_s": 5.0}, source="eye")
        tired = [1 for t, _ in seen if t == RobotEvent.USER_TIRED]
        self.assertEqual(len(tired), 1)   # only once within cooldown
        fd.stop()

    def test_not_a_diagnosis_note(self):
        bus = EventBus(); seen = collect(bus)
        fd = FatigueDetector(bus, FatigueConfig(long_look_away_s=1.0), FakeClock())
        fd.start()
        bus.emit(RobotEvent.LOOKING_AWAY, {"duration_s": 5.0}, source="eye")
        payload = next(d for t, d in seen if t == RobotEvent.USER_TIRED)
        self.assertIn("not a medical diagnosis", payload["note"])
        fd.stop()

if __name__ == "__main__":
    unittest.main()
