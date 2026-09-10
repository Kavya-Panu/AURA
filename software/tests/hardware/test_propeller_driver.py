import time
import unittest
from hardware.face_driver import MockCommandSink
from hardware.propeller_driver import PropellerDriver

def fast_sleep(s): time.sleep(min(s, 0.002))

class TestPropellerDriver(unittest.TestCase):
    def setUp(self):
        self.sink = MockCommandSink()

    def test_start_stop(self):
        p = PropellerDriver(self.sink, safety_timeout_s=5, sleep=fast_sleep)
        p.start(80)
        self.assertTrue(p.running)
        self.assertEqual(self.sink.for_device("esp32")[-1], "PROP:prop:80")
        p.stop()
        self.assertFalse(p.running)
        self.assertEqual(self.sink.for_device("esp32")[-1], "PROP:prop:0")

    def test_speed_clamped(self):
        p = PropellerDriver(self.sink, safety_timeout_s=5, sleep=fast_sleep)
        p.start(500)
        self.assertEqual(p.speed, 100)

    def test_set_speed_zero_stops(self):
        p = PropellerDriver(self.sink, safety_timeout_s=5, sleep=fast_sleep)
        p.start(50); p.set_speed(0)
        self.assertFalse(p.running)

    def test_safety_timeout_stops(self):
        p = PropellerDriver(self.sink, safety_timeout_s=0.03, sleep=fast_sleep)
        p.start(100)
        self.assertTrue(p.running)
        time.sleep(0.1)                    # exceed the safety timeout
        self.assertFalse(p.running)        # auto-stopped
        self.assertEqual(self.sink.for_device("esp32")[-1], "PROP:prop:0")

    def test_run_for_duration(self):
        p = PropellerDriver(self.sink, safety_timeout_s=5, sleep=fast_sleep)
        p.run_for(0.03, speed=70)
        self.assertTrue(p.running)
        time.sleep(0.1)
        self.assertFalse(p.running)        # stopped after duration

if __name__ == "__main__":
    unittest.main()
