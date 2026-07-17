"""
voice/vad.py
============
Voice-activity detection / endpointing. A real WebRTC VAD can be injected;
otherwise an energy-based fallback is used. The endpointer turns a stream of
frames into complete utterances: it waits for `start_frames` of speech to
begin, keeps `pre_roll` audio before onset, and ends after
`silence_timeout_s` of trailing silence (or `max_utterance_s`).
"""
from __future__ import annotations

from collections import deque
from typing import Protocol, runtime_checkable

from .audio_utils import rms
from .voice_config import AudioConfig, VADConfig


@runtime_checkable
class VADBackend(Protocol):
    def is_speech(self, frame: bytes, sample_rate: int) -> bool: ...


class EnergyVAD:
    """Energy-threshold VAD fallback. Adapts a noise floor from quiet frames."""
    def __init__(self, aggressiveness: int = 2) -> None:
        # Map 0..3 aggressiveness to an RMS threshold.
        self._threshold = (0.010, 0.015, 0.022, 0.030)[max(0, min(3, aggressiveness))]
        self._floor = 0.0

    def is_speech(self, frame: bytes, sample_rate: int) -> bool:
        level = rms(frame)
        # Slow noise-floor tracking.
        self._floor = 0.995 * self._floor + 0.005 * level
        return level > max(self._threshold, self._floor * 2.5)


class Endpointer:
    """Frame-by-frame utterance segmentation. Returns a completed utterance's
    PCM bytes when speech ends, else None."""

    def __init__(self, audio: AudioConfig, cfg: VADConfig,
                 backend: VADBackend | None = None) -> None:
        self._audio = audio
        self._cfg = cfg
        self._vad = backend or EnergyVAD(cfg.aggressiveness)
        pre_roll_frames = max(1, int(cfg.pre_roll_ms / audio.frame_ms))
        self._preroll: deque[bytes] = deque(maxlen=pre_roll_frames)
        self._buf: list[bytes] = []
        self._in_speech = False
        self._speech_run = 0
        self._silence_s = 0.0
        self._elapsed_s = 0.0

    @property
    def in_speech(self) -> bool:
        return self._in_speech

    def reset(self) -> None:
        self._preroll.clear(); self._buf.clear()
        self._in_speech = False; self._speech_run = 0
        self._silence_s = 0.0; self._elapsed_s = 0.0

    def process(self, frame: bytes) -> bytes | None:
        """Feed one frame. Returns completed utterance PCM when speech ends."""
        speech = self._vad.is_speech(frame, self._audio.sample_rate)
        frame_s = self._audio.frame_ms / 1000.0

        if not self._in_speech:
            self._preroll.append(frame)
            if speech:
                self._speech_run += 1
                if self._speech_run >= self._cfg.start_frames:
                    # Begin utterance, including the pre-roll context.
                    self._in_speech = True
                    self._buf = list(self._preroll)
                    self._silence_s = 0.0
                    self._elapsed_s = len(self._buf) * frame_s
            else:
                self._speech_run = 0
            return None

        # In speech: accumulate.
        self._buf.append(frame)
        self._elapsed_s += frame_s
        self._silence_s = 0.0 if speech else self._silence_s + frame_s

        ended = (self._silence_s >= self._cfg.silence_timeout_s
                 or self._elapsed_s >= self._cfg.max_utterance_s)
        if ended:
            pcm = b"".join(self._buf)
            self.reset()
            return pcm
        return None
