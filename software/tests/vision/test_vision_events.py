"""VisionEvent <-> RobotEvent mapping and alias correctness."""
import unittest
from core.constants import RobotEvent
from vision.vision_events import VisionEvent, robot_event

class TestVisionEvents(unittest.TestCase):
    def test_lifecycle_mapping(self):
        self.assertIs(robot_event(VisionEvent.VISION_STARTED),
                      RobotEvent.VISION_STARTED)
        self.assertIs(robot_event(VisionEvent.CAMERA_CONNECTED),
                      RobotEvent.CAMERA_CONNECTED)

    def test_spec_aliases_map_to_core(self):
        # PHONE_REMOVED is the spec name; core uses PHONE_GONE
        self.assertIs(robot_event(VisionEvent.PHONE_REMOVED),
                      RobotEvent.PHONE_GONE)
        # PERSON_FOUND spec name -> core PERSON_RETURNED
        self.assertIs(robot_event(VisionEvent.PERSON_FOUND),
                      RobotEvent.PERSON_RETURNED)

    def test_all_events_resolve_to_robot_events(self):
        for ev in VisionEvent:
            self.assertIsInstance(robot_event(ev), RobotEvent)

    def test_required_events_present(self):
        for name in ("VISION_STARTED", "VISION_STOPPED", "CAMERA_CONNECTED",
                     "CAMERA_DISCONNECTED", "FACE_FOUND", "FACE_LOST",
                     "PHONE_DETECTED", "PHONE_REMOVED", "PERSON_FOUND",
                     "PERSON_LEFT", "VISION_ERROR"):
            self.assertTrue(hasattr(VisionEvent, name), name)

if __name__ == "__main__":
    unittest.main()
