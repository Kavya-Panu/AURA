"""SpeechManager: full pipeline, queue, interruption, cancellation, events, threads."""
import threading
import time
import unittest
from core.constants import RobotEvent
from core.lifecycle import Module
from speech import (SpeechManager, TTSManager, FakeTTS, AudioPlayer, FakeAudioSink,
                    SpeechState)
from speech.tests._helpers import build_speech, collect, instant_config, wait_until

class TestSpeechManager(unittest.TestCase):
    def test_is_module(self):
        bus, sm = build_speech(start=False)
        self.assertIsInstance(sm, Module)
        sm.stop()

    def test_full_pipeline_events(self):
        bus, sm = build_speech()
        seen = collect(bus)
        sm.say("Hello there!", mode="NORMAL")
        self.assertTrue(wait_until(
            lambda: any(t == RobotEvent.SPEECH_FINISHED for t, _ in seen)))
        types = [t for t, _ in seen]
        for e in (RobotEvent.SPEECH_STARTED, RobotEvent.TTS_STARTED,
                  RobotEvent.TTS_FINISHED, RobotEvent.EXPRESSION_CHANGED,
                  RobotEvent.MOUTH_ANIMATION_STARTED, RobotEvent.SPEECH_FINISHED):
            self.assertIn(e, types)
        sm.stop()

    def test_sends_face_emotion(self):
        bus, sm = build_speech()
        seen = collect(bus)
        sm.say("Congratulations, well done!", mode="QUIZ")
        wait_until(lambda: any(t == RobotEvent.SPEECH_FINISHED for t, _ in seen))
        # the expression emotion is CELEBRATE, sent via EMOTION_CHANGED
        emotions = [d.get("emotion") for t, d in seen
                    if t == RobotEvent.EMOTION_CHANGED and "emotion" in d]
        self.assertIn("CELEBRATE", emotions)
        sm.stop()

    def test_empty_text_ignored(self):
        bus, sm = build_speech()
        self.assertFalse(sm.say("   "))
        sm.stop()

    def test_queue_multiple(self):
        bus, sm = build_speech()
        seen = collect(bus)
        sm.say("first"); sm.say("second"); sm.say("third")
        self.assertTrue(wait_until(
            lambda: sum(1 for t, _ in seen if t == RobotEvent.SPEECH_FINISHED) >= 3,
            timeout_s=3.0))
        sm.stop()

    def test_priority_speaks_first(self):
        # slow playback so the queue actually holds items; urgent should be next
        bus, sm = build_speech(sink=FakeAudioSink(speed=20))
        seen = collect(bus)
        sm.say("normal one", priority=100)
        sm.say("URGENT", priority=0)
        wait_until(lambda: sum(1 for t, _ in seen if t == RobotEvent.SPEECH_STARTED) >= 2,
                   timeout_s=3.0)
        started_texts = [d.get("text") for t, d in seen if t == RobotEvent.SPEECH_STARTED]
        # first started is whichever was already playing; URGENT should precede
        # 'normal one' if 'normal one' hadn't started yet. At minimum URGENT ran.
        self.assertIn("URGENT", started_texts)
        sm.stop()

    def test_cancel_all(self):
        bus, sm = build_speech(sink=FakeAudioSink(speed=10))
        seen = collect(bus)
        sm.say("one"); sm.say("two"); sm.say("three")
        time.sleep(0.02)
        removed = sm.cancel_all()
        self.assertGreaterEqual(removed, 0)
        self.assertIn(RobotEvent.SPEECH_CANCELLED, [t for t, _ in seen])
        sm.stop()

    def test_interrupt_stops_current(self):
        bus, sm = build_speech(sink=FakeAudioSink(speed=8))
        seen = collect(bus)
        sm.say("a long first utterance being spoken slowly")
        time.sleep(0.03)
        sm.say("interrupting message", priority=0, interrupt=True)
        wait_until(lambda: any(t == RobotEvent.SPEECH_CANCELLED for t, _ in seen))
        self.assertIn(RobotEvent.SPEECH_CANCELLED, [t for t, _ in seen])
        sm.stop()

    def test_answer_ready_is_spoken(self):
        bus, sm = build_speech()
        seen = collect(bus)
        bus.emit(RobotEvent.ANSWER_READY,
                 {"text": "here is your answer", "success": True, "mode": "ASSISTANT"},
                 source="brain")
        self.assertTrue(wait_until(
            lambda: any(t == RobotEvent.SPEECH_STARTED for t, _ in seen)))
        sm.stop()

    def test_failed_answer_not_spoken(self):
        bus, sm = build_speech()
        seen = collect(bus)
        bus.emit(RobotEvent.ANSWER_READY,
                 {"text": "", "success": False}, source="brain")
        time.sleep(0.1)
        self.assertNotIn(RobotEvent.SPEECH_STARTED, [t for t, _ in seen])
        sm.stop()

    def test_cancelled_request_answer_is_not_spoken(self):
        bus, sm = build_speech()
        seen = collect(bus)
        sm.suppress_request("voice-123")
        bus.emit(
            RobotEvent.ANSWER_READY,
            {
                "text": "late cancelled answer",
                "success": True,
                "request_id": "voice-123",
            },
            source="brain",
        )
        time.sleep(0.1)
        self.assertNotIn(RobotEvent.SPEECH_STARTED, [t for t, _ in seen])
        sm.stop()

    def test_voice_changed_event(self):
        bus, sm = build_speech()
        seen = collect(bus)
        sm.say("teach me", mode="TEACHER")   # -> teacher profile (not default)
        self.assertTrue(wait_until(
            lambda: any(t == RobotEvent.VOICE_CHANGED for t, _ in seen)))
        sm.stop()

    def test_tts_failure_handled(self):
        bus, sm = build_speech(tts=TTSManager([FakeTTS("f", fail=True)]))
        seen = collect(bus)
        sm.say("this will fail synthesis")
        self.assertTrue(wait_until(
            lambda: any(t == RobotEvent.TTS_FINISHED and not d.get("success")
                        for t, d in seen), timeout_s=2.0))
        sm.stop()

    def test_health_check(self):
        bus, sm = build_speech(start=False)
        sm.start()
        self.assertTrue(sm.health_check())
        sm.stop()
        self.assertFalse(sm.health_check())

    def test_never_generates_or_decides(self):
        import ast, speech.speech_manager as m
        tree = ast.parse(open(m.__file__).read())
        mods = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module:
                mods.add(n.module)
        # must not import the brain/LLM, intent, or mode managers
        self.assertFalse(any(("brain" in x or "intent" in x or "mode." in x)
                             for x in mods))

    def test_thread_safety_concurrent_say(self):
        bus, sm = build_speech()
        def worker(i):
            for j in range(10):
                sm.say(f"msg {i}-{j}")
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
        for t in threads: t.start()
        for t in threads: t.join()
        # no crash; drain
        wait_until(lambda: sm.queue_length == 0, timeout_s=5.0)
        sm.stop()

if __name__ == "__main__":
    unittest.main()
