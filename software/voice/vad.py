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
    """Calibrated energy VAD which continues adapting during quiet periods."""
    def __init__(self, aggressiveness: int = 2, *,
                 noise_multiplier: float = 2.2,
                 noise_margin: float = 0.004) -> None:
        # Map 0..3 aggressiveness to an RMS threshold.
        # The ES3C28P electret input is clean but substantially quieter than a
        # typical laptop microphone. Mode 0 must follow the calibrated floor
        # instead of imposing the former 0.010 minimum, which detected only
        # the loudest syllable and discarded the rest of normal speech.
        self._threshold = (0.0020, 0.005, 0.012, 0.020)[
            max(0, min(3, aggressiveness))
        ]
        self._floor = 0.0
        self._calibrated_floor = 0.0
        self._noise_multiplier = noise_multiplier
        self._noise_margin = noise_margin

    @property
    def noise_floor(self) -> float:
        return self._floor

    @property
    def speech_threshold(self) -> float:
        return max(
            self._threshold,
            self._floor * self._noise_multiplier + self._noise_margin,
        )

    @property
    def continuation_threshold(self) -> float:
        """Lower threshold used after speech has already started.

        Natural speech contains quiet consonants and unstressed syllables.  A
        single start/stop threshold clipped those parts on AURA's quiet
        electret microphone, often leaving Whisper with only one loud word.
        """
        # At two metres the AOM-5024L speech envelope sits only slightly above
        # this board's p90 electrical-noise floor. Once a real onset has been
        # confirmed, use hysteresis below that p90 value to retain quiet words.
        return max(0.0015, self._floor * 0.90 + 0.00010)

    def calibrate(self, frames: list[bytes]) -> None:
        """Set a robust ambient-noise floor from quiet calibration frames."""
        levels = sorted(rms(frame) for frame in frames if frame)
        if not levels:
            return
        # This board's display/USB activity creates periodic noise bursts. The
        # 90th percentile represents the loud end of normal room noise without
        # letting one isolated click dominate calibration.
        index = min(len(levels) - 1, int(len(levels) * 0.90))
        self._floor = levels[index]
        self._calibrated_floor = self._floor

    def is_speech(self, frame: bytes, sample_rate: int) -> bool:
        level = rms(frame)
        speech = level > self.speech_threshold
        # Track only likely background audio; never learn the user's voice as noise.
        if not speech:
            # Adapt upward when a room becomes noisier, but do not quickly
            # decay below the calibrated noise envelope and become sensitive
            # to the board's periodic electrical noise.
            target = max(level, self._calibrated_floor * 0.85)
            self._floor = 0.995 * self._floor + 0.005 * target
        return speech

    def is_continuation(self, frame: bytes, sample_rate: int) -> bool:
        """Use hysteresis to preserve quiet words once an utterance starts."""
        level = rms(frame)
        speech = level > self.continuation_threshold
        if not speech:
            target = max(level, self._calibrated_floor * 0.85)
            self._floor = 0.998 * self._floor + 0.002 * target
        return speech

    def is_strong_speech(self, frame: bytes, sample_rate: int) -> bool:
        """Evidence strong enough to reset the end-of-speech pause timer."""
        return rms(frame) > self.speech_threshold


