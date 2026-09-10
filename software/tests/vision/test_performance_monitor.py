import unittest
from vision.performance_monitor import PerformanceMonitor

class FakeClock:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t
    def advance(self, dt): self.t += dt

class TestPerfMonitor(unittest.TestCase):
    def test_detector_timing(self):
        pm = PerformanceMonitor(cpu_sampler=lambda: 12.0)
        pm.record_detector_time("face", 5.0)
        pm.record_detector_time("face", 15.0)
        snap = pm.snapshot()
        d = next(x for x in snap.detectors if x.name == "face")
        self.assertEqual(d.last_ms, 15.0)
        self.assertEqual(d.avg_ms, 10.0)
        self.assertEqual(d.max_ms, 15.0)
        self.assertEqual(d.samples, 2)

    def test_processing_fps(self):
        clk = FakeClock()
        pm = PerformanceMonitor(clock=clk, cpu_sampler=lambda: 0.0)
        for _ in range(5):
            pm.record_processed_frame(); clk.advance(0.1)  # 10 fps
        self.assertAlmostEqual(pm.snapshot().processing_fps, 10.0, delta=1.0)

    def test_camera_fps_and_dropped(self):
        pm = PerformanceMonitor(cpu_sampler=lambda: 0.0)
        pm.record_camera_fps(29.5); pm.record_dropped(7)
        snap = pm.snapshot()
        self.assertEqual(snap.camera_fps, 29.5)
        self.assertEqual(snap.dropped_frames, 7)

    def test_as_dict(self):
        pm = PerformanceMonitor(cpu_sampler=lambda: 50.0)
        pm.record_detector_time("phone", 3.0)
        d = pm.as_dict()
        self.assertIn("phone", d["detectors"])
        self.assertEqual(d["cpu_percent"], 50.0)
        self.assertIsNone(d["gpu_percent"])

    def test_thread_safe(self):
        import threading
        pm = PerformanceMonitor(cpu_sampler=lambda: 0.0)
        def worker(i):
            for _ in range(500):
                pm.record_detector_time(f"d{i}", float(i))
                pm.record_processed_frame()
                pm.snapshot()
        ts = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
        for t in ts: t.start()
        for t in ts: t.join()
        self.assertEqual(len(pm.snapshot().detectors), 6)

if __name__ == "__main__":
    unittest.main()
