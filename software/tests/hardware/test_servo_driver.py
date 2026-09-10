import unittest
from hardware.face_driver import MockCommandSink
from hardware.servo_driver import ServoDriver, ServoLimits

class TestServoDriver(unittest.TestCase):
    def setUp(self):
        self.sink = MockCommandSink()
        self.servo = ServoDriver(self.sink, "pan",
                                 ServoLimits(min_angle=0, max_angle=180),
                                 sleep=lambda s: None)

    def test_move_to(self):
        self.servo.move_to(90)
        self.assertEqual(self.sink.for_device("esp32")[-1], "SERVO:pan:90.0")
        self.assertEqual(self.servo.angle, 90)

    def test_limits_clamped(self):
        self.assertEqual(self.servo.move_to(500), 180)
        self.assertEqual(self.servo.move_to(-500), 0)

    def test_calibration_offset(self):
        s = ServoDriver(self.sink, "tilt",
                        ServoLimits(0, 180, calibration_offset=10),
                        sleep=lambda s: None)
        s.move_to(90)
        self.assertEqual(self.sink.for_device("esp32")[-1], "SERVO:tilt:100.0")

    def test_smooth_movement_reaches_target(self):
        self.servo.move_to(0)
        self.servo.move_smooth(60, speed_dps=1000, blocking=True)
        self.assertEqual(self.servo.angle, 60)
        # multiple stepped commands were emitted
        self.assertGreater(len(self.sink.for_device("esp32")), 2)

    def test_center(self):
        self.servo.center()
        self.assertEqual(self.servo.angle, 90)

    def test_cancel_smooth(self):
        # Needs a REAL (small) sleep so the move is gradual and still running
        # when we cancel; the setUp servo uses a no-op sleep that finishes
        # instantly, which would defeat the cancel.
        import time
        sink = MockCommandSink()
        servo = ServoDriver(sink, "pan", ServoLimits(min_angle=0, max_angle=180),
                            sleep=lambda s: time.sleep(0.01))
        servo.move_to(0)
        servo.move_smooth(180, speed_dps=20)   # gradual, non-blocking
        time.sleep(0.02)                        # let it move a little
        servo.cancel()
        self.assertLess(servo.angle, 180)       # didn't finish

if __name__ == "__main__":
    unittest.main()
