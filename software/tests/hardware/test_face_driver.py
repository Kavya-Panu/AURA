import threading
import unittest
from hardware.face_driver import FaceDriver, MockCommandSink, CommandSink
from hardware.device_types import CommandPriority

class TestFaceDriver(unittest.TestCase):
    def setUp(self):
        self.sink = MockCommandSink()
        self.face = FaceDriver(self.sink)

    def test_mock_sink_is_command_sink(self):
        self.assertIsInstance(self.sink, CommandSink)

    def test_set_emotion(self):
        self.face.set_emotion("HAPPY")
        self.assertEqual(self.sink.for_device("esp32"), ["HAPPY"])
        self.assertEqual(self.sink.last()[2], CommandPriority.HIGH)

    def test_eyes_clamped(self):
        self.face.look(2.0, -2.0)                # out of range -> clamped
        self.assertEqual(self.sink.for_device("esp32")[-1], "LOOK RIGHT")

    def test_blink(self):
        self.face.blink(3)
        self.assertEqual(self.sink.for_device("esp32")[-1], "DOUBLE_BLINK")

    def test_mouth_is_suppressed_until_firmware_supports_visemes(self):
        before = len(self.sink.commands)
        self.face.set_mouth("MOUTH_WIDE")
        self.assertEqual(len(self.sink.commands), before)

    def test_focus_commands_match_firmware(self):
        self.face.start_focus()
        self.face.stop_focus()
        self.assertEqual(
            self.sink.for_device("esp32")[-2:],
            ["BOOK START", "BOOK STOP"],
        )

    def test_sleep_wake(self):
        self.face.sleep(); self.face.wake()
        cmds = self.sink.for_device("esp32")
        self.assertIn("SLEEP", cmds); self.assertIn("WAKE", cmds)

    def test_boot_shutdown_critical(self):
        self.face.boot()
        self.assertEqual(self.sink.last()[2], CommandPriority.CRITICAL)

    def test_does_not_touch_serial(self):
        import ast, pathlib, hardware.face_driver as m
        mods = {n.module for n in ast.walk(ast.parse(pathlib.Path(m.__file__).read_text()))
                if isinstance(n, ast.ImportFrom) and n.module}
        self.assertNotIn("serial", mods)
        self.assertNotIn("hardware.serial_manager", mods)

    def test_thread_safe(self):
        def worker(i):
            for _ in range(100):
                self.face.set_emotion(f"E{i}")
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(len(self.sink.commands), 600)

if __name__ == "__main__":
    unittest.main()
