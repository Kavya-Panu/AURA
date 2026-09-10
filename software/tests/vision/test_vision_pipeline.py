import unittest
from core.event_bus import EventBus
from core.constants import RobotEvent
from vision import Detector, VisionManager, VisionConfig
from vision.frame_buffer import FrameBuffer, Frame
from vision.vision_pipeline import VisionPipeline
from vision.performance_monitor import PerformanceMonitor
from vision.vision_result import VisionResult, Detection, DetectionKind
from vision.tests._vhelpers import collect, push_frame

class FakeDet:
    def __init__(self, name, healthy=True):
        self.name = name; self._h = healthy
        self.events = []
    def initialize(self): self.events.append("init")
    def start(self): self.events.append("start")
    def stop(self): self.events.append("stop")
    def health_check(self): return self._h

def build():
    bus = EventBus(); buf = FrameBuffer(max_frames=4)
    pipe = VisionPipeline(bus, buf, PerformanceMonitor(cpu_sampler=lambda: 0.0))
    return bus, buf, pipe, collect(bus)

class TestPipeline(unittest.TestCase):
    def test_is_detector(self):
        _, _, pipe, _ = build()
        self.assertIsInstance(pipe, Detector)

    def test_add_remove_without_manager(self):
        _, _, pipe, _ = build()
        pipe.add_detector(FakeDet("a")); pipe.add_detector(FakeDet("b"))
        self.assertEqual(pipe.detectors, ("a", "b"))
        self.assertTrue(pipe.remove_detector("a"))
        self.assertEqual(pipe.detectors, ("b",))

    def test_lifecycle_starts_enabled_only(self):
        _, _, pipe, seen = build()
        a = FakeDet("a"); b = FakeDet("b")
        pipe.add_detector(a, enabled=True)
        pipe.add_detector(b, enabled=False)
        pipe.initialize(); pipe.start()
        self.assertIn("start", a.events)
        self.assertNotIn("start", b.events)   # disabled -> not started
        self.assertIn(RobotEvent.PIPELINE_STARTED, [t for t, _ in seen])
        pipe.stop()
        self.assertIn(RobotEvent.PIPELINE_STOPPED, [t for t, _ in seen])

    def test_enable_disable_runtime(self):
        _, _, pipe, _ = build()
        b = FakeDet("b")
        pipe.add_detector(b, enabled=False)
        pipe.start()
        pipe.set_enabled("b", True)
        self.assertIn("start", b.events)
        self.assertIn("b", pipe.enabled_detectors())
        pipe.set_enabled("b", False)
        self.assertIn("stop", b.events)
        pipe.stop()

    def test_health(self):
        _, _, pipe, _ = build()
        pipe.add_detector(FakeDet("a", healthy=True))
        self.assertFalse(pipe.health_check())   # not started
        pipe.start()
        self.assertTrue(pipe.health_check())
        pipe.add_detector(FakeDet("bad", healthy=False))
        self.assertFalse(pipe.health_check())
        pipe.stop()

    def test_process_frame_merges_and_times(self):
        _, buf, pipe, _ = build()
        pipe.add_detector(FakeDet("face"))
        pipe.add_detector(FakeDet("phone"))
        pipe.start()
        frame = Frame(data="x", index=0, timestamp=0.0, width=640, height=480)
        def infer(name, fr):
            kind = DetectionKind.FACE if name == "face" else DetectionKind.PHONE
            return VisionResult(name, (Detection(kind, 0.9),), frame_index=fr.index)
        combined = pipe.process_frame(frame, infer=infer)
        self.assertEqual(len(combined.detections), 2)   # merged from both
        perf = pipe.performance()
        self.assertIn("face", perf["detectors"])
        self.assertIn("phone", perf["detectors"])
        pipe.stop()

    def test_detector_error_emits_pipeline_error(self):
        _, buf, pipe, seen = build()
        pipe.add_detector(FakeDet("boom"))
        pipe.start()
        frame = Frame(data="x", index=0, timestamp=0.0, width=64, height=64)
        def infer(name, fr): raise RuntimeError("kaboom")
        pipe.process_frame(frame, infer=infer)
        self.assertIn(RobotEvent.PIPELINE_ERROR, [t for t, _ in seen])
        pipe.stop()

    def test_registers_with_vision_manager_as_single_detector(self):
        bus = EventBus(); buf = FrameBuffer()
        vm = VisionManager(bus)
        pipe = VisionPipeline(bus, buf, PerformanceMonitor(cpu_sampler=lambda: 0.0))
        pipe.add_detector(FakeDet("face"))
        vm.register_detector(pipe)            # manager unmodified, gains all detectors
        self.assertIn("pipeline", vm.detectors)
        vm.initialize(); vm.start()
        self.assertTrue(vm.health_check())
        vm.stop()

if __name__ == "__main__":
    unittest.main()
