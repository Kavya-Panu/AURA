"""Tests for core.timer."""
import time
import unittest

from core.timer import Timer


class TestTimer(unittest.TestCase):
    def test_one_shot_fires(self):
        fired = []
        t = Timer(0.10, lambda tm: fired.append(tm.name), name="t1").start()
        self.assertTrue(t.wait(1.0))
        self.assertEqual(fired, ["t1"])
        self.assertAlmostEqual(t.remaining(), 0.0, places=2)

    def test_cancel_prevents_callback(self):
        fired = []
        t = Timer(0.15, lambda tm: fired.append(1)).start()
        time.sleep(0.05)
        t.cancel()
        t.wait(1.0)
        self.assertEqual(fired, [])
        self.assertFalse(t.is_running())

    def test_pause_resume(self):
        fired = []
        t = Timer(0.20, lambda tm: fired.append(1)).start()
        time.sleep(0.05)
        t.pause()
        r1 = t.remaining()
        time.sleep(0.15)                       # paused: remaining frozen
        r2 = t.remaining()
        self.assertAlmostEqual(r1, r2, delta=0.02)
        self.assertEqual(fired, [])            # would have expired if unpaused
        t.resume()
        self.assertTrue(t.wait(1.0))
        self.assertEqual(fired, [1])

    def test_elapsed_and_remaining(self):
        t = Timer(1.0).start()
        time.sleep(0.20)
        self.assertGreater(t.elapsed(), 0.1)
        self.assertLess(t.remaining(), 1.0)
        self.assertAlmostEqual(t.elapsed() + t.remaining(), 1.0, delta=0.05)
        t.cancel()

    def test_repeating_fires_multiple_times(self):
        fired = []
        t = Timer(0.06, lambda tm: fired.append(1), repeating=True).start()
        time.sleep(0.32)
        t.cancel()
        self.assertGreaterEqual(len(fired), 3)

    def test_callback_exception_survives(self):
        def bad(tm): raise RuntimeError("boom")
        t = Timer(0.05, bad, repeating=True).start()
        time.sleep(0.18)
        self.assertTrue(t.is_running())        # still alive despite raising
        t.cancel()

    def test_invalid_duration(self):
        with self.assertRaises(ValueError):
            Timer(0)


if __name__ == "__main__":
    unittest.main()
