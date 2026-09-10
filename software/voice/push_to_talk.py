"""
voice/push_to_talk.py
=====================
Reliable first-stage voice input for AURA.

The user presses Enter (or types /listen), speaks one question, and stops
talking. The listener records until trailing silence, transcribes locally with
faster-whisper, and returns recognised text.

This mode deliberately opens the microphone only while the user is speaking.
That prevents AURA's own TTS output from being captured and re-submitted.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from core.logger import get_logger

from .backends import MicrophoneBackend, SoundDeviceMicrophone, WhisperSTT
from .audio_utils import rms
from .microphone_manager import MicrophoneManager
from .noise_filter import NoiseFilter
from .speech_recognizer import RecognitionResult, SpeechRecognizer
from .vad import Endpointer
from .voice_config import VoiceConfig
from .voice_exceptions import MicrophoneError, STTError

log = get_logger("voice.push_to_talk")


StatusCallback = Callable[[str], None]


@dataclass(frozen=True)
class ListenResult:
    text: str
    language: str
    confidence: float
    audio_duration_s: float
    transcription_time_s: float
    success: bool
    error: str = ""


class PushToTalkListener:
    """One-question-at-a-time microphone and local Whisper controller."""

    name = "push_to_talk"

    def __init__(self, config: VoiceConfig,
                 status: StatusCallback | None = None,
                 microphone: MicrophoneBackend | None = None,
                 play_cue: bool = True) -> None:
        self._cfg = config
        self._status = status or (lambda _message: None)

        microphone = microphone or SoundDeviceMicrophone(
            config.audio,
            config.microphone.device_index,
        )
        self._mic = MicrophoneManager(
            microphone,
            config.microphone,
            on_error=self._status,
        )
        self._endpointer = Endpointer(config.audio, config.vad)
        self._recognizer = SpeechRecognizer(
            config,
            WhisperSTT(config.stt),
            noise=NoiseFilter(config.audio, config.noise),
        )
        self._loaded = False
        self._calibrated = False
        self._play_cue = play_cue

    # Lifecycle-compatible API.
    def initialize(self) -> None:
        self._status(
            f"Loading Whisper model '{self._cfg.stt.model_size}' "
            f"on {self._cfg.stt.device}..."
        )
        self._recognizer.load()
        self._loaded = True
        self._status("Whisper is ready.")

    def start(self) -> None:
        # Push-to-talk has no background capture thread.
        pass

    def stop(self) -> None:
        try:
            self._mic.close()
        except Exception:  # noqa: BLE001
            pass

    def health_check(self) -> bool:
        return self._loaded

    def listen(self, wait_for_speech_s: float | None = None,
               *, force_calibration: bool = False,
               initial_audio: bytes = b"") -> ListenResult:
        """Record one utterance and transcribe it.

        The microphone is opened only for this call and closed before returning,
        preventing feedback from AURA's own spoken response.
        """
        if not self._loaded:
            return ListenResult(
                "", "", 0.0, 0.0, 0.0, False,
                "Whisper has not been initialized.",
            )

        self._endpointer.reset()

        microphone_was_open = self._mic.is_open()
        try:
            self._mic.open()
        except MicrophoneError as exc:
            return ListenResult(
                "", "", 0.0, 0.0, 0.0, False, str(exc),
            )

        try:
            # Briefly discard stale startup frames before prompting the user.
            # Do not flush when the wake listener hands us its live stream:
            # those queued frames may contain the first words of the question.
            flush_frames = 0 if microphone_was_open or initial_audio else max(
                1,
                int(0.12 * 1000 / self._cfg.audio.frame_ms),
            )
            for _ in range(flush_frames):
                self._mic.read_frame()

            if force_calibration or not self._calibrated:
                self._status("Calibrating room noise... stay quiet briefly.")
                count = max(
                    1,
                    int(self._cfg.vad.calibration_s * 1000
                        / self._cfg.audio.frame_ms),
                )
                frames = [self._mic.read_frame() for _ in range(count)]
                self._endpointer.calibrate(frames)
                self._calibrated = True
                self._status(
                    "Microphone calibrated "
                    f"(noise {self._endpointer.noise_floor:.4f}, "
                    f"start threshold {self._endpointer.speech_threshold:.4f}, "
                    f"continue threshold "
                    f"{self._endpointer.continuation_threshold:.4f})."
                )

            if self._play_cue:
                self._beep()
            self._status(
                "Listening... speak naturally. AURA will wait through short pauses."
            )

            timeout = (self._cfg.vad.wait_for_speech_s
                       if wait_for_speech_s is None else wait_for_speech_s)
            deadline = time.monotonic() + max(1.0, timeout)
            speech_started = False

            # Vosk may confirm the wake word only after it has already read
            # the rest of "Hey AURA, <question>". Replay those exact frames
            # through the normal endpoint and Whisper pipeline so the user
            # never has to repeat the question.
            frame_bytes = self._cfg.audio.frame_samples * 2
            usable = len(initial_audio) - (len(initial_audio) % frame_bytes)
            for offset in range(0, usable, frame_bytes):
                frame = initial_audio[offset:offset + frame_bytes]
                utterance = self._endpointer.process(frame)
                if self._endpointer.in_speech and not speech_started:
                    speech_started = True
                    self._status("I hear you... keep speaking naturally.")
                    deadline = (
                        time.monotonic()
                        + self._cfg.vad.max_utterance_s
                        + 2.0
                    )
                if utterance is not None:
                    return self._transcribe(utterance)

            while time.monotonic() < deadline:
                frame = self._mic.read_frame()
                utterance = self._endpointer.process(frame)

                if self._endpointer.in_speech and not speech_started:
                    speech_started = True
                    self._status("I hear you... keep speaking naturally.")
                    # Once speech begins, do not let the initial waiting timer
                    # cut the user off mid-sentence.
                    deadline = time.monotonic() + self._cfg.vad.max_utterance_s + 2.0

                if utterance is None:
                    continue

                return self._transcribe(utterance)

            # Preserve intelligible speech if a noisy room prevented the
            # endpointer from observing enough trailing silence.
            utterance = self._endpointer.finish()
            if utterance is not None:
                return self._transcribe(utterance)

            return ListenResult(
                "", "", 0.0, 0.0, 0.0, False,
                "No speech was detected before the timeout.",
            )

        except (MicrophoneError, STTError) as exc:
            log.warning("voice input failed: %s", exc)
            return ListenResult(
                "", "", 0.0, 0.0, 0.0, False, str(exc),
            )
        finally:
            self._mic.close()

    def request_recalibration(self) -> None:
        """Make the next listening turn recalibrate ambient room noise."""
        self._calibrated = False

    def calibrate(self) -> bool:
        """Calibrate once before hands-free wake mode begins."""
        if not self._loaded:
            return False
        self._endpointer.reset()
        try:
            self._mic.open()
            flush_frames = max(1, int(0.12 * 1000 / self._cfg.audio.frame_ms))
            for _ in range(flush_frames):
                self._mic.read_frame()
            self._status("Calibrating room noise... stay quiet briefly.")
            count = max(
                1,
                int(self._cfg.vad.calibration_s * 1000 / self._cfg.audio.frame_ms),
            )
            frames = [self._mic.read_frame() for _ in range(count)]
            self._endpointer.calibrate(frames)
            self._calibrated = True
            self._status(
                "Microphone calibrated "
                f"(noise {self._endpointer.noise_floor:.4f}, "
                f"start threshold {self._endpointer.speech_threshold:.4f}, "
                f"continue threshold "
                f"{self._endpointer.continuation_threshold:.4f})."
            )
            return True
        except MicrophoneError as exc:
            self._status(f"Microphone calibration failed: {exc}")
            return False
        finally:
            self._mic.close()

    def _transcribe(self, utterance: bytes) -> ListenResult:
        if not self._has_voice_evidence(utterance):
            return ListenResult(
                "", "", 0.0,
                len(utterance) / (2 * self._cfg.audio.sample_rate),
                0.0, False,
                "Only background noise was detected; no question was sent.",
            )
        self._status("Transcribing...")
        started = time.monotonic()
        recognized = self._recognizer.recognize(utterance)
        elapsed = time.monotonic() - started
        return self._to_result(
            recognized,
            elapsed,
            min_confidence=self._cfg.stt.min_confidence,
        )

    def _has_voice_evidence(self, pcm: bytes) -> bool:
        """Reject ambient noise before it can trigger a Whisper hallucination."""
        frame_bytes = self._cfg.audio.frame_samples * 2
        levels = [
            rms(pcm[offset:offset + frame_bytes])
            for offset in range(0, len(pcm) - frame_bytes + 1, frame_bytes)
        ]
        if not levels:
            return False
        floor = self._endpointer.noise_floor
        # The board's external electret microphone is clean but quiet at desk
        # distance. Use calibrated evidence instead of the former hard 0.015
        # floor, which rejected normal speech even though Vosk could hear it.
        threshold = max(0.0018, floor * 0.98 + 0.00010)
        strong_frames = sum(level >= threshold for level in levels)
        required = max(6, int(0.14 / (self._cfg.audio.frame_ms / 1000.0)))
        return strong_frames >= required and max(levels) >= threshold * 1.10

    @staticmethod
    def input_devices() -> list[dict[str, object]]:
        """Return sounddevice input devices for the /mics command."""
        try:
            import sounddevice as sd
            devices = sd.query_devices()
        except Exception as exc:  # noqa: BLE001
            return [{"error": str(exc)}]

        result: list[dict[str, object]] = []
        for index, device in enumerate(devices):
            channels = int(device.get("max_input_channels", 0))
            if channels <= 0:
                continue
            result.append({
                "index": index,
                "name": str(device.get("name", "Unknown")),
                "channels": channels,
                "sample_rate": int(device.get("default_samplerate", 0)),
            })
        return result

    @staticmethod
    def _to_result(recognized: RecognitionResult,
                   transcription_time_s: float,
                   min_confidence: float = 0.0) -> ListenResult:
        if recognized.is_empty:
            return ListenResult(
                "", recognized.language, recognized.confidence,
                recognized.duration_s, transcription_time_s, False,
                "Whisper did not detect any words.",
            )
        word_count = len(recognized.text.split())
        # A complete sentence from the quiet electret microphone may receive a
        # conservative decoder score even when it is useful.  Conversely,
        # accepting one noisy word such as "What?" creates a bad AI request.
        required_confidence = (
            max(0.45, min_confidence) if word_count <= 1
            else max(0.16, min_confidence - 0.04)
        )
        if recognized.confidence < required_confidence:
            return ListenResult(
                recognized.text,
                recognized.language,
                recognized.confidence,
                recognized.duration_s,
                transcription_time_s,
                False,
                "I heard speech, but I was not confident enough to use it. "
                "Please repeat that a little more clearly.",
            )
        return ListenResult(
            recognized.text,
            recognized.language,
            recognized.confidence,
            recognized.duration_s,
            transcription_time_s,
            True,
        )

    @staticmethod
    def _beep() -> None:
        """Short Windows cue; silently skipped on other platforms."""
        try:
            import winsound
            winsound.Beep(900, 110)
        except Exception:  # noqa: BLE001
            pass
