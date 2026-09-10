import unittest
from hardware.face_driver import MockCommandSink
from hardware.led_driver import LedDriver, Color, GREEN, OFF

class TestLedDriver(unittest.TestCase):
    def setUp(self):
        self.sink = MockCommandSink()
        self.led = LedDriver(self.sink, sleep=lambda s: None)

    def test_set_color(self):
        self.led.set_color(GREEN)
        self.assertEqual(self.sink.for_device("esp32")[-1], "LED:led:0,255,0")

    def test_brightness_scales(self):
        self.led.set_color(Color(200, 200, 200))
        self.led.set_brightness(0.5)
        self.assertEqual(self.sink.for_device("esp32")[-1], "LED:led:100,100,100")

    def test_color_clamped(self):
        self.led.set_color(Color(300, -5, 999))
        self.assertEqual(self.sink.for_device("esp32")[-1], "LED:led:255,0,255")

    def test_off(self):
        self.led.set_color(GREEN); self.led.off()
        self.assertEqual(self.sink.for_device("esp32")[-1], "LED:led:0,0,0")

    def test_blink_emits_multiple(self):
        self.led.blink(GREEN, times=3, period_s=0.001)
        import time; time.sleep(0.05)
        self.led.stop_effect()
        self.assertGreater(len(self.sink.for_device("esp32")), 2)

    def test_fade_reaches_target(self):
        self.led.set_color(OFF)
        self.led.fade(GREEN, duration_s=0.01, steps=5)
        import time; time.sleep(0.05)
        self.assertEqual(self.led.color, GREEN)

    def test_idle_and_charging_presets(self):
        self.led.idle()
        import time; time.sleep(0.01)
        self.assertTrue(self.sink.for_device("esp32"))
        self.led.charging_indicator()
        time.sleep(0.01)
        self.led.stop_effect()

if __name__ == "__main__":
    unittest.main()
