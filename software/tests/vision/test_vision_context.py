"""VisionContext state + thread-safe snapshots."""
import threading
import unittest
from vision.vision_context import VisionContext

class TestVisionContext(unittest.TestCase):
    def test_initial_state(self):
        ctx = VisionContext(camera_id=2)
        snap = ctx.snapshot()
        self.assertTrue(snap.enabled)
        self.assertFalse(snap.running)
        self.assertFalse(snap.camera_connected)
        self.assertEqual(snap.camera_id, 2)
        self.assertEqual(snap.active_detectors, ())
        self.assertIsNone(snap.last_error)

    def test_mutations_reflected_in_snapshot(self):
        ctx = VisionContext()
        ctx.set_running(True)
        ctx.set_camera_connected(True)
        ctx.set_capture_fps(30.0)
        ctx.set_processing_fps(12.5)
        ctx.add_detector("face")
        ctx.add_detector("phone")
        ctx.set_error("boom")
        snap = ctx.snapshot()
        self.assertTrue(snap.running)
        self.assertTrue(snap.camera_connected)
        self.assertEqual(snap.capture_fps, 30.0)
        self.assertEqual(snap.processing_fps, 12.5)
        self.assertEqual(snap.active_detectors, ("face", "phone"))
        self.assertEqual(snap.last_error, "boom")

    def test_remove_detector_and_clear_error(self):
        ctx = VisionContext()
        ctx.add_detector("face")
        ctx.remove_detector("face")
        ctx.set_error("x"); ctx.clear_error()
        snap = ctx.snapshot()
        self.assertEqual(snap.active_detectors, ())
        self.assertIsNone(snap.last_error)

    def test_snapshot_is_immutable(self):
        snap = VisionContext().snapshot()
        with self.assertRaises(Exception):
            snap.running = True   # frozen dataclass

    def test_thread_safety(self):
        ctx = VisionContext()
        def worker(i):
            for _ in range(200):
                ctx.add_detector(f"d{i}")
                ctx.set_capture_fps(i)
                ctx.snapshot()
                ctx.remove_detector(f"d{i}")
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads: t.start()
        for t in threads: t.join()
        # no exception + a consistent snapshot
        self.assertIsNotNone(ctx.snapshot())

if __name__ == "__main__":
    unittest.main()
