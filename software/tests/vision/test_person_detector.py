"""PersonDetector: detection, tracking IDs, PERSON_FOUND/PERSON_LEFT."""
import unittest
from core.event_bus import EventBus
from core.constants import RobotEvent
from vision import Detector
from vision.frame_buffer import FrameBuffer
from vision.vision_config import VisionConfig, ProcessingConfig
from vision.person_detector import PersonDetector, FakePersonBackend, PersonBox
from vision.tests._vhelpers import collect, push_frame, wait_until

def build(script):
    bus = EventBus(); buf = FrameBuffer(max_frames=4)
    cfg = VisionConfig(); cfg.processing = ProcessingConfig(detect_every_n_frames=1)
    pd = PersonDetector(bus, buf, cfg, FakePersonBackend(script), min_confidence=0.4)
    return bus, buf, pd, collect(bus)

class TestPersonDetector(unittest.TestCase):
    def test_is_detector(self):
        bus, buf, pd, seen = build([[]])
        self.assertIsInstance(pd, Detector)

    def test_person_found_with_id(self):
        bus, buf, pd, seen = build([[PersonBox(100, 50, 120, 300, 0.9)]])
        pd.initialize(); pd.start()
        push_frame(buf, 0)
        self.assertTrue(wait_until(
            lambda: any(t == RobotEvent.PERSON_FOUND for t, _ in seen)))
        pd.stop()
        payload = next(d for t, d in seen if t == RobotEvent.PERSON_FOUND)
        self.assertEqual(payload["count"], 1)
        self.assertIn("id", payload["persons"][0])
        self.assertEqual(payload["persons"][0]["box"], [100, 50, 120, 300])

    def test_tracking_id_stable(self):
        # same person across two frames -> same id
        p = [PersonBox(100, 50, 120, 300, 0.9)]
        bus, buf, pd, seen = build([p, [PersonBox(105, 52, 120, 300, 0.9)]])
        pd.initialize(); pd.start()
        push_frame(buf, 0)
        self.assertTrue(wait_until(
            lambda: any(t == RobotEvent.PERSON_FOUND for t, _ in seen)))
        push_frame(buf, 1)
        wait_until(lambda: sum(1 for t, _ in seen if t == RobotEvent.PERSON_FOUND) >= 2)
        pd.stop()
        founds = [d for t, d in seen if t == RobotEvent.PERSON_FOUND]
        id1 = founds[0]["persons"][0]["id"]
        id2 = founds[-1]["persons"][0]["id"]
        self.assertEqual(id1, id2)

    def test_person_left(self):
        bus, buf, pd, seen = build([[PersonBox(100, 50, 120, 300, 0.9)], [], [], [], [], [], []])
        pd.initialize(); pd.start()
        push_frame(buf, 0)
        self.assertTrue(wait_until(
            lambda: any(t == RobotEvent.PERSON_FOUND for t, _ in seen)))
        for i in range(1, 8):   # enough empty frames to exceed max_misses
            push_frame(buf, i)
        self.assertTrue(wait_until(
            lambda: any(t == RobotEvent.PERSON_LEFT for t, _ in seen)))
        pd.stop()

    def test_health_check(self):
        bus, buf, pd, seen = build([[]])
        pd.initialize(); pd.start()
        self.assertTrue(pd.health_check())
        pd.stop()
        self.assertFalse(pd.health_check())

if __name__ == "__main__":
    unittest.main()
