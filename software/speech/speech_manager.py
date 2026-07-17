"""
speech/speech_manager.py
========================
The Speech Manager - AURA's expression layer. It EXPRESSES BrainManager
responses: choose a voice profile + face emotion, set a stable expression, run
mouth animation, synthesize, and play - all on a background worker so the robot
never blocks. It implements the core Module protocol so the LifecycleManager
owns it.

It never generates answers, calls an LLM, does speech recognition, changes modes,
or makes decisions. It integrates by:
  * subscribing to ANSWER_READY (from the Brain) and speaking the text, and
  * publishing SPEECH_STARTED/FINISHED/CANCELLED, TTS_STARTED/FINISHED,
    VOICE_CHANGED, EXPRESSION_CHANGED, MOUTH_ANIMATION_STARTED/STOPPED,
  * sending face emotions via the existing EMOTION_CHANGED event.
It modifies no existing module.

Threading: a single speak-worker thread consumes the priority SpeechQueue, so
synthesis, playback, expression and mouth animation are serialized per-utterance
and thread-safe. Priority items can interrupt the current utterance.
"""
from __future__ import annotations

import threading
import time
from typing import Callable

from core.event_bus import Event, EventBus
from core.logger import get_logger

from . import speech_events as ev
from .audio_player import AudioPlayer
from .emotion_mapper import EmotionMapper
from .expression_manager import ExpressionManager
from .mouth_animation import MouthAnimator
from .speech_config import SpeechConfig
from .speech_context import SpeechContext, SpeechState
from .speech_exceptions import SpeechError, TTSError, TTSUnavailable
from .speech_queue import SpeechItem, SpeechQueue
from .speech_result import SpeechResult
from .timing_controller import TimingController
from .tts_manager import TTSManager
from .voice_profiles import VoiceProfileRegistry

log = get_logger("speech.manager")


