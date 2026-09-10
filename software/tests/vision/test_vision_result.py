"""VisionResult / Detection / BoundingBox generic dataclass."""
import unittest
from vision.vision_result import (
    BoundingBox, Detection, DetectionKind, VisionResult)

class TestVisionResult(unittest.TestCase):
    def test_bounding_box_geometry(self):
        b = BoundingBox(10, 20, 100, 40)
        self.assertEqual(b.center, (60.0, 40.0))
        self.assertEqual(b.area, 4000)

    def test_empty_result(self):
        r = VisionResult(detector="face")
        self.assertFalse(r.has_detections)
        self.assertEqual(r.detections, ())

    def test_result_with_detections(self):
        d1 = Detection(DetectionKind.FACE, 0.9, BoundingBox(0, 0, 50, 50))
        d2 = Detection(DetectionKind.PHONE, 0.8, label="cell phone")
        r = VisionResult("multi", (d1, d2), frame_index=7, processing_ms=12.3)
        self.assertTrue(r.has_detections)
        self.assertEqual(r.of_kind(DetectionKind.FACE), (d1,))
        self.assertEqual(r.of_kind(DetectionKind.PHONE), (d2,))

    def test_to_dict_serialisable(self):
        d = Detection(DetectionKind.PERSON, 0.75, BoundingBox(1, 2, 3, 4),
                      label="person", track_id=5)
        r = VisionResult("person", (d,), frame_index=1, processing_ms=1.0)
        out = r.to_dict()
        self.assertEqual(out["detector"], "person")
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["detections"][0]["kind"], "PERSON")
        self.assertEqual(out["detections"][0]["box"], [1, 2, 3, 4])
        self.assertEqual(out["detections"][0]["track_id"], 5)

if __name__ == "__main__":
    unittest.main()
