"""FrameBuffer: thread-safety, latest-only, drop-oldest, timestamps, multi-consumer."""
import threading
import time
import unittest
from vision.frame_buffer import FrameBuffer, Frame

def mk(i, data=None):
    return Frame(data=data or f"f{i}", index=i, timestamp=time.monotonic(),
                 width=64, height=48, camera_id=0)

class TestFrameBuffer(unittest.TestCase):
    def test_push_and_get_latest(self):
        b = FrameBuffer(max_frames=3)
        b.push(mk(0)); b.push(mk(1))
        self.assertEqual(b.get_latest().index, 1)
        self.assertEqual(b.size, 2)

    def test_drops_oldest_when_full(self):
        b = FrameBuffer(max_frames=2)
        for i in range(5):
            b.push(mk(i))
        self.assertEqual(b.size, 2)                 # never grows past capacity
        indices = [f.index for f in b.snapshot()]
        self.assertEqual(indices, [3, 4])            # only newest kept
        self.assertEqual(b.dropped_count, 3)
        self.assertEqual(b.pushed_count, 5)

    def test_memory_bounded(self):
        b = FrameBuffer(max_frames=2)
        for i in range(10_000):
            b.push(mk(i))
        self.assertLessEqual(b.size, 2)

    def test_since_index_prevents_reprocessing(self):
        b = FrameBuffer(max_frames=3)
        b.push(mk(5))
        self.assertIsNotNone(b.get_latest(since_index=4))
        self.assertIsNone(b.get_latest(since_index=5))   # already seen
        self.assertIsNone(b.get_latest(since_index=6))

    def test_timestamp_and_age(self):
        b = FrameBuffer()
        b.push(mk(0))
        f = b.get_latest()
        self.assertGreaterEqual(f.age_s, 0.0)

    def test_wait_for_frame_returns_on_push(self):
        b = FrameBuffer()
        got = []
        def consumer():
            got.append(b.wait_for_frame(since_index=-1, timeout_s=1.0))
        t = threading.Thread(target=consumer); t.start()
        time.sleep(0.02)
        b.push(mk(7))
        t.join()
        self.assertIsNotNone(got[0])
        self.assertEqual(got[0].index, 7)

    def test_wait_for_frame_timeout(self):
        b = FrameBuffer()
        self.assertIsNone(b.wait_for_frame(since_index=-1, timeout_s=0.05))

    def test_multiple_consumers_same_latest(self):
        b = FrameBuffer(max_frames=2)
        b.push(mk(9))
        results = []
        def consumer():
            results.append(b.get_latest().index)
        threads = [threading.Thread(target=consumer) for _ in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertTrue(all(r == 9 for r in results))

    def test_thread_safe_producer_consumer(self):
        b = FrameBuffer(max_frames=4)
        b.push(mk(0))                      # ensure a frame exists from the start
        stop = threading.Event()
        seen = []
        seen_lock = threading.Lock()
        def producer():
            for i in range(1, 2000):
                b.push(mk(i))
        def consumer():
            local = 0
            while not stop.is_set():
                f = b.get_latest()
                if f is not None:
                    local = f.index
            # one guaranteed final read so scheduling can't zero us out
            f = b.get_latest()
            with seen_lock:
                seen.append(f.index if f is not None else local)
        prod = threading.Thread(target=producer)
        cons = [threading.Thread(target=consumer) for _ in range(4)]
        for c in cons: c.start()
        prod.start(); prod.join()
        stop.set()
        for c in cons: c.join()
        self.assertEqual(len(seen), 4)          # every consumer recorded a read
        self.assertLessEqual(b.size, 4)         # bounded throughout
        self.assertEqual(b.pushed_count, 2000)  # no lost pushes

    def test_clear(self):
        b = FrameBuffer()
        b.push(mk(0)); b.clear()
        self.assertEqual(b.size, 0)
        self.assertIsNone(b.get_latest())

    def test_invalid_capacity(self):
        with self.assertRaises(ValueError):
            FrameBuffer(max_frames=0)

if __name__ == "__main__":
    unittest.main()
