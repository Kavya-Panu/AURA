import unittest
from voice.backends import FakeMicrophone
from voice.microphone_manager import MicrophoneManager
from voice.voice_config import MicrophoneConfig
from voice.voice_exceptions import MicrophoneError
from voice.tests._audio import tone_frame

class TestMicManager(unittest.TestCase):
    def test_reads_frames(self):
        mic = FakeMicrophone([tone_frame(160), tone_frame(160)])
        mgr = MicrophoneManager(mic, MicrophoneConfig(), sleep=lambda s: None)
        mgr.open()
        self.assertEqual(len(mgr.read_frame()), 320)

    def test_reconnects_then_succeeds(self):
        # fails after 1 read, then a fresh script after reopen
        mic = FakeMicrophone([tone_frame(160)], fail_after=1)
        errors = []
        mgr = MicrophoneManager(mic, MicrophoneConfig(reconnect_interval_s=0),
                                on_error=errors.append, sleep=lambda s: None)
        mgr.open()
        mgr.read_frame()                 # ok (read #1)
        # reload script so the reopened mic yields data again
        def reopen():
            mic._i = 0; mic.reads = 0; mic._fail_after = None; mic._open = True
        mic.open = reopen
        frame = mgr.read_frame()         # triggers reconnect, then reads
        self.assertEqual(len(frame), 320)
        self.assertTrue(errors)          # reported the disconnect

    def test_gives_up_after_max_attempts(self):
        mic = FakeMicrophone([], fail_after=0)
        mgr = MicrophoneManager(mic, MicrophoneConfig(max_reconnect_attempts=2,
                                                      reconnect_interval_s=0),
                                sleep=lambda s: None)
        mgr.open()
        mic._open = True
        with self.assertRaises(MicrophoneError):
            mgr.read_frame()

if __name__ == "__main__":
    unittest.main()
