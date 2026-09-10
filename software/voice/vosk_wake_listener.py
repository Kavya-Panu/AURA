"""Lightweight, offline streaming wake-word listener for ``Hey AURA``.

Vosk runs with a deliberately tiny grammar while AURA is asleep. Whisper and
Qwen are not invoked until the wake phrase has been confirmed. The microphone
is released immediately on detection so the normal high-accuracy listener can
record the user's request.
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from core.logger import get_logger
from .backends import MicrophoneBackend
from .voice_config import AudioConfig
from .voice_exceptions import MicrophoneError

log = get_logger("voice.vosk_wake")

StatusCallback = Callable[[str], None]


@dataclass(frozen=True)
class WakeDetection:
    detected: bool
    transcript: str = ""
    elapsed_s: float = 0.0
    # True when Vosk observed a completed wake-only utterance.  A stable
    # partial means the user may already be continuing with their question,
    # so the live microphone stream must be handed over without interruption.
    phrase_complete: bool = False
    # Audio already consumed while Vosk was deciding that the wake phrase was
    # present.  It can include the beginning—or all—of a one-breath question.
    # The high-accuracy listener feeds this to Whisper before reading new PCM.
    buffered_audio: bytes = b""


class VoskWakeWordListener:
    """Continuously recognize only a small set of ``Hey AURA`` variants."""

    name = "wake_word"
    _GRAMMAR = (
        "hey aura",
        "hey ora",
        "hey or a",
        "hi aura",
        "hi ora",
        "okay aura",
        "ok aura",
        "[unk]",
    )
    _STOP_GRAMMAR = (
        "aura stop",
        "aura shut up",
        "aura keep quiet",
        "ora stop",
        "ora shut up",
        "ora keep quiet",
        "or a stop",
        "or a shut up",
        "or a keep quiet",
        "aura keep quite",
        "ora keep quite",
        "or a keep quite",
        "aura be quiet",
        "ora be quiet",
        "or a be quiet",
        "aura shut",
        "ora shut",
        "or a shut",
        "or stop",
        "or shut up",
        "or keep quiet",
        "or keep quite",
        "[unk]",
    )

    def __init__(
        self,
        audio: AudioConfig,
        microphone: MicrophoneBackend,
        model_path: str | Path,
        status: StatusCallback | None = None,
    ) -> None:
        self._audio = audio
        self._microphone = microphone
        self._model_path = Path(model_path).expanduser().resolve()
        self._status = status or (lambda _message: None)
        self._model = None
        self._recognizer_type = None
        self._loaded = False
        self._stop = threading.Event()

    def initialize(self) -> None:
        if not self._model_path.exists():
            raise RuntimeError(
                f"Vosk wake-word model is missing: {self._model_path}"
            )
        try:
            from vosk import KaldiRecognizer, Model, SetLogLevel
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "Vosk is not installed. Run INSTALL_PYTHON.bat again."
            ) from exc

        SetLogLevel(-1)
        self._status("Loading the offline 'Hey AURA' wake-word model...")
        self._model = Model(str(self._model_path))
        self._recognizer_type = KaldiRecognizer
        self._loaded = True
        self._status("Wake-word listener is ready.")

    def start(self) -> None:
        self._stop.clear()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._microphone.close()
        except Exception:  # noqa: BLE001
            pass

    def health_check(self) -> bool:
        return self._loaded

    def wait(self, timeout_s: float | None = None) -> WakeDetection:
        """Block until ``Hey AURA`` is detected or an optional timeout ends."""
        if not self._loaded or self._model is None or self._recognizer_type is None:
            raise RuntimeError("wake-word listener has not been initialized")

        recognizer = self._recognizer_type(
            self._model,
            self._audio.sample_rate,
            json.dumps(self._GRAMMAR),
        )
        recognizer.SetWords(True)
        started = time.monotonic()
        deadline = None if timeout_s is None else started + max(0.1, timeout_s)
        previous_match = ""
        stable_hits = 0
        handoff_microphone = False
        utterance_audio = bytearray()
        max_audio_bytes = self._audio.sample_rate * 2 * 12

        try:
            self._microphone.open()
            # Discard a short transport/startup tail left by the previous mode.
            for _ in range(max(1, int(0.12 * 1000 / self._audio.frame_ms))):
                self._microphone.read_frame()
            self._status("Waiting for 'Hey AURA'...")

            while not self._stop.is_set():
                if deadline is not None and time.monotonic() >= deadline:
                    break
                frame = self._microphone.read_frame()
                if not frame:
                    continue

                utterance_audio.extend(frame)
                if len(utterance_audio) > max_audio_bytes:
                    del utterance_audio[:-max_audio_bytes]

                complete = bool(recognizer.AcceptWaveform(frame))
                payload = recognizer.Result() if complete else recognizer.PartialResult()
                text = self._extract_text(payload, complete)
                if not self._contains_wake_phrase(text):
                    previous_match = ""
                    stable_hits = 0
                    # A final non-wake result marks the end of an unrelated
                    # utterance. Do not carry that old speech into a later
                    # genuine AURA request.
                    if complete:
                        utterance_audio.clear()
                    continue

                normalized = self._normalize(text)
                if normalized == previous_match:
                    stable_hits += 1
                else:
                    previous_match = normalized
                    stable_hits = 1

                # Final recognition fires immediately; stable partials make the
                # wake response feel prompt without accepting a one-frame glitch.
                if complete or stable_hits >= 2:
                    elapsed = time.monotonic() - started
                    log.info("wake phrase detected: %r", text)
                    # Keep the microphone stream open. PushToTalkListener takes
                    # ownership immediately and consumes any question audio
                    # already queued after the wake phrase. This supports the
                    # natural one-breath form: "Hi AURA, what is Ohm's law?"
                    handoff_microphone = True
                    return WakeDetection(
                        True,
                        text,
                        elapsed,
                        phrase_complete=complete,
                        buffered_audio=bytes(utterance_audio),
                    )
        except MicrophoneError:
            raise
        finally:
            if not handoff_microphone:
                self._microphone.close()

        return WakeDetection(False, "", time.monotonic() - started)

    def wait_for_stop(
        self,
        cancel_event: threading.Event,
        timeout_s: float | None = None,
    ) -> WakeDetection:
        """Listen only for AURA's explicit stop phrases.

        This lightweight grammar runs while the brain is thinking and while the
        robot speaker is active. It never sends ordinary room speech to Qwen.
        The caller can end the monitor through ``cancel_event``.
        """
        if not self._loaded or self._model is None or self._recognizer_type is None:
            raise RuntimeError("wake-word listener has not been initialized")

        recognizer = self._recognizer_type(
            self._model,
            self._audio.sample_rate,
            json.dumps(self._STOP_GRAMMAR),
        )
        recognizer.SetWords(True)
        started = time.monotonic()
        deadline = None if timeout_s is None else started + max(0.1, timeout_s)
        previous_match = ""
        stable_hits = 0

        try:
            self._microphone.open()
            # Clear only the codec/transport transition tail. Keep this short
            # so a stop command spoken as AURA begins answering is not clipped.
            for _ in range(max(1, int(0.06 * 1000 / self._audio.frame_ms))):
                self._microphone.read_frame()

            while not self._stop.is_set() and not cancel_event.is_set():
                if deadline is not None and time.monotonic() >= deadline:
                    break
                frame = self._microphone.read_frame()
                if not frame:
                    continue

                complete = bool(recognizer.AcceptWaveform(frame))
                payload = recognizer.Result() if complete else recognizer.PartialResult()
                text = self._extract_text(payload, complete)
                if not self._contains_stop_phrase(text):
                    previous_match = ""
                    stable_hits = 0
                    continue

                normalized = self._normalize(text)
                if normalized == previous_match:
                    stable_hits += 1
                else:
                    previous_match = normalized
                    stable_hits = 1

                if complete or stable_hits >= 2:
                    elapsed = time.monotonic() - started
                    log.info("stop phrase detected: %r", text)
                    return WakeDetection(True, text, elapsed)
        except MicrophoneError:
            if not cancel_event.is_set():
                raise
        finally:
            self._microphone.close()

        return WakeDetection(False, "", time.monotonic() - started)

    @staticmethod
    def _extract_text(payload: str, complete: bool) -> str:
        try:
            value = json.loads(payload or "{}")
        except json.JSONDecodeError:
            return ""
        key = "text" if complete else "partial"
        return str(value.get(key) or "").strip()

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"[^a-z]+", " ", (text or "").lower()).strip()

    @classmethod
    def _contains_wake_phrase(cls, text: str) -> bool:
        normalized = f" {cls._normalize(text)} "
        return any(
            f" {phrase} " in normalized
            for phrase in (
                "hey aura",
                "hey ora",
                "hey or a",
                "hi aura",
                "hi ora",
                "okay aura",
                "ok aura",
            )
        )

    @classmethod
    def _contains_stop_phrase(cls, text: str) -> bool:
        normalized = cls._normalize(text)
        return normalized in {
            "aura stop",
            "aura shut up",
            "aura keep quiet",
            "ora stop",
            "ora shut up",
            "ora keep quiet",
            "or a stop",
            "or a shut up",
            "or a keep quiet",
            "aura keep quite",
            "ora keep quite",
            "or a keep quite",
            "aura be quiet",
            "ora be quiet",
            "or a be quiet",
            "aura shut",
            "ora shut",
            "or a shut",
            "or stop",
            "or shut up",
            "or keep quiet",
            "or keep quite",
        }
