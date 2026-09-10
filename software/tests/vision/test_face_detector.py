"""FaceDetector: detection, FACE_FOUND/FACE_LOST transitions, confidence, thread."""
import unittest
from core.event_bus import EventBus
from core.constants import RobotEvent
from vision import Detector
from vision.frame_buffer import FrameBuffer
from vision.vision_config import VisionConfig, ProcessingConfig
from vision.face_detector import FaceDetector, FakeFaceBackend, FaceBox
from vision.tests._vhelpers import collect, push_frame, wait_until

def build(script):
    bus = EventBus(); buf = FrameBuffer(max_frames=4)
    cfg = VisionConfig(); cfg.processing = ProcessingConfig(detect_every_n_frames=1)
    be = FakeFaceBackend(script)
    fd = FaceDetector(bus, buf, cfg, be, min_confidence=0.5)
    return bus, buf, fd, collect(bus)

class TestFaceDetector(unittest.TestCase):
    def test_is_detector(self):
        bus, buf, fd, seen = build([[]])
        self.assertIsInstance(fd, Detector)

    def test_face_found_published(self):
        bus, buf, fd, seen = build([[FaceBox(100, 80, 60, 60, 0.95)]])
        fd.initialize(); fd.start()
        push_frame(buf, 0)
        self.assertTrue(wait_until(
            lambda: any(t == RobotEvent.FACE_FOUND for t, _ in seen)))
        fd.stop()
        payload = next(d for t, d in seen if t == RobotEvent.FACE_FOUND)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["faces"][0]["box"], [100, 80, 60, 60])

    def test_multiple_faces(self):
        faces = [FaceBox(10, 10, 40, 40, 0.9), FaceBox(200, 50, 40, 40, 0.8)]
        bus, buf, fd, seen = build([faces])
        fd.initialize(); fd.start()
        push_frame(buf, 0)
        self.assertTrue(wait_until(
            lambda: any(t == RobotEvent.FACE_FOUND for t, _ in seen)))
        fd.stop()
        payload = next(d for t, d in seen if t == RobotEvent.FACE_FOUND)
        self.assertEqual(payload["count"], 2)

    def test_low_confidence_filtered(self):
        bus, buf, fd, seen = build([[FaceBox(0, 0, 10, 10, 0.2)]])  # below 0.5
        fd.initialize(); fd.start()
        push_frame(buf, 0)
        import time; time.sleep(0.05)
        fd.stop()
        self.assertFalse(any(t == RobotEvent.FACE_FOUND for t, _ in seen))

    def test_face_lost_transition(self):
        bus, buf, fd, seen = build([[FaceBox(10, 10, 40, 40, 0.9)], []])
        fd.initialize(); fd.start()
        push_frame(buf, 0)
        self.assertTrue(wait_until(
            lambda: any(t == RobotEvent.FACE_FOUND for t, _ in seen)))
        push_frame(buf, 1)   # now no faces
        self.assertTrue(wait_until(
            lambda: any(t == RobotEvent.FACE_LOST for t, _ in seen)))
        fd.stop()

    def test_health_check(self):
        bus, buf, fd, seen = build([[]])
        self.assertFalse(fd.health_check())
        fd.initialize(); fd.start()
        self.assertTrue(fd.health_check())
        fd.stop()
        self.assertFalse(fd.health_check())

    def test_dedicated_thread(self):
        import threading
        bus, buf, fd, seen = build([[]])
        fd.initialize(); fd.start()
        self.assertIn("vision-face", [t.name for t in threading.enumerate()])
        fd.stop()

if __name__ == "__main__":
    unittest.main()
