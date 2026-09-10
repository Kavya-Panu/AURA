"""
speech/audio_player.py
======================
Plays a synthesized audio clip. Playback sits behind an AudioSink Protocol so no
audio backend is imported at module load; a FakeAudioSink drives tests. Handles
start/end, interruption and volume. Thread-safe.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Protocol, runtime_checkable

from core.logger import get_logger

from .speech_exceptions import PlaybackError

log = get_logger("speech.audio")


@runtime_checkable
class AudioSink(Protocol):
    """Where audio actually goes. Real impl wraps a sound library/device."""
    def play(self, audio: object, duration_s: float,
             should_stop: Callable[[], bool]) -> bool: ...
    def set_volume(self, volume: float) -> None: ...


class FakeAudioSink:
    """Deterministic sink for tests: 'plays' by waiting a scaled fraction of the
    duration, honouring the stop flag so interruption is testable."""

    def __init__(self, speed: float = 200.0) -> None:
        # speed = how much faster than real-time to simulate (keeps tests fast)
        self._speed = speed
        self.volume = 1.0
        self.played: list[object] = []

    def set_volume(self, volume: float) -> None:
        self.volume = max(0.0, min(1.0, volume))

    def play(self, audio: object, duration_s: float,
             should_stop: Callable[[], bool]) -> bool:
        self.played.append(audio)
        remaining = duration_s / self._speed
        step = 0.002
        waited = 0.0
        while waited < remaining:
            if should_stop():
                return False            # interrupted
            time.sleep(step)
            waited += step
        return True                     # completed


class RealAudioSink:
    """Real WAV playback via soundfile + sounddevice (lazily imported)."""

    def __init__(self) -> None:
        self.volume = 1.0

    def set_volume(self, volume: float) -> None:
        self.volume = max(0.0, min(1.0, volume))

    def play(self, audio: object, duration_s: float,
             should_stop: Callable[[], bool]) -> bool:
        del duration_s  # playback duration comes from the generated WAV file

        try:
            import sounddevice as sd
            import soundfile as sf
        except Exception as exc:                        # noqa: BLE001
            raise PlaybackError(f"audio backend unavailable: {exc}") from exc

        path = str(audio)
        try:
            samples, sample_rate = sf.read(path, dtype="float32")
            if self.volume != 1.0:
                samples = samples * self.volume

            sd.play(samples, sample_rate, blocking=False)

            while True:
                stream = sd.get_stream()
                if not bool(getattr(stream, "active", False)):
                    return True
                if should_stop():
                    sd.stop()
                    return False
                time.sleep(0.02)

        except Exception as exc:                        # noqa: BLE001
            raise PlaybackError(f"playback failed: {exc}") from exc
        finally:
            # pyttsx3 produces a temporary WAV for each answer.
            try:
                from pathlib import Path
                temp_path = Path(path)
                if temp_path.exists() and temp_path.suffix.lower() == ".wav":
                    temp_path.unlink(missing_ok=True)
            except Exception:                           # noqa: BLE001
                pass


class Esp32AudioSink:
    """WAV playback through the robot's ES8311 speaker over USB serial."""

    def __init__(self, audio_link, sample_rate: int = 16_000) -> None:
        self._link = audio_link
        self._sample_rate = sample_rate
        self.volume = 1.0

    def set_volume(self, volume: float) -> None:
        self.volume = max(0.0, min(1.0, volume))
        self._link.set_volume(round(self.volume * 100))

    def play(self, audio: object, duration_s: float,
             should_stop: Callable[[], bool]) -> bool:
        del duration_s
        path = str(audio)
        try:
            import numpy as np
            import soundfile as sf

            samples, source_rate = sf.read(path, dtype="float32", always_2d=True)
            mono = samples.mean(axis=1)
            if source_rate != self._sample_rate and len(mono) > 1:
                target_count = max(
                    1,
                    round(len(mono) * self._sample_rate / source_rate),
                )
                source_x = np.linspace(0.0, 1.0, len(mono), endpoint=False)
                target_x = np.linspace(0.0, 1.0, target_count, endpoint=False)
                mono = np.interp(target_x, source_x, mono)

            # The tiny robot speaker needs a denser signal than desktop
            # speakers, but hard limiting overloads its small amplifier and
            # sounds like a burst/crackle. Use moderate speech compression with
            # generous electrical headroom; the ES8311 controls final volume.
            mono = np.nan_to_num(mono, copy=False)
            if len(mono):
                mono = mono - float(np.mean(mono))
                rms = float(np.sqrt(np.mean(np.square(mono))))
                if rms > 1.0e-5:
                    drive = float(np.clip(0.13 / rms, 1.0, 3.0))
                    mono = np.tanh(mono * drive)
                    peak = float(np.max(np.abs(mono)))
                    if peak > 1.0e-5:
                        mono = mono * (0.60 / peak)
            mono = np.clip(mono, -0.60, 0.60)

            # Give the ES8311 DAC/amp 120 ms to settle after switching from the
            # microphone, then play a brief two-note acknowledgement before
            # every answer. This is both a friendly Siri-like cue and an
            # unmistakable check that the robot speaker path is active.
            settle = np.zeros(round(self._sample_rate * 0.12), dtype=np.float32)
            note_len = round(self._sample_rate * 0.075)
            gap = np.zeros(round(self._sample_rate * 0.025), dtype=np.float32)
            tail = np.zeros(round(self._sample_rate * 0.06), dtype=np.float32)
            t = np.arange(note_len, dtype=np.float32) / self._sample_rate
            envelope = np.sin(np.linspace(0.0, np.pi, note_len, dtype=np.float32))
            note_one = 0.18 * np.sin(2.0 * np.pi * 784.0 * t) * envelope
            note_two = 0.18 * np.sin(2.0 * np.pi * 1046.5 * t) * envelope
            mono = np.concatenate(
                (settle, note_one, gap, note_two, tail, mono.astype(np.float32)),
            )

            final_rms = float(np.sqrt(np.mean(np.square(mono)))) if len(mono) else 0.0
            final_peak = float(np.max(np.abs(mono))) if len(mono) else 0.0
            log.info(
                "ESP32 speech prepared: %.2fs, RMS %.3f, peak %.3f",
                len(mono) / self._sample_rate,
                final_rms,
                final_peak,
            )
            pcm = (mono * 32767.0).astype("<i2", copy=False).tobytes()
            return bool(self._link.play_pcm(pcm, should_stop))
        except Exception as exc:  # noqa: BLE001
            raise PlaybackError(f"ESP32 speaker playback failed: {exc}") from exc
        finally:
            try:
                from pathlib import Path
                temp_path = Path(path)
                if temp_path.exists() and temp_path.suffix.lower() == ".wav":
                    temp_path.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass


class AudioPlayer:
    """Coordinates playback with a stop flag for interruption. Thread-safe."""

    def __init__(self, sink: AudioSink) -> None:
        self._sink = sink
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._playing = False

    def set_volume(self, volume: float) -> None:
        self._sink.set_volume(volume)

    def play(self, audio: object, duration_s: float) -> bool:
        """Play a clip; returns True if completed, False if interrupted."""
        with self._lock:
            self._stop.clear()
            self._playing = True
        try:
            completed = self._sink.play(audio, duration_s, self._stop.is_set)
            return completed
        finally:
            with self._lock:
                self._playing = False

    def stop(self) -> None:
        """Interrupt the current playback."""
        self._stop.set()

    @property
    def is_playing(self) -> bool:
        with self._lock:
            return self._playing
