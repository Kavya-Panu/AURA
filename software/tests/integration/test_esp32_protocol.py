import unittest

from hardware.esp32_protocol import (
    blink_command,
    brightness_command,
    emotion_command,
    focus_command,
    gaze_command,
    timer_alert_command,
    timer_start_command,
    timer_stop_command,
)


class TestEsp32Protocol(unittest.TestCase):
    def test_emotion_aliases_match_firmware(self):
        self.assertEqual(emotion_command("NORMAL"), "NEUTRAL")
        self.assertEqual(emotion_command("thinking"), "THINK")
        self.assertEqual(emotion_command("FACE HAPPY"), "HAPPY")

    def test_gaze_is_discretized(self):
        self.assertEqual(gaze_command(0.0, 0.0), "LOOK CENTER")
        self.assertEqual(gaze_command(0.8, 0.1), "LOOK RIGHT")
        self.assertEqual(gaze_command(-0.8, 0.1), "LOOK LEFT")
        self.assertEqual(gaze_command(0.1, -0.8), "LOOK UP")
        self.assertEqual(gaze_command(0.1, 0.8), "LOOK DOWN")

    def test_blink_focus_and_brightness(self):
        self.assertEqual(blink_command(1), "BLINK")
        self.assertEqual(blink_command(3), "DOUBLE_BLINK")
        self.assertEqual(focus_command(True), "BOOK START")
        self.assertEqual(focus_command(False), "BOOK STOP")
        self.assertEqual(brightness_command(999), "BRIGHTNESS 255")

    def test_timer_commands(self):
        self.assertEqual(timer_start_command(1200, "reminder"),
                         "TIMER START 1200 REMINDER")
        self.assertEqual(timer_alert_command("alarm"), "TIMER ALERT ALARM")
        self.assertEqual(timer_start_command(1500, "focus"),
                         "TIMER START 1500 FOCUS")
        self.assertEqual(timer_alert_command("focus"), "TIMER ALERT FOCUS")
        self.assertEqual(timer_stop_command(), "TIMER STOP")


if __name__ == "__main__":
    unittest.main()
