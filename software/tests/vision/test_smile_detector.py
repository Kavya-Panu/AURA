import unittest
from core.event_bus import EventBus
from core.constants import RobotEvent
from vision import Detector
from vision.frame_buffer import FrameBuffer
from vision.vision_config import VisionConfig, ProcessingConfig
from vision.smile_detector import SmileDetector, FakeFaceMeshBackend, FaceMesh, smile_ratio
from vision.tests._vhelpers import collect, push_frame, wait_until
from vision.tests._landmarks import face_mesh_smiling, face_mesh_neutral

def FM(pts): return FaceMesh(tuple(pts))

def build(script):
    bus = EventBus(); buf = FrameBuffer(max_frames=8)
    cfg = VisionConfig(); cfg.processing = ProcessingConfig(detect_every_n_frames=1)
    sd = SmileDetector(bus, buf, cfg, FakeFaceMeshBackend(script), smile_threshold=0.5)
    return bus, buf, sd, collect(bus)

class TestSmile(unittest.TestCase):
    def test_is_detector(self):
        bus, buf, sd, seen = build([[]])
        self.assertIsInstance(sd, Detector)

    def test_ratio_smiling_gt_neutral(self):
        self.assertGreater(smile_ratio(FM(face_mesh_smiling())),
                           smile_ratio(FM(face_mesh_neutral())))

    def test_user_smiling(self):
        bus, buf, sd, seen = build([[FM(face_mesh_smiling())]])
        sd.initialize(); sd.start(); push_frame(buf, 0)
        self.assertTrue(wait_until(
            lambda: any(t == RobotEvent.USER_SMILING for t, _ in seen)))
        sd.stop()

    def test_smiling_then_not(self):
        bus, buf, sd, seen = build([[FM(face_mesh_smiling())],
                                    [FM(face_mesh_neutral())]])
        sd.initialize(); sd.start(); push_frame(buf, 0)
        self.assertTrue(wait_until(
            lambda: any(t == RobotEvent.USER_SMILING for t, _ in seen)))
        push_frame(buf, 1)
        self.assertTrue(wait_until(
            lambda: any(t == RobotEvent.USER_NOT_SMILING for t, _ in seen)))
        sd.stop()

    def test_health(self):
        bus, buf, sd, seen = build([[]])
        sd.initialize(); sd.start()
        self.assertTrue(sd.health_check()); sd.stop()
        self.assertFalse(sd.health_check())

if __name__ == "__main__":
    unittest.main()
