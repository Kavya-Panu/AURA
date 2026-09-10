import threading
import unittest
from speech.audio_player import AudioPlayer, FakeAudioSink

class TestAudioPlayer(unittest.TestCase):
    def test_plays_to_completion(self):
        sink = FakeAudioSink(speed=1000)
        p = AudioPlayer(sink)
        self.assertTrue(p.play("clip", 0.1))
        self.assertEqual(sink.played, ["clip"])

    def test_stop_interrupts(self):
        sink = FakeAudioSink(speed=5)     # slow enough to interrupt
        p = AudioPlayer(sink)
        result = {}
        def play():
            result["completed"] = p.play("clip", 2.0)
        t = threading.Thread(target=play); t.start()
        import time; time.sleep(0.02)
        p.stop()
        t.join()
        self.assertFalse(result["completed"])       # interrupted

    def test_volume_control(self):
        sink = FakeAudioSink()
        p = AudioPlayer(sink)
        p.set_volume(0.5)
        self.assertEqual(sink.volume, 0.5)
        p.set_volume(2.0)                            # clamped
        self.assertEqual(sink.volume, 1.0)

    def test_is_playing_flag(self):
        sink = FakeAudioSink(speed=1000)
        p = AudioPlayer(sink)
        self.assertFalse(p.is_playing)
        p.play("clip", 0.05)
        self.assertFalse(p.is_playing)              # done after play returns

if __name__ == "__main__":
    unittest.main()
