import unittest
from core.event_bus import EventBus
from core.constants import RobotEvent
from vision import Detector
from vision.frame_buffer import FrameBuffer
from vision.vision_config import VisionConfig, ProcessingConfig
from vision.eye_contact import (
    EyeContactDetector, FakeFaceMeshBackend, FaceMesh, gaze_centered)
from vision.tests._vhelpers import collect, push_frame, wait_until
from vision.tests._landmarks import face_mesh_gaze

def FM(pts): return FaceMesh(tuple(pts))

class FakeClock:
    def __init__(self): self.t = 500.0
    def __call__(self): return self.t
    def advance(self, dt): self.t += dt

def build(script, clock=None):
    bus = EventBus(); buf = FrameBuffer(max_frames=8)
    cfg = VisionConfig(); cfg.processing = ProcessingConfig(detect_every_n_frames=1)
    ec = EyeContactDetector(bus, buf, cfg, FakeFaceMeshBackend(script),
                            clock=clock or (lambda: 0.0))
    return bus, buf, ec, collect(bus)

class TestEyeContact(unittest.TestCase):
    def test_is_detector(self):
        bus, buf, ec, seen = build([[]])
        self.assertIsInstance(ec, Detector)

    def test_gaze_centered_helper(self):
        self.assertTrue(gaze_centered(FM(face_mesh_gaze(centered=True))))
        self.assertFalse(gaze_centered(FM(face_mesh_gaze(centered=False))))

    def test_looking_at_robot(self):
        bus, buf, ec, seen = build([[FM(face_mesh_gaze(True))]])
        ec.initialize(); ec.start(); push_frame(buf, 0)
        self.assertTrue(wait_until(
            lambda: any(t == RobotEvent.LOOKING_AT_ROBOT for t, _ in seen)))
        ec.stop()

    def test_transition_with_duration(self):
        clk = FakeClock()
        bus, buf, ec, seen = build([[FM(face_mesh_gaze(True))],
                                    [FM(face_mesh_gaze(False))]], clock=clk)
        ec.initialize(); ec.start(); push_frame(buf, 0)
        self.assertTrue(wait_until(
            lambda: any(t == RobotEvent.LOOKING_AT_ROBOT for t, _ in seen)))
        clk.advance(3.0)
        push_frame(buf, 1)
        self.assertTrue(wait_until(
            lambda: any(t == RobotEvent.LOOKING_AWAY for t, _ in seen)))
        ec.stop()
        away = next(d for t, d in seen if t == RobotEvent.LOOKING_AWAY)
        self.assertGreaterEqual(away["duration_s"], 3.0)

    def test_health(self):
        bus, buf, ec, seen = build([[]])
        ec.initialize(); ec.start()
        self.assertTrue(ec.health_check()); ec.stop()
        self.assertFalse(ec.health_check())

if __name__ == "__main__":
    unittest.main()
