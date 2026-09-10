"""CameraManager: threaded capture, buffer delivery, reconnect, switching, events."""
import time
import unittest
from core.event_bus import EventBus
from core.constants import RobotEvent
from vision import VisionManager
from vision.vision_config import CameraConfig
from vision.camera_selector import CameraSelector, FakeCameraProbe, CameraInfo, CameraKind
from vision.camera_manager import CameraManager, FakeCaptureBackend
from vision.frame_buffer import FrameBuffer
from vision.vision_exceptions import CameraError

def wait_until(predicate, timeout_s=2.0, interval_s=0.005):
    """Poll until predicate() is true or timeout; returns the final bool.
    Makes threaded tests deterministic instead of sleeping a fixed time."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval_s)
    return predicate()

def build(backend=None, cfg=None, cameras=None):
    bus = EventBus()
    vm = VisionManager(bus)
    seen = []
    bus.subscribe_all(lambda e: seen.append((e.type, e.data)))
    cams = cameras or [CameraInfo(0, "webcam", CameraKind.LAPTOP_WEBCAM, available=True),
                       CameraInfo(1, "usb", CameraKind.USB, available=True)]
    sel = CameraSelector(FakeCameraProbe(cams))
    sel.discover()
    buf = FrameBuffer(max_frames=3)
    be = backend or FakeCaptureBackend(width=320, height=240)
    cfg = cfg or CameraConfig(target_fps=500)   # fast, no real waiting
    cm = CameraManager(vm, cfg, sel, buf, be,
                       sleep=lambda s: time.sleep(min(s, 0.001)))
    return bus, vm, cm, buf, be, seen

class TestCameraManager(unittest.TestCase):
    def test_open_emits_connected(self):
        bus, vm, cm, buf, be, seen = build()
        cm.open()
        self.assertTrue(cm.is_open)
        self.assertTrue(vm.context.camera_connected)
        self.assertIn(RobotEvent.CAMERA_CONNECTED, [t for t, _ in seen])

    def test_capture_pushes_frames(self):
        bus, vm, cm, buf, be, seen = build()
        cm.open(); cm.start()
        self.assertTrue(wait_until(lambda: buf.pushed_count > 0))
        cm.stop()
        self.assertGreater(buf.pushed_count, 0)
        f = buf.get_latest()
        self.assertEqual((f.width, f.height), (320, 240))
        self.assertEqual(f.camera_id, 0)

    def test_frames_are_timestamped_and_indexed(self):
        bus, vm, cm, buf, be, seen = build()
        cm.open(); cm.start()
        wait_until(lambda: buf.pushed_count >= 2)
        cm.stop()
        frames = buf.snapshot()
        self.assertTrue(all(fr.timestamp > 0 for fr in frames))
        idxs = [fr.index for fr in frames]
        self.assertEqual(idxs, sorted(idxs))    # monotonic

    def test_stop_emits_disconnected(self):
        bus, vm, cm, buf, be, seen = build()
        cm.open(); cm.start()
        wait_until(lambda: buf.pushed_count > 0)
        cm.stop()
        self.assertIn(RobotEvent.CAMERA_DISCONNECTED, [t for t, _ in seen])
        self.assertFalse(cm.is_running)

    def test_auto_reconnect_on_read_failure(self):
        # A backend that fails reads once its counter passes `fail_after`, but
        # RECOVERS whenever it is reopened (open count > 1). This models a real
        # transient disconnect without defeating the initial open.
        class RecoveringBackend(FakeCaptureBackend):
            def __init__(self):
                super().__init__(width=320, height=240, fail_after=3)
                self.opens = 0
            def open(self, camera_id, config):
                super().open(camera_id, config)
                self.opens += 1
                # First open keeps the fault; any reopen clears it.
                self._fail_after = None if self.opens > 1 else 3
        be = RecoveringBackend()
        cfg = CameraConfig(target_fps=500, auto_reconnect=True,
                           reconnect_interval_s=0, max_reconnect_attempts=5)
        bus, vm, cm, buf, _, seen = build(backend=be, cfg=cfg)
        cm.open(); cm.start()
        types = lambda: [t for t, _ in seen]
        ok = wait_until(
            lambda: types().count(RobotEvent.CAMERA_CONNECTED) >= 2
            and RobotEvent.CAMERA_DISCONNECTED in types())
        cm.stop()
        self.assertTrue(ok, "expected a disconnect followed by a reconnect")
        self.assertGreaterEqual(be.opens, 2)                          # reopened

    def test_no_reconnect_when_disabled_stops(self):
        be = FakeCaptureBackend(fail_after=2)
        cfg = CameraConfig(target_fps=500, auto_reconnect=False)
        bus, vm, cm, buf, be, seen = build(backend=be, cfg=cfg)
        cm.open(); cm.start()
        # loop must exit itself on failure since reconnect is disabled
        self.assertTrue(wait_until(lambda: not cm.is_running))
        cm.stop()

    def test_switch_camera(self):
        bus, vm, cm, buf, be, seen = build()
        cm.open(); cm.start()
        wait_until(lambda: buf.pushed_count > 0)
        cm.switch_camera(1)
        self.assertEqual(cm.camera_id, 1)
        wait_until(lambda: any(fr.camera_id == 1 for fr in buf.snapshot()))
        cm.stop()

    def test_switch_to_invalid_raises(self):
        bus, vm, cm, buf, be, seen = build()
        cm.open()
        with self.assertRaises(CameraError):
            cm.switch_camera(99)
        cm.stop()

    def test_dedicated_thread_used(self):
        import threading
        before = threading.active_count()
        bus, vm, cm, buf, be, seen = build()
        cm.open(); cm.start()
        self.assertGreater(threading.active_count(), before)  # a thread spawned
        names = [t.name for t in threading.enumerate()]
        self.assertIn("camera-capture", names)
        cm.stop()

if __name__ == "__main__":
    unittest.main()