class SpeechManager:
    """Turns text (from the Brain) into expressive, spoken output."""

    name = "speech"

    def __init__(self, event_bus: EventBus, config: SpeechConfig,
                 tts: TTSManager, audio_player: AudioPlayer,
                 profiles: VoiceProfileRegistry | None = None,
                 emotion_mapper: EmotionMapper | None = None,
                 expression: ExpressionManager | None = None,
                 mouth: MouthAnimator | None = None,
                 timing: TimingController | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._bus = event_bus
        self._cfg = config
        self._tts = tts
        self._player = audio_player
        self._profiles = profiles or VoiceProfileRegistry()
        self._mapper = emotion_mapper or EmotionMapper(config.default_profile)
        self._expression = expression or ExpressionManager(event_bus, config.expression)
        self._mouth = mouth or MouthAnimator(event_bus, config.mouth)
        self._timing = timing or TimingController(config.timing)
        self._ctx = SpeechContext()
        self._clock = clock

        self._queue = SpeechQueue(config.max_queue)
        self._running = threading.Event()
        self._worker: threading.Thread | None = None
        self._current_profile = config.default_profile
        self._sub_id: int | None = None

    # =====================================================================
    #  Module protocol
    # =====================================================================
    def initialize(self) -> None:
        engine = self._tts.available_engine()
        if engine is not None:
            self._ctx.set_provider(engine.name)
        log.info("speech initialised (engines: %s)",
                 ", ".join(self._tts.engine_names()) or "none")

    def start(self) -> None:
        if self._running.is_set():
            return
        self._running.set()
        self._worker = threading.Thread(target=self._run, name="speech-worker",
                                        daemon=True)
        self._worker.start()
        if self._sub_id is None:
            self._sub_id = self._bus.subscribe(ev.ANSWER_READY, self._on_answer,
                                               priority=50)
        log.info("speech started")

    def stop(self) -> None:
        self._running.clear()
        self._player.stop()
        self._mouth.stop()
        if self._sub_id is not None:
            self._bus.unsubscribe(self._sub_id)
            self._sub_id = None
        if self._worker is not None:
            self._queue.put("", priority=0)   # wake the worker so it can exit
            self._worker.join(timeout=2.0)
            self._worker = None
        log.info("speech stopped")

    def health_check(self) -> bool:
        return self._running.is_set() and (
            self._worker is not None and self._worker.is_alive())

    # =====================================================================
    #  Public API
    # =====================================================================
    def say(self, text: str, *, mode: str | None = None,
            emotion_hint: str | None = None, priority: int = 100,
            interrupt: bool = False) -> bool:
        """Queue an utterance. Returns False if the queue is full. Higher
        priority (lower number) speaks sooner; `interrupt` stops the current
        utterance first."""
        if not text or not text.strip():
            return False
        if interrupt:
            self._player.stop()
            self._mouth.stop()
        ok = self._queue.put(text.strip(), priority=priority, mode=mode,
                             emotion_hint=emotion_hint, interrupt=interrupt)
        self._ctx.set_queue_length(len(self._queue))
        return ok

    def cancel_all(self) -> int:
        """Cancel the current utterance and clear the queue."""
        self._ctx.set_state(SpeechState.CANCELLING)
        self._player.stop()
        self._mouth.stop()
        removed = self._queue.clear()
        self._ctx.set_queue_length(0)
        self._bus.emit(ev.SPEECH_CANCELLED, {"cleared": removed}, source=self.name)
        self._ctx.set_state(SpeechState.IDLE)
        return removed

    def set_volume(self, volume: float) -> None:
        self._player.set_volume(volume)

    @property
    def context(self) -> SpeechContext:
        return self._ctx

    @property
    def queue_length(self) -> int:
        return len(self._queue)

    # =====================================================================
    #  Worker: consume the queue, speak one utterance at a time
    # =====================================================================
    def _run(self) -> None:
        while self._running.is_set():
            item = self._queue.get(timeout=0.2)
            if item is None:
                continue
            if not self._running.is_set():
                break
            if not item.text:                 # wake-up sentinel
                continue
            try:
                self._speak_item(item)
            except SpeechError as exc:
                log.warning("speech failed: %s", exc)
                self._bus.emit(ev.SPEECH_FINISHED,
                               {"success": False, "error": str(exc)},
                               source=self.name)
            finally:
                self._ctx.set_queue_length(len(self._queue))

    def _speak_item(self, item: SpeechItem) -> SpeechResult:
        # 1) choose style (emotion token + voice profile)
        style = self._mapper.map(item.text, mode=item.mode,
                                 hint_emotion=item.emotion_hint)
        profile = self._resolve_profile(style.profile)
        self._announce_voice(profile.name)
        self._ctx.set_style(style.emotion, profile.name)

        # 2) thinking pause + stable expression
        self._ctx.set_state(SpeechState.THINKING)
        self._timing.thinking_pause()
        if self._cfg.enable_expressions:
            self._expression.set_expression(style.emotion)

        # 3) synthesize
        self._bus.emit(ev.TTS_STARTED, {"engine_pref": self._cfg.default_engine},
                       source=self.name)
        try:
            synth = self._tts.synthesize(item.text, profile)
        except (TTSError, TTSUnavailable) as exc:
            self._bus.emit(ev.TTS_FINISHED, {"success": False}, source=self.name)
            return SpeechResult.failure(str(exc), item.text)
        self._ctx.set_provider(synth.engine)
        self._bus.emit(ev.TTS_FINISHED,
                       {"success": True, "engine": synth.engine,
                        "duration_s": round(synth.duration_s, 3)}, source=self.name)

        # 4) speak: start mouth animation + play audio together
        self._ctx.set_state(SpeechState.SPEAKING)
        self._ctx.mark_speaking(synth.duration_s)
        self._timing.pre_speech_delay()
        self._bus.emit(ev.SPEECH_STARTED,
                       {"text": item.text, "emotion": style.emotion,
                        "profile": profile.name, "engine": synth.engine,
                        "duration_s": round(synth.duration_s, 3)},
                       source=self.name)
        if self._cfg.enable_mouth_animation:
            self._mouth.start(item.text, synth.duration_s)

        completed = self._player.play(synth.audio, synth.duration_s)

        self._mouth.stop()
        self._timing.post_speech_delay()
        self._ctx.set_state(SpeechState.IDLE)

        if not completed:
            self._bus.emit(ev.SPEECH_CANCELLED, {"text": item.text}, source=self.name)
            return SpeechResult.cancelled_result(item.text)

        self._bus.emit(ev.SPEECH_FINISHED,
                       {"success": True, "text": item.text,
                        "emotion": style.emotion}, source=self.name)
        return SpeechResult(text=item.text, emotion=style.emotion,
                            profile=profile.name, engine=synth.engine,
                            duration_s=synth.duration_s, spoken=True)

    # =====================================================================
    #  Bus integration: speak Brain answers
    # =====================================================================
    def _on_answer(self, event: Event) -> None:
        text = event.data.get("text", "")
        if not text or not event.data.get("success", True):
            return
        mode = event.data.get("mode")
        self.say(text, mode=mode)

    # =====================================================================
    #  Helpers
    # =====================================================================
    def _resolve_profile(self, name: str):
        if self._profiles.has(name):
            return self._profiles.get(name)
        return self._profiles.get(self._cfg.default_profile)

    def _announce_voice(self, profile_name: str) -> None:
        if profile_name != self._current_profile:
            self._current_profile = profile_name
            self._bus.emit(ev.VOICE_CHANGED, {"profile": profile_name},
                           source=self.name)
