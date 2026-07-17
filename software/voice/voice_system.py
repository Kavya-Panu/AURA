"""
voice/voice_system.py
=====================
The Voice System module. Ties together mic -> (wake word) -> VAD/endpointing ->
STT and PUBLISHES results on the Event Bus. It listens; it never decides. It
implements the core `Module` protocol (initialize/start/stop/health_check) so
the LifecycleManager owns it like any other module.

State machine per capture loop:
    IDLE ── wake word ──► LISTENING ── endpoint ──► RECOGNIZING ──► publish
      ▲                                                              │
      └──────────────────────────────────────────────────────────◄─┘

Continuous modes (TRANSLATION/QUIZ) set require_wake_word=False so every
endpointed utterance is transcribed without a wake word (the spec's continuous
behaviour); an explicit wake word still works.

Threading: one capture thread runs the loop; the bus delivers events to
subscribers. All backend calls happen on that single thread, so backends can be
simple and synchronous.
"""
from __future__ import annotations

import threading
from enum import Enum, auto

from core.event_bus import EventBus
from core.logger import get_logger
from . import voice_events as ev
from .backends import MicrophoneBackend, STTBackend
from .microphone_manager import MicrophoneManager
from .noise_filter import NoiseFilter
from .speech_recognizer import SpeechRecognizer
from .vad import Endpointer, VADBackend
from .voice_config import VoiceConfig
from .voice_exceptions import MicrophoneError
from .wake_word import WakeWordBackend, WakeWordDetector

log = get_logger("voice.system")


class VoiceState(Enum):
    IDLE = auto()          # waiting for wake word
    LISTENING = auto()     # capturing an utterance
    RECOGNIZING = auto()   # running STT


class VoiceSystem:
    """Audio capture + recognition, publishing to the Event Bus."""

    name = "voice"

    def __init__(self,
                 event_bus: EventBus,
                 config: VoiceConfig,
                 microphone: MicrophoneBackend,
                 stt: STTBackend,
                 wake_backend: WakeWordBackend | None = None,
                 vad_backend: VADBackend | None = None) -> None:
        self._bus = event_bus
        self._cfg = config
        self._mic = MicrophoneManager(microphone, config.microphone,
                                      on_error=self._emit_mic_error)
        self._recognizer = SpeechRecognizer(
            config, stt,
            noise=NoiseFilter(config.audio, config.noise),
        )
        self._wake = WakeWordDetector(config.wake_word, wake_backend)
        self._endpointer = Endpointer(config.audio, config.vad, vad_backend)

        self._state = VoiceState.IDLE
        self._require_wake = config.require_wake_word
        self._lock = threading.RLock()
        self._running = threading.Event()
        self._thread: threading.Thread | None = None

    # ---------------------------------------------------------- Module API
    def initialize(self) -> None:
        """Load the STT model and open the microphone (fail fast if unavailable)."""
        self._recognizer.load()
        self._mic.open()
        log.info("voice initialised")

    def start(self) -> None:
        if self._running.is_set():
            return
        self._running.set()
        self._thread = threading.Thread(target=self._loop, name="voice-capture",
                                        daemon=True)
        self._thread.start()
        self._bus.emit(ev.VOICE_STARTED, {}, source=self.name)

    def stop(self) -> None:
        if not self._running.is_set():
            self._mic.close()
            return
        self._running.clear()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._mic.close()
        self._bus.emit(ev.VOICE_STOPPED, {}, source=self.name)

    def health_check(self) -> bool:
        return self._running.is_set() and self._mic.is_open()

    # ---------------------------------------------------- runtime controls
    def set_require_wake_word(self, required: bool) -> None:
        """Continuous modes call this: False = transcribe every utterance."""
        with self._lock:
            self._require_wake = required
        log.debug("require_wake_word = %s", required)

    @property
    def state(self) -> VoiceState:
        with self._lock:
            return self._state

    # --------------------------------------------------------- capture loop
    def _loop(self) -> None:
        while self._running.is_set():
            try:
                frame = self._mic.read_frame()
            except MicrophoneError:
                self._emit_mic_error("microphone permanently unavailable")
                break
            if not frame:
                continue
            self._process_frame(frame)

    def _process_frame(self, frame: bytes) -> None:
        with self._lock:
            state = self._state
            require_wake = self._require_wake

        if state is VoiceState.IDLE:
            if require_wake:
                if not self._wake.process_frame(frame):
                    return
                self._fire_wake()
            # Whether woken or wake-free, begin listening from this frame.
            self._set_state(VoiceState.LISTENING)
            self._bus.emit(ev.SPEECH_STARTED, {}, source=self.name)
            self._endpointer.reset()
            # fall through to feed this frame into the endpointer

        # LISTENING: feed frames until an utterance completes.
        utterance = self._endpointer.process(frame)
        if utterance is not None:
            self._bus.emit(ev.SPEECH_FINISHED, {}, source=self.name)
            self._recognize_and_publish(utterance)
            self._set_state(VoiceState.IDLE)

    def _recognize_and_publish(self, pcm: bytes) -> None:
        self._set_state(VoiceState.RECOGNIZING)
        result = self._recognizer.recognize(pcm)
        if result.is_empty:
            self._bus.emit(ev.NO_SPEECH_DETECTED, {}, source=self.name)
            return
        self._bus.emit(ev.LANGUAGE_DETECTED,
                       {"language": result.language,
                        "confidence": result.confidence}, source=self.name)
        # THE key output the Intent Engine consumes:
        self._bus.emit(ev.TEXT_RECOGNIZED,
                       {"text": result.text,
                        "language": result.language,
                        "confidence": result.confidence,
                        "duration_s": round(result.duration_s, 3)},
                       source=self.name)
        log.info("recognised: %r (%s, %.2f)", result.text,
                 result.language, result.confidence)

    # ------------------------------------------------------------ helpers
    def _fire_wake(self) -> None:
        self._bus.emit(ev.WAKE_WORD_DETECTED, {}, source=self.name)

    def _set_state(self, state: VoiceState) -> None:
        with self._lock:
            self._state = state

    def _emit_mic_error(self, message: str) -> None:
        log.warning("microphone error: %s", message)
        self._bus.emit(ev.MICROPHONE_ERROR, {"message": message},
                       source=self.name)

    # ---------------------------------------- test / manual drive helper
    def feed_frame_for_test(self, frame: bytes) -> None:
        """Drive one frame synchronously (used by tests without the thread)."""
        self._process_frame(frame)
