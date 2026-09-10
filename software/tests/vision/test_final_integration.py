"""All final-stage detectors run under the pipeline + VisionManager + Lifecycle,
and the eye/head -> fatigue chain works over the bus."""
import unittest
from core.event_bus import EventBus
from core.constants import RobotEvent
from core.lifecycle import LifecycleManager
from core.state_machine import build_aura_state_machine
from vision import VisionManager, VisionConfig
from vision.vision_config import ProcessingConfig
from vision.frame_buffer import FrameBuffer
from vision.vision_pipeline import VisionPipeline
from vision.performance_monitor import PerformanceMonitor
from vision.gesture_detector import GestureDetector, FakeGestureBackend
from vision.smile_detector import SmileDetector, FakeFaceMeshBackend as SFB
from vision.eye_contact import EyeContactDetector, FakeFaceMeshBackend as EFB
from vision.head_pose import HeadPoseDetector, FakeFaceMeshBackend as HFB
from vision.fatigue_detector import FatigueDetector, FatigueConfig
from vision.tests._vhelpers import collect

class TestFinalIntegration(unittest.TestCase):
    def test_pipeline_groups_all_detectors_via_manager(self):
        bus = EventBus()
        sm = build_aura_state_machine(bus)
        life = LifecycleManager(bus, sm)
        cfg = VisionConfig(); cfg.processing = ProcessingConfig(detect_every_n_frames=1)
        buf = FrameBuffer(max_frames=4)
        pipe = VisionPipeline(bus, buf, PerformanceMonitor(cpu_sampler=lambda: 0.0))
        pipe.add_detector(GestureDetector(bus, buf, cfg, FakeGestureBackend([[]])))
        pipe.add_detector(SmileDetector(bus, buf, cfg, SFB([[]])))
        pipe.add_detector(EyeContactDetector(bus, buf, cfg, EFB([[]])))
        pipe.add_detector(HeadPoseDetector(bus, buf, cfg, HFB([[]])))
        pipe.add_detector(FatigueDetector(bus))
        vm = VisionManager(bus, cfg)
        vm.register_detector(pipe)            # ONE registration, no manager edits
        life.register(vm)
        life.startup()
        self.assertEqual(set(pipe.enabled_detectors()),
                         {"gesture", "smile", "eye_contact", "head_pose", "fatigue"})
        self.assertTrue(life.health_report()["vision"])
        life.shutdown()

    def test_eye_head_to_fatigue_chain(self):
        bus = EventBus(); seen = collect(bus)
        class Clk:
            def __init__(self): self.t = 0.0
            def __call__(self): return self.t
            def adv(self, d): self.t += d
        clk = Clk()
        fatigue = FatigueDetector(bus, FatigueConfig(look_away_events_for_tired=3,
                                                     cooldown_s=30), clk)
        fatigue.start()
        # simulate the eye-contact detector publishing repeated look-aways
        for _ in range(3):
            bus.emit(RobotEvent.LOOKING_AWAY, {"duration_s": 0.5}, source="eye_contact")
            clk.adv(1.0)
        self.assertTrue(any(t == RobotEvent.USER_TIRED for t, _ in seen))
        fatigue.stop()

if __name__ == "__main__":
    unittest.main()
