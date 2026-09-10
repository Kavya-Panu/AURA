"""VisionConfig defaults and validation."""
import unittest
from vision.vision_config import VisionConfig, CameraConfig, ProcessingConfig
from vision.vision_exceptions import VisionConfigurationError

class TestVisionConfig(unittest.TestCase):
    def test_defaults_valid(self):
        VisionConfig().validate()   # must not raise

    def test_bad_dimensions(self):
        cfg = VisionConfig(camera=CameraConfig(width=0))
        with self.assertRaises(VisionConfigurationError):
            cfg.validate()

    def test_bad_fps(self):
        cfg = VisionConfig(camera=CameraConfig(target_fps=0))
        with self.assertRaises(VisionConfigurationError):
            cfg.validate()

    def test_bad_detect_interval(self):
        cfg = VisionConfig(processing=ProcessingConfig(detect_every_n_frames=0))
        with self.assertRaises(VisionConfigurationError):
            cfg.validate()

    def test_bad_downscale(self):
        cfg = VisionConfig(processing=ProcessingConfig(downscale=2.0))
        with self.assertRaises(VisionConfigurationError):
            cfg.validate()

    def test_toggles_default(self):
        cfg = VisionConfig()
        self.assertTrue(cfg.detectors.face)
        self.assertFalse(cfg.detectors.gesture)

if __name__ == "__main__":
    unittest.main()
