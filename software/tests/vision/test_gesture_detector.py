import unittest
from core.event_bus import EventBus
from core.constants import RobotEvent
from vision import Detector
from vision.frame_buffer import FrameBuffer
from vision.vision_config import VisionConfig, ProcessingConfig
from vision.gesture_detector import (
    GestureDetector, FakeGestureBackend, HandLandmarks)
from vision.tests._vhelpers import collect, push_frame, wait_until
from vision.tests._landmarks import hand_thumbs_up, hand_raised, hand_at

def H(pts, handed="Right"):
    return HandLandmarks(tuple(pts), handed)

def build(script, **kw):
    bus = EventBus(); buf = FrameBuffer(max_frames=8)
    cfg = VisionConfig(); cfg.processing = ProcessingConfig(detect_every_n_frames=1)
    gd = GestureDetector(bus, buf, cfg, FakeGestureBackend(script), **kw)
    return bus, buf, gd, collect(bus)

class TestGesture(unittest.TestCase):
    def test_is_detector(self):
        bus, buf, gd, seen = build([[]])
        self.assertIsInstance(gd, Detector)

    def test_thumbs_up(self):
        bus, buf, gd, seen = build([[H(hand_thumbs_up())]])
        gd.initialize(); gd.start(); push_frame(buf, 0)
        self.assertTrue(wait_until(
            lambda: any(t == RobotEvent.THUMBS_UP for t, _ in seen)))
        gd.stop()

    def test_raised_hand(self):
        bus, buf, gd, seen = build([[H(hand_raised())]])
        gd.initialize(); gd.start(); push_frame(buf, 0)
        self.assertTrue(wait_until(
            lambda: any(t == RobotEvent.HAND_RAISED for t, _ in seen)))
        gd.stop()

    def test_wave_from_oscillation(self):
        # Wave needs to SEE each frame; the latest-only FrameBuffer skips frames
        # if pushed faster than consumed, so pace delivery to one-per-consume.
        from vision.gesture_detector import FakeGestureBackend
        xs = [0.3, 0.6, 0.3, 0.6, 0.3, 0.6]
        be = FakeGestureBackend([[H(hand_at(x))] for x in xs])
        bus = EventBus(); buf = FrameBuffer(max_frames=8)
        cfg = VisionConfig(); cfg.processing = ProcessingConfig(detect_every_n_frames=1)
        gd = GestureDetector(bus, buf, cfg, be, wave_min_swings=3)
        seen = collect(bus)
        gd.initialize(); gd.start()
        for i in range(len(xs)):
            push_frame(buf, i)
            wait_until(lambda i=i: be._i >= i + 1)   # frame i consumed before next
        self.assertTrue(wait_until(
            lambda: any(t == RobotEvent.HAND_WAVE for t, _ in seen)))
        gd.stop()

    def test_no_hand_no_event(self):
        bus, buf, gd, seen = build([[]])
        gd.initialize(); gd.start(); push_frame(buf, 0)
        import time; time.sleep(0.05); gd.stop()
        gestures = {RobotEvent.THUMBS_UP, RobotEvent.HAND_RAISED, RobotEvent.HAND_WAVE}
        self.assertFalse(any(t in gestures for t, _ in seen))

    def test_never_executes_actions(self):
        # gesture module must not import behavior/mode/emotion managers
        import ast, vision.gesture_detector as m
        tree = ast.parse(open(m.__file__).read())
        mods = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module:
                mods.add(n.module)
        self.assertFalse(any("behavior" in x or "mode" in x or "emotion" in x
                             for x in mods))

    def test_health(self):
        bus, buf, gd, seen = build([[]])
        gd.initialize(); gd.start()
        self.assertTrue(gd.health_check()); gd.stop()
        self.assertFalse(gd.health_check())

if __name__ == "__main__":
    unittest.main()
