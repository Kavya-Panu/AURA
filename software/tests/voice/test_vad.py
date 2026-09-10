import unittest
from voice.vad import Endpointer, EnergyVAD
from voice.voice_config import AudioConfig, VADConfig
from voice.tests._audio import tone_frame, silence_frame

class TestVAD(unittest.TestCase):
    def setUp(self):
        self.audio = AudioConfig(frame_ms=20)      # 320 samples/frame @16k
        self.n = self.audio.frame_samples
        self.cfg = VADConfig(
            start_frames=3, silence_timeout_s=0.1,
            short_silence_timeout_s=0.1, long_silence_timeout_s=0.1,
            pre_roll_ms=40, max_utterance_s=5.0, min_speech_s=0.0,
        )
        self.ep = Endpointer(self.audio, self.cfg)

    def test_energy_vad_discriminates(self):
        vad = EnergyVAD(2)
        self.assertTrue(vad.is_speech(tone_frame(self.n), 16000))
        # feed some silence to settle the floor, then test
        for _ in range(5):
            vad.is_speech(silence_frame(self.n), 16000)
        self.assertFalse(vad.is_speech(silence_frame(self.n), 16000))

    def test_endpoints_an_utterance(self):
        out = None
        # 10 speech frames then enough silence (>0.1s = >5 frames of 20ms)
        for f in [tone_frame(self.n)] * 10 + [silence_frame(self.n)] * 8:
            r = self.ep.process(f)
            if r is not None:
                out = r
        self.assertIsNotNone(out)
        # utterance includes pre-roll + speech, so >= 10 frames of bytes
        self.assertGreaterEqual(len(out), 10 * self.n * 2)

    def test_no_output_during_silence(self):
        for f in [silence_frame(self.n)] * 20:
            self.assertIsNone(self.ep.process(f))

    def test_max_utterance_cap(self):
        cfg = VADConfig(
            start_frames=1, silence_timeout_s=99,
            short_silence_timeout_s=99, long_silence_timeout_s=99,
            max_utterance_s=0.1, min_speech_s=0.0,
        )  # 5 frames @20ms
        ep = Endpointer(self.audio, cfg)
        out = None
        for f in [tone_frame(self.n)] * 20:
            r = ep.process(f)
            if r is not None:
                out = r; break
        self.assertIsNotNone(out)

if __name__ == "__main__":
    unittest.main()
