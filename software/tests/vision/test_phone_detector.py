"""PhoneDetector: PHONE_DETECTED/REMOVED, duration tracking, grace period."""
import unittest
from core.event_bus import EventBus
from core.constants import RobotEvent
from vision import Detector
from vision.frame_buffer import FrameBuffer
from vision.vision_config import VisionConfig, ProcessingConfig
from vision.phone_detector import PhoneDetector, FakePhoneBackend, PhoneBox
from vision.tests._vhelpers import collect, push_frame, wait_until

class FakeClock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t
    def advance(self, dt): self.t += dt

def build(script, clock=None, grace=0.6, update=1.0):
    bus = EventBus(); buf = FrameBuffer(max_frames=8)
    cfg = VisionConfig(); cfg.processing = ProcessingConfig(detect_every_n_frames=1)
    ph = PhoneDetector(bus, buf, cfg, FakePhoneBackend(script),
                       min_confidence=0.4, duration_update_interval_s=update,
                       disappear_grace_s=grace, clock=clock or (lambda: 0.0))
    return bus, buf, ph, collect(bus)

class TestPhoneDetector(unittest.TestCase):
    def test_is_detector(self):
        bus, buf, ph, seen = build([[]])
        self.assertIsInstance(ph, Detector)

    def test_phone_detected(self):
        clk = FakeClock()
        bus, buf, ph, seen = build([[PhoneBox(200, 200, 80, 160, 0.9)]], clock=clk)
        ph.initialize(); ph.start()
        push_frame(buf, 0)
        self.assertTrue(wait_until(
            lambda: any(t == RobotEvent.PHONE_DETECTED for t, _ in seen)))
        ph.stop()
        payload = next(d for t, d in seen if t == RobotEvent.PHONE_DETECTED)
        self.assertEqual(payload["box"], [200, 200, 80, 160])
        self.assertTrue(ph.is_phone_visible)

    def test_duration_updates_while_visible(self):
        clk = FakeClock()
        # phone present in every frame
        bus, buf, ph, seen = build([[PhoneBox(200, 200, 80, 160, 0.9)]],
                                   clock=clk, update=1.0)
        ph.initialize(); ph.start()
        push_frame(buf, 0)
        self.assertTrue(wait_until(
            lambda: any(t == RobotEvent.PHONE_DETECTED for t, _ in seen)))
        clk.advance(1.5)                 # exceed update interval
        push_frame(buf, 1)
        self.assertTrue(wait_until(
            lambda: any(t == RobotEvent.PHONE_DURATION_UPDATED for t, _ in seen)))
        ph.stop()
        upd = next(d for t, d in seen if t == RobotEvent.PHONE_DURATION_UPDATED)
        self.assertGreaterEqual(upd["duration_s"], 1.0)

    def test_phone_removed_after_grace(self):
        clk = FakeClock()
        bus, buf, ph, seen = build(
            [[PhoneBox(200, 200, 80, 160, 0.9)], []], clock=clk, grace=0.5)
        ph.initialize(); ph.start()
        push_frame(buf, 0)
        self.assertTrue(wait_until(
            lambda: any(t == RobotEvent.PHONE_DETECTED for t, _ in seen)))
        clk.advance(1.0)                 # exceed grace
        push_frame(buf, 1)               # phone gone this frame
        self.assertTrue(wait_until(
            lambda: any(t == RobotEvent.PHONE_GONE for t, _ in seen)))
        ph.stop()
        self.assertFalse(ph.is_phone_visible)

    def test_no_removed_within_grace(self):
        clk = FakeClock()
        bus, buf, ph, seen = build(
            [[PhoneBox(200, 200, 80, 160, 0.9)], []], clock=clk, grace=5.0)
        ph.initialize(); ph.start()
        push_frame(buf, 0)
        self.assertTrue(wait_until(
            lambda: any(t == RobotEvent.PHONE_DETECTED for t, _ in seen)))
        clk.advance(0.1)                 # within grace
        push_frame(buf, 1)
        import time; time.sleep(0.05)
        ph.stop()
        self.assertFalse(any(t == RobotEvent.PHONE_GONE for t, _ in seen))

    def test_health_check(self):
        bus, buf, ph, seen = build([[]])
        ph.initialize(); ph.start()
        self.assertTrue(ph.health_check())
        ph.stop()
        self.assertFalse(ph.health_check())

if __name__ == "__main__":
    unittest.main()
