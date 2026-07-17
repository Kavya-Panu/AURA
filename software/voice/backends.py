"""
voice/backends.py
=================
Hardware/model backends behind Protocols, so the Voice System depends on
INTERFACES, not on faster-whisper / sounddevice / a physical mic. This is what
lets the whole pipeline run and be tested with fakes here, then use the real
libraries on the laptop by injecting the real backends.

Backends provided:
    MicrophoneBackend  - source of audio frames
        * SoundDeviceMicrophone  (real; needs `sounddevice`)
        * FakeMicrophone         (feeds scripted frames; for tests)
    STTBackend         - speech -> text
        * WhisperSTT             (real; needs `faster-whisper`)
        * FakeSTT                (scripted transcripts; for tests)
"""
from __future__ import annotations

import threading
from typing import Callable, Iterable, Protocol, runtime_checkable

from core.logger import get_logger
from .voice_config import STTConfig, AudioConfig
from .voice_exceptions import MicrophoneError, STTError

log = get_logger("voice.backends")

FrameCallback = Callable[[bytes], None]


# ===========================================================================
#  Microphone
# ===========================================================================
@runtime_checkable
class MicrophoneBackend(Protocol):
    """A source of fixed-size int16 PCM frames."""
    def open(self) -> None: ...
    def close(self) -> None: ...
    def read_frame(self) -> bytes: ...          # blocks until one frame
    def is_open(self) -> bool: ...


class FakeMicrophone:
    """Deterministic microphone for tests. Yields scripted frames then blocks
    (or raises, to simulate disconnect). No hardware, no threads of its own."""

    def __init__(self, frames: Iterable[bytes] = (),
                 fail_after: int | None = None) -> None:
        self._frames = list(frames)
        self._i = 0
        self._open = False
        self._fail_after = fail_after
        self.reads = 0

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    def is_open(self) -> bool:
        return self._open

    def feed(self, frame: bytes) -> None:
        self._frames.append(frame)

    def read_frame(self) -> bytes:
        if not self._open:
            raise MicrophoneError("read from closed FakeMicrophone")
        self.reads += 1
        if self._fail_after is not None and self.reads > self._fail_after:
            raise MicrophoneError("simulated microphone disconnect")
        if self._i < len(self._frames):
            f = self._frames[self._i]
            self._i += 1
            return f
        return b""                    # silence when script exhausted


class SoundDeviceMicrophone:
    """Real microphone via `sounddevice`. Imported lazily so environments
    without the library (or without audio hardware) can still import this
    module and use the fake backend."""

    def __init__(self, audio: AudioConfig, device_index: int | None = None) -> None:
        self._audio = audio
        self._device_index = device_index
        self._stream = None

    def open(self) -> None:
        try:
            import sounddevice as sd    # lazy import
        except Exception as exc:        # noqa: BLE001
            raise MicrophoneError("sounddevice not available",
                                  {"error": str(exc)}) from exc
        try:
            self._stream = sd.RawInputStream(
                samplerate=self._audio.sample_rate,
                channels=self._audio.channels,
                dtype=self._audio.dtype,
                blocksize=self._audio.frame_samples,
                device=self._device_index,
            )
            self._stream.start()
        except Exception as exc:        # noqa: BLE001
            raise MicrophoneError("failed to open input stream",
                                  {"error": str(exc)}) from exc

    def close(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop(); self._stream.close()
            finally:
                self._stream = None

    def is_open(self) -> bool:
        return self._stream is not None

    def read_frame(self) -> bytes:
        if self._stream is None:
            raise MicrophoneError("read from closed microphone")
        data, _overflowed = self._stream.read(self._audio.frame_samples)
        return bytes(data)


# ===========================================================================
#  Speech-to-text
# ===========================================================================
class STTResult:
    """Transcription result."""
    __slots__ = ("text", "language", "confidence")

    def __init__(self, text: str, language: str, confidence: float) -> None:
        self.text = text
        self.language = language
        self.confidence = confidence


@runtime_checkable
class STTBackend(Protocol):
    def load(self) -> None: ...
    def transcribe(self, pcm: bytes, sample_rate: int,
                   language: str | None) -> STTResult: ...


class FakeSTT:
    """Scripted STT for tests. Maps queued transcripts in FIFO order; returns
    empty text when exhausted (i.e. 'no speech')."""

    def __init__(self, scripted: Iterable[tuple[str, str, float]] = ()) -> None:
        # each item: (text, language, confidence)
        self._queue = list(scripted)
        self._i = 0
        self.loaded = False

    def load(self) -> None:
        self.loaded = True

    def queue(self, text: str, language: str = "en", confidence: float = 0.95):
        self._queue.append((text, language, confidence))

    def transcribe(self, pcm: bytes, sample_rate: int,
                   language: str | None) -> STTResult:
        if not self.loaded:
            raise STTError("FakeSTT.transcribe before load()")
        if self._i < len(self._queue):
            text, lang, conf = self._queue[self._i]
            self._i += 1
            return STTResult(text, language or lang, conf)
        return STTResult("", language or "en", 0.0)


class WhisperSTT:
    """Real STT via `faster-whisper`. Lazily imported. Expects int16 PCM bytes,
    converts to float32 for the model."""

    def __init__(self, cfg: STTConfig) -> None:
        self._cfg = cfg
        self._model = None

    def load(self) -> None:
        try:
            from faster_whisper import WhisperModel   # lazy import
        except Exception as exc:        # noqa: BLE001
            raise STTError("faster-whisper not available",
                           {"error": str(exc)}) from exc
        device = self._cfg.device
        if device == "auto":
            try:
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
            except Exception:           # noqa: BLE001
                device = "cpu"
        self._model = WhisperModel(self._cfg.model_size, device=device,
                                   compute_type=self._cfg.compute_type)
        log.info("Whisper model '%s' loaded on %s", self._cfg.model_size, device)

    def transcribe(self, pcm: bytes, sample_rate: int,
                   language: str | None) -> STTResult:
        if self._model is None:
            raise STTError("WhisperSTT.transcribe before load()")
        try:
            import numpy as np
            audio = (np.frombuffer(pcm, dtype=np.int16)
                     .astype(np.float32) / 32768.0)
            segments, info = self._model.transcribe(
                audio, language=language, beam_size=self._cfg.beam_size)
            text = " ".join(seg.text for seg in segments).strip()
            conf = float(getattr(info, "language_probability", 0.0) or 0.0)
            lang = getattr(info, "language", language or "en")
            return STTResult(text, lang, conf if conf else (0.9 if text else 0.0))
        except Exception as exc:        # noqa: BLE001
            raise STTError("transcription failed", {"error": str(exc)}) from exc
