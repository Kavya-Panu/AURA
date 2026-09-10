"""End-to-end pipeline with fakes: frames -> wake -> endpoint -> STT -> bus."""
import unittest
from core.event_bus import EventBus
from core.constants import RobotEvent
from voice.backends import FakeMicrophone, FakeSTT
from voice.wake_word import FakeWakeWord
from voice.factory import build_fake_voice_system
from voice.voice_config import VoiceConfig, VADConfig
from voice.voice_system import VoiceState
from voice.tests._audio import tone_frame, silence_frame

def make(require_wake=True, wake_scores=None):
    bus = EventBus()
    cfg = VoiceConfig()
    cfg.require_wake_word = require_wake
    cfg.vad = VADConfig(start_frames=2, silence_timeout_s=0.06,
                        pre_roll_ms=20, max_utterance_s=5.0)
    mic = FakeMicrophone(); stt = FakeSTT()
    vs = build_fake_voice_system(bus, cfg, mic=mic, stt=stt)
    # inject a wake backend
    from voice.wake_word import WakeWordDetector
    vs._wake = WakeWordDetector(cfg.wake_word,
                                FakeWakeWord(wake_scores or []))
    vs.initialize()
    events = []
    bus.subscribe_all(lambda e: events.append((e.type, e.data)))
    return bus, cfg, mic, stt, vs, events

N = VoiceConfig().audio.frame_samples

class TestVoiceSystem(unittest.TestCase):
    def test_full_pipeline_with_wake_word(self):
        bus, cfg, mic, stt, vs, events = make(
            require_wake=True, wake_scores=[0.9])   # first frame wakes
        stt.queue("aura start focus", "en", 0.96)
        # frame 1 wakes + starts listening; then speech; then silence to end
        vs.feed_frame_for_test(tone_frame(N))               # wake -> LISTENING
        for _ in range(4):
            vs.feed_frame_for_test(tone_frame(N))            # speech
        for _ in range(6):
            vs.feed_frame_for_test(silence_frame(N))         # end
        types = [t for t, _ in events]
        self.assertIn(RobotEvent.WAKE_WORD_DETECTED, types)
        self.assertIn(RobotEvent.SPEECH_STARTED, types)
        self.assertIn(RobotEvent.SPEECH_FINISHED, types)
        self.assertIn(RobotEvent.TEXT_RECOGNIZED, types)
        # the recognised text is the Intent Engine's input
        payload = next(d for t, d in events if t == RobotEvent.TEXT_RECOGNIZED)
        self.assertEqual(payload["text"], "aura start focus")
        self.assertEqual(vs.state, VoiceState.IDLE)          # back to idle

    def test_no_wake_word_no_recognition(self):
        bus, cfg, mic, stt, vs, events = make(
            require_wake=True, wake_scores=[0.1, 0.1, 0.1])
        stt.queue("should not be used")
        for _ in range(5):
            vs.feed_frame_for_test(tone_frame(N))
        types = [t for t, _ in events]
        self.assertNotIn(RobotEvent.TEXT_RECOGNIZED, types)
        self.assertNotIn(RobotEvent.WAKE_WORD_DETECTED, types)

    def test_continuous_mode_skips_wake_word(self):
        bus, cfg, mic, stt, vs, events = make(require_wake=True)
        vs.set_require_wake_word(False)                      # TRANSLATION/QUIZ
        stt.queue("hello world", "en", 0.9)
        vs.feed_frame_for_test(tone_frame(N))                # starts listening
        for _ in range(4):
            vs.feed_frame_for_test(tone_frame(N))
        for _ in range(6):
            vs.feed_frame_for_test(silence_frame(N))
        types = [t for t, _ in events]
        self.assertIn(RobotEvent.TEXT_RECOGNIZED, types)
        self.assertNotIn(RobotEvent.WAKE_WORD_DETECTED, types)

    def test_empty_transcript_emits_no_speech(self):
        bus, cfg, mic, stt, vs, events = make(require_wake=False)
        # no transcript queued -> FakeSTT returns empty
        vs.feed_frame_for_test(tone_frame(N))
        for _ in range(4):
            vs.feed_frame_for_test(tone_frame(N))
        for _ in range(6):
            vs.feed_frame_for_test(silence_frame(N))
        types = [t for t, _ in events]
        self.assertIn(RobotEvent.NO_SPEECH_DETECTED, types)
        self.assertNotIn(RobotEvent.TEXT_RECOGNIZED, types)

    def test_language_event_emitted(self):
        bus, cfg, mic, stt, vs, events = make(require_wake=False)
        stt.queue("bonjour", "fr", 0.88)
        vs.feed_frame_for_test(tone_frame(N))
        for _ in range(4): vs.feed_frame_for_test(tone_frame(N))
        for _ in range(6): vs.feed_frame_for_test(silence_frame(N))
        lang = next((d for t, d in events if t == RobotEvent.LANGUAGE_DETECTED), None)
        self.assertIsNotNone(lang)
        self.assertEqual(lang["language"], "fr")

if __name__ == "__main__":
    unittest.main()
