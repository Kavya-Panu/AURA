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

import math
import os
import sys
import threading
from pathlib import Path
from typing import Callable, Iterable, Protocol, runtime_checkable

from core.logger import get_logger
from .voice_config import STTConfig, AudioConfig
from .voice_exceptions import MicrophoneError, STTError

log = get_logger("voice.backends")

# Keep Windows DLL directory handles alive for the lifetime of the process.
# Closing or garbage-collecting a handle removes that directory from DLL search.
_CUDA_DLL_HANDLES: list[object] = []


def _prepare_windows_cuda_runtime() -> None:
    """Expose CUDA 12 libraries bundled with Ollama to CTranslate2.

    The NVIDIA display driver supports CUDA, but it does not install the
    user-space cuBLAS DLL required by faster-whisper. Ollama already ships the
    compatible CUDA 12 runtime, so reuse it instead of installing another full
    CUDA toolkit.
    """
    if os.name != "nt":
        return

    local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
    candidates = (
        local_app_data / "Programs" / "Ollama" / "lib" / "ollama" / "cuda_v12",
        Path(sys.prefix) / "Lib" / "site-packages" / "ctranslate2",
    )
    for directory in candidates:
        if not directory.is_dir():
            continue
        directory_text = str(directory)
        path_entries = os.environ.get("PATH", "").lower().split(os.pathsep)
        if directory_text.lower() not in path_entries:
            os.environ["PATH"] = (
                directory_text + os.pathsep + os.environ.get("PATH", "")
            )
        if hasattr(os, "add_dll_directory"):
            try:
                _CUDA_DLL_HANDLES.append(os.add_dll_directory(directory_text))
            except OSError:
                pass

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


class Esp32SerialMicrophone:
    """The ES8311 MEMS microphone streamed by the ESP32 audio link."""

    def __init__(self, audio_link) -> None:
        self._link = audio_link
        self._open = False

    def open(self) -> None:
        # Wake-word mode deliberately hands an already-running stream to the
        # high-accuracy question listener. Reopening here would stop/restart
        # I2S and discard the first words spoken after "Hi AURA".
        if self._open:
            return
        try:
            self._link.start_microphone()
            self._open = True
        except Exception as exc:  # noqa: BLE001
            raise MicrophoneError(
                "failed to start ESP32 onboard microphone",
                {"error": str(exc)},
            ) from exc

    def close(self) -> None:
        if not self._open:
            return
        try:
            self._link.stop_microphone()
        finally:
            self._open = False

    def is_open(self) -> bool:
        return self._open

    def read_frame(self) -> bytes:
        if not self._open:
            raise MicrophoneError("read from closed ESP32 microphone")
        try:
            return self._link.read_microphone_frame()
        except Exception as exc:  # noqa: BLE001
            raise MicrophoneError(
                "ESP32 microphone stream stopped",
                {"error": str(exc)},
            ) from exc


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
        if self._cfg.device in {"cuda", "auto"}:
            _prepare_windows_cuda_runtime()
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
            # Whisper can confidently invent "Thank you" on digital silence.
            # Reject empty/flat input before decoding, including a stuck ADC
            # returning a constant DC value. This threshold is far below
            # audible speech; it does not blacklist genuine short replies.
            if audio.size == 0 or float(np.std(audio)) < 1.0e-5:
                return STTResult("", language or "en", 0.0)
            segments, info = self._model.transcribe(
                audio,
                language=language,
                beam_size=self._cfg.beam_size,
                best_of=self._cfg.best_of,
                patience=self._cfg.patience,
                repetition_penalty=self._cfg.repetition_penalty,
                no_repeat_ngram_size=self._cfg.no_repeat_ngram_size,
                hotwords=self._cfg.hotwords,
                initial_prompt=self._cfg.initial_prompt,
                # The calibrated endpointer already isolated the utterance.
                # A second VAD pass can clip quiet opening and closing words.
                vad_filter=False,
                condition_on_previous_text=False,
                temperature=0.0,
                word_timestamps=False,
            )
            accepted: list[str] = []
            confidence_total = 0.0
            confidence_weight = 0.0
            for segment in segments:
                no_speech = float(getattr(segment, "no_speech_prob", 0.0) or 0.0)
                avg_logprob = float(getattr(segment, "avg_logprob", 0.0) or 0.0)
                # Reject Whisper's common silence/noise hallucinations while
                # retaining quiet but credible speech.
                if no_speech >= 0.65 and avg_logprob < -0.45:
                    continue
                if avg_logprob < -1.35:
                    continue
                accepted.append(segment.text)
                start = float(getattr(segment, "start", 0.0) or 0.0)
                end = float(getattr(segment, "end", start + 0.1) or (start + 0.1))
                weight = max(0.1, end - start)
                decoder_probability = math.exp(max(-10.0, min(0.0, avg_logprob)))
                speech_probability = max(0.0, min(1.0, 1.0 - no_speech))
                confidence_total += decoder_probability * speech_probability * weight
                confidence_weight += weight
            text = " ".join(accepted).strip()
            conf = (
                confidence_total / confidence_weight
                if text and confidence_weight > 0.0
                else 0.0
            )
            lang = getattr(info, "language", language or "en")
            return STTResult(text, lang, max(0.0, min(1.0, conf)))
        except Exception as exc:        # noqa: BLE001
            raise STTError("transcription failed", {"error": str(exc)}) from exc