class Endpointer:
    """Frame-by-frame utterance segmentation. Returns a completed utterance's
    PCM bytes when speech ends, else None."""

    def __init__(self, audio: AudioConfig, cfg: VADConfig,
                 backend: VADBackend | None = None) -> None:
        self._audio = audio
        self._cfg = cfg
        self._vad = backend or EnergyVAD(
            cfg.aggressiveness,
            noise_multiplier=cfg.noise_multiplier,
            noise_margin=cfg.noise_margin,
        )
        pre_roll_frames = max(1, int(cfg.pre_roll_ms / audio.frame_ms))
        self._preroll: deque[bytes] = deque(maxlen=pre_roll_frames)
        self._buf: list[bytes] = []
        self._in_speech = False
        self._speech_run = 0
        self._silence_s = 0.0
        self._elapsed_s = 0.0
        self._voiced_s = 0.0
        self._strong_run = 0

    @property
    def in_speech(self) -> bool:
        return self._in_speech

    @property
    def noise_floor(self) -> float:
        return float(getattr(self._vad, "noise_floor", 0.0))

    @property
    def speech_threshold(self) -> float:
        return float(getattr(self._vad, "speech_threshold", 0.0))

    @property
    def continuation_threshold(self) -> float:
        return float(
            getattr(
                self._vad,
                "continuation_threshold",
                self.speech_threshold,
            )
        )

    @property
    def silence_timeout_s(self) -> float:
        """Adaptive pause allowed for the current utterance."""
        # Base this on voiced time, not wall time. Otherwise a short phrase's
        # pause itself would make it look like a long utterance and shorten
        # the timeout while the user is still thinking.
        if self._voiced_s < self._cfg.short_utterance_s:
            return self._cfg.short_silence_timeout_s
        if self._voiced_s >= self._cfg.long_utterance_s:
            return self._cfg.long_silence_timeout_s
        return self._cfg.silence_timeout_s

    def calibrate(self, frames: list[bytes]) -> None:
        calibrate = getattr(self._vad, "calibrate", None)
        if callable(calibrate):
            calibrate(frames)

    def reset(self) -> None:
        self._preroll.clear(); self._buf.clear()
        self._in_speech = False; self._speech_run = 0
        self._silence_s = 0.0; self._elapsed_s = 0.0
        self._voiced_s = 0.0
        self._strong_run = 0

    def finish(self) -> bytes | None:
        """Return a valid partial utterance when an outer timeout is reached."""
        pcm = b"".join(self._buf) if self._in_speech else b""
        valid = bool(pcm) and self._voiced_s >= self._cfg.min_speech_s
        self.reset()
        return pcm if valid else None

    def process(self, frame: bytes) -> bytes | None:
        """Feed one frame. Returns completed utterance PCM when speech ends."""
        if self._in_speech:
            continuation = getattr(self._vad, "is_continuation", None)
            speech = (
                continuation(frame, self._audio.sample_rate)
                if callable(continuation)
                else self._vad.is_speech(frame, self._audio.sample_rate)
            )
            strong_detector = getattr(self._vad, "is_strong_speech", None)
            strong_speech = (
                strong_detector(frame, self._audio.sample_rate)
                if callable(strong_detector)
                else speech
            )
        else:
            speech = self._vad.is_speech(frame, self._audio.sample_rate)
            strong_speech = speech
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
                    self._voiced_s = self._cfg.start_frames * frame_s
                    self._speech_run = 0
                    self._strong_run = self._cfg.start_frames
            else:
                self._speech_run = 0
            return None

        # In speech: accumulate.
        self._buf.append(frame)
        self._elapsed_s += frame_s
        if speech:
            self._speech_run += 1
            self._voiced_s += frame_s
        else:
            self._speech_run = 0

        if strong_speech:
            self._strong_run += 1
        else:
            self._strong_run = 0

        # Quiet continuation frames are retained in the recording, but only
        # two consecutive strong speech frames may reset the pause timer.
        # This prevents far-field room noise from extending every recording
        # to the hard 20-second limit.
        if self._strong_run >= 2:
            self._silence_s = 0.0
        else:
            self._silence_s += frame_s

        ended = (self._silence_s >= self.silence_timeout_s
                 or self._elapsed_s >= self._cfg.max_utterance_s)
        if ended:
            # Whisper does not need the full endpointing pause. Retain 220 ms
            # for a natural word ending and remove the rest before inference.
            # This makes transcription noticeably faster without clipping the
            # final consonant.
            frames = self._buf
            if self._silence_s >= self.silence_timeout_s:
                removable_s = max(0.0, self._silence_s - 0.22)
                removable_frames = int(removable_s / frame_s)
                if 0 < removable_frames < len(frames):
                    frames = frames[:-removable_frames]
            pcm = b"".join(frames)
            valid = self._voiced_s >= self._cfg.min_speech_s
            self.reset()
            return pcm if valid else None
        return None
