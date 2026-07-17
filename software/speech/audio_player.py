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
    """Real playback via simpleaudio/sounddevice (lazily imported)."""

    def __init__(self) -> None:
        self.volume = 1.0

    def set_volume(self, volume: float) -> None:
        self.volume = max(0.0, min(1.0, volume))

    def play(self, audio: object, duration_s: float,
             should_stop: Callable[[], bool]) -> bool:
        try:
            import simpleaudio as sa
        except Exception as exc:                        # noqa: BLE001
            raise PlaybackError(f"audio backend unavailable: {exc}") from exc
        try:
            wave_obj = sa.WaveObject.from_wave_file(str(audio))
            play_obj = wave_obj.play()
            while play_obj.is_playing():
                if should_stop():
                    play_obj.stop()
                    return False
                time.sleep(0.02)
            return True
        except Exception as exc:                        # noqa: BLE001
            raise PlaybackError(f"playback failed: {exc}") from exc


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
