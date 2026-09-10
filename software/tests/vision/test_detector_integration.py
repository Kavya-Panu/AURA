"""All four detectors register with the real VisionManager and run via Lifecycle,
and the face detector -> face tracker chain works end to end over the bus."""
import unittest
from core.event_bus import EventBus
from core.constants import RobotEvent, RobotState
from core.lifecycle import LifecycleManager
from core.state_machine import build_aura_state_machine
from vision import VisionManager, VisionConfig
from vision.vision_config import ProcessingConfig
from vision.frame_buffer import FrameBuffer
from vision.face_detector import FaceDetector, FakeFaceBackend, FaceBox
from vision.face_tracker import FaceTracker
from vision.person_detector import PersonDetector, FakePersonBackend, PersonBox
from vision.phone_detector import PhoneDetector, FakePhoneBackend, PhoneBox
from vision.tests._vhelpers import collect, push_frame, wait_until

class TestIntegration(unittest.TestCase):
    def test_all_register_and_lifecycle(self):
        bus = EventBus()
        sm = build_aura_state_machine(bus)
        life = LifecycleManager(bus, sm)
        cfg = VisionConfig(); cfg.processing = ProcessingConfig(detect_every_n_frames=1)
        buf = FrameBuffer(max_frames=4)
        vm = VisionManager(bus, cfg)
        vm.register_detector(FaceDetector(bus, buf, cfg, FakeFaceBackend([[]])))
        vm.register_detector(FaceTracker(bus))
        vm.register_detector(PersonDetector(bus, buf, cfg, FakePersonBackend([[]])))
        vm.register_detector(PhoneDetector(bus, buf, cfg, FakePhoneBackend([[]])))
        life.register(vm)
        life.startup()
        self.assertEqual(set(vm.detectors),
                         {"face", "face_tracker", "person", "phone"})
        # Lifecycle reports MODULES (the VisionManager registers as "vision").
        report = life.health_report()
        self.assertIn("vision", report)
        self.assertTrue(report["vision"])
        # The manager's own health aggregates its detectors.
        self.assertTrue(vm.health_check())
        life.shutdown()

    def test_face_detector_to_tracker_chain(self):
        bus = EventBus()
        cfg = VisionConfig(); cfg.processing = ProcessingConfig(detect_every_n_frames=1)
        buf = FrameBuffer(max_frames=4)
        seen = collect(bus)
        fd = FaceDetector(bus, buf, cfg,
                          FakeFaceBackend([[FaceBox(320 - 30, 240 - 30, 60, 60, 0.95)]]))
        ft = FaceTracker(bus, smoothing=1.0)
        fd.initialize(); fd.start(); ft.initialize(); ft.start()
        push_frame(buf, 0, w=640, h=480)
        # detector emits FACE_FOUND -> tracker emits FACE_POSITION
        self.assertTrue(wait_until(
            lambda: any(t == RobotEvent.FACE_POSITION for t, _ in seen)))
        fd.stop(); ft.stop()
        pos = next(d for t, d in seen if t == RobotEvent.FACE_POSITION)
        self.assertAlmostEqual(pos["x"], 0.0, delta=0.05)   # centered face

    def test_detectors_are_independent(self):
        # Each detector must not IMPORT another detector or the wrong model.
        # Check real import statements via the AST, not docstring prose (the
        # phone module's docstring legitimately says "never imports mediapipe").
        import ast
        import vision.face_detector as fdmod
        import vision.person_detector as pdmod
        import vision.phone_detector as phmod
        import vision.face_tracker as ftmod

        def imports(module):
            tree = ast.parse(open(module.__file__).read())
            names = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names.update(a.name for a in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names.add(node.module)
            return names

        face_imports = imports(fdmod)
        person_imports = imports(pdmod)
        phone_imports = imports(phmod)
        tracker_imports = imports(ftmod)

        # Face never depends on YOLO/ultralytics; phone/person never on MediaPipe.
        self.assertFalse(any("ultralytics" in m for m in face_imports))
        self.assertFalse(any("mediapipe" in m for m in phone_imports))
        self.assertFalse(any("mediapipe" in m for m in person_imports))
        self.assertFalse(any("mediapipe" in m for m in tracker_imports))
        # No detector imports another detector module.
        for imps in (face_imports, person_imports, phone_imports, tracker_imports):
            self.assertFalse(any(
                x in imps for x in
                ("vision.face_detector", "vision.person_detector",
                 "vision.phone_detector", "vision.face_tracker")),
                f"a detector imports another detector: {imps}")

if __name__ == "__main__":
    unittest.main()
