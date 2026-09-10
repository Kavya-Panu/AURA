"""VisionManager: registration, lifecycle, events, camera seams, context."""
import unittest
from core.event_bus import EventBus
from core.constants import RobotEvent
from core.lifecycle import Module
from vision.vision_manager import VisionManager
from vision.vision_config import VisionConfig
from vision.vision_result import VisionResult, Detection, DetectionKind
from vision.vision_exceptions import DetectorRegistrationError


class FakeDetector:
    """Minimal detector satisfying the Detector protocol (no detection logic)."""
    def __init__(self, name="fake", healthy=True, fail_start=False):
        self.name = name
        self._healthy = healthy
        self._fail_start = fail_start
        self.events = []
    def initialize(self): self.events.append("init")
    def start(self):
        if self._fail_start: raise RuntimeError("start boom")
        self.events.append("start")
    def stop(self): self.events.append("stop")
    def health_check(self): return self._healthy


def make():
    bus = EventBus()
    vm = VisionManager(bus, VisionConfig())
    seen = []
    bus.subscribe_all(lambda e: seen.append((e.type, e.data)))
    return bus, vm, seen


class TestManager(unittest.TestCase):
    def test_is_a_module(self):
        _, vm, _ = make()
        self.assertIsInstance(vm, Module)

    def test_register_and_list(self):
        _, vm, _ = make()
        vm.register_detector(FakeDetector("face"))
        vm.register_detector(FakeDetector("phone"))
        self.assertEqual(vm.detectors, ("face", "phone"))

    def test_duplicate_registration_raises(self):
        _, vm, _ = make()
        vm.register_detector(FakeDetector("face"))
        with self.assertRaises(DetectorRegistrationError):
            vm.register_detector(FakeDetector("face"))

    def test_bad_object_registration_raises(self):
        _, vm, _ = make()
        with self.assertRaises(DetectorRegistrationError):
            vm.register_detector(object())    # not a Detector

    def test_lifecycle_drives_detectors(self):
        _, vm, _ = make()
        d = FakeDetector("face")
        vm.register_detector(d)
        vm.initialize(); vm.start()
        self.assertIn("init", d.events)
        self.assertIn("start", d.events)
        self.assertIn("face", vm.context.active_detectors)
        vm.stop()
        self.assertIn("stop", d.events)
        self.assertEqual(vm.context.active_detectors, ())

    def test_start_stop_emit_events(self):
        _, vm, seen = make()
        vm.initialize(); vm.start(); vm.stop()
        types = [t for t, _ in seen]
        self.assertIn(RobotEvent.VISION_STARTED, types)
        self.assertIn(RobotEvent.VISION_STOPPED, types)

    def test_running_flag_and_context(self):
        _, vm, _ = make()
        vm.start()
        self.assertTrue(vm.context.snapshot().running)
        vm.stop()
        self.assertFalse(vm.context.snapshot().running)

    def test_register_while_running_joins(self):
        _, vm, _ = make()
        vm.start()
        d = FakeDetector("late")
        vm.register_detector(d)
        self.assertIn("start", d.events)
        self.assertIn("late", vm.context.active_detectors)

    def test_detector_start_failure_emits_error(self):
        _, vm, seen = make()
        vm.register_detector(FakeDetector("bad", fail_start=True))
        vm.start()
        types = [t for t, _ in seen]
        self.assertIn(RobotEvent.VISION_ERROR, types)
        self.assertIsNotNone(vm.context.last_error)

    def test_health_check(self):
        _, vm, _ = make()
        self.assertFalse(vm.health_check())          # not started
        vm.register_detector(FakeDetector("face", healthy=True))
        vm.start()
        self.assertTrue(vm.health_check())
        vm.register_detector(FakeDetector("sick", healthy=False))
        self.assertFalse(vm.health_check())          # one unhealthy

    def test_camera_connect_disconnect_events(self):
        _, vm, seen = make()
        vm.on_camera_connected(camera_id=1)
        self.assertTrue(vm.context.camera_connected)
        vm.on_camera_disconnected("unplugged")
        self.assertFalse(vm.context.camera_connected)
        types = [t for t, _ in seen]
        self.assertIn(RobotEvent.CAMERA_CONNECTED, types)
        self.assertIn(RobotEvent.CAMERA_DISCONNECTED, types)

    def test_update_metrics(self):
        _, vm, _ = make()
        vm.update_metrics(capture_fps=29.0, processing_fps=10.0)
        snap = vm.context.snapshot()
        self.assertEqual(snap.capture_fps, 29.0)
        self.assertEqual(snap.processing_fps, 10.0)

    def test_publish_result_seam(self):
        _, vm, seen = make()
        r = VisionResult("face", (Detection(DetectionKind.FACE, 0.9),),
                         frame_index=3)
        vm.publish_result(r)
        payloads = [d for t, d in seen if t == RobotEvent.VISION_RESULT]
        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0]["detector"], "face")
        self.assertEqual(payloads[0]["count"], 1)

    def test_unregister(self):
        _, vm, _ = make()
        vm.register_detector(FakeDetector("face"))
        self.assertTrue(vm.unregister_detector("face"))
        self.assertFalse(vm.unregister_detector("face"))
        self.assertEqual(vm.detectors, ())

    def test_set_enabled(self):
        _, vm, _ = make()
        vm.start()
        vm.set_enabled(False)
        self.assertFalse(vm.health_check())          # disabled -> unhealthy
        self.assertFalse(vm.context.enabled)


if __name__ == "__main__":
    unittest.main()
