"""CameraSelector: discovery, metadata, default selection, switching, validation."""
import unittest
from vision.camera_selector import (
    CameraSelector, FakeCameraProbe, CameraInfo, CameraKind)
from vision.vision_exceptions import CameraError

def cams():
    return [
        CameraInfo(0, "webcam", CameraKind.LAPTOP_WEBCAM, "v4l2", True, 640, 480),
        CameraInfo(1, "usbcam", CameraKind.USB, "v4l2", True, 1280, 720),
        CameraInfo(2, "offline", CameraKind.USB, "v4l2", False),
    ]

class TestCameraSelector(unittest.TestCase):
    def test_discover_returns_metadata(self):
        sel = CameraSelector(FakeCameraProbe(cams()))
        found = sel.discover()
        self.assertEqual(len(found), 3)
        self.assertEqual(found[1].name, "usbcam")
        self.assertEqual(found[1].kind, CameraKind.USB)

    def test_select_default_first_available(self):
        sel = CameraSelector(FakeCameraProbe(cams()))
        sel.discover()
        self.assertEqual(sel.select_default().camera_id, 0)

    def test_select_default_prefers_preferred_id(self):
        sel = CameraSelector(FakeCameraProbe(cams()), preferred_id=1)
        sel.discover()
        self.assertEqual(sel.select_default().camera_id, 1)

    def test_select_default_skips_unavailable_preferred(self):
        sel = CameraSelector(FakeCameraProbe(cams()), preferred_id=2)  # offline
        sel.discover()
        self.assertEqual(sel.select_default().camera_id, 0)   # falls back

    def test_no_cameras_raises(self):
        sel = CameraSelector(FakeCameraProbe([]))
        with self.assertRaises(CameraError):
            sel.select_default()

    def test_validate(self):
        sel = CameraSelector(FakeCameraProbe(cams()))
        sel.discover()
        self.assertTrue(sel.validate(1))
        self.assertFalse(sel.validate(2))    # offline
        self.assertFalse(sel.validate(99))   # doesn't exist

    def test_select_specific(self):
        sel = CameraSelector(FakeCameraProbe(cams()))
        sel.discover()
        self.assertEqual(sel.select(1).camera_id, 1)
        self.assertEqual(sel.selected.camera_id, 1)

    def test_select_unavailable_raises(self):
        sel = CameraSelector(FakeCameraProbe(cams()))
        sel.discover()
        with self.assertRaises(CameraError):
            sel.select(2)

    def test_csi_kind_supported(self):
        probe = FakeCameraProbe([CameraInfo(0, "csi0", CameraKind.CSI, "gstreamer")])
        sel = CameraSelector(probe); sel.discover()
        self.assertEqual(sel.get_info(0).kind, CameraKind.CSI)

if __name__ == "__main__":
    unittest.main()
