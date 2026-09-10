import unittest
from core.event_bus import EventBus
from core.constants import RobotEvent
from vision import Detector
from vision.frame_buffer import FrameBuffer
from vision.vision_config import VisionConfig, ProcessingConfig
from vision.head_pose import (
    HeadPoseDetector, FakeFaceMeshBackend, FaceMesh, HeadDirection,
    estimate_orientation)
from vision.tests._vhelpers import collect, push_frame, wait_until
from vision.tests._landmarks import face_mesh_head

def FM(pts): return FaceMesh(tuple(pts))

def build(script):
    bus = EventBus(); buf = FrameBuffer(max_frames=8)
    cfg = VisionConfig(); cfg.processing = ProcessingConfig(detect_every_n_frames=1)
    hp = HeadPoseDetector(bus, buf, cfg, FakeFaceMeshBackend(script))
    return bus, buf, hp, collect(bus)

class TestHeadPose(unittest.TestCase):
    def test_is_detector(self):
        bus, buf, hp, seen = build([[]])
        self.assertIsInstance(hp, Detector)

    def test_orientation_center(self):
        o = estimate_orientation(FM(face_mesh_head(0.5, 0.5)))
        self.assertEqual(o.direction, HeadDirection.CENTER)
        self.assertAlmostEqual(o.yaw, 0.0, delta=0.05)

    def test_orientation_left_right(self):
        left = estimate_orientation(FM(face_mesh_head(nose_x=0.34)))
        right = estimate_orientation(FM(face_mesh_head(nose_x=0.66)))
        self.assertEqual(left.direction, HeadDirection.LEFT)
        self.assertEqual(right.direction, HeadDirection.RIGHT)

    def test_orientation_up_down(self):
        up = estimate_orientation(FM(face_mesh_head(nose_y=0.34)))
        down = estimate_orientation(FM(face_mesh_head(nose_y=0.66)))
        self.assertEqual(up.direction, HeadDirection.UP)
        self.assertEqual(down.direction, HeadDirection.DOWN)

    def test_publishes_head_events(self):
        bus, buf, hp, seen = build([[FM(face_mesh_head(nose_x=0.7))]])
        hp.initialize(); hp.start(); push_frame(buf, 0)
        self.assertTrue(wait_until(
            lambda: any(t == RobotEvent.HEAD_RIGHT for t, _ in seen)))
        hp.stop()

    def test_health(self):
        bus, buf, hp, seen = build([[]])
        hp.initialize(); hp.start()
        self.assertTrue(hp.health_check()); hp.stop()
        self.assertFalse(hp.health_check())

if __name__ == "__main__":
    unittest.main()
