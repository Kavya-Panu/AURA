"""
voice/noise_filter.py
=====================
Optional pre-processing: a simple one-pole high-pass to remove low-frequency
fan/hum rumble before STT. Dependency-light (pure Python over int16). Real
deployments can replace this with an RNNoise/noisereduce backend via the same
`process()` signature.
"""
from __future__ import annotations

import array
import math

from .voice_config import AudioConfig, NoiseConfig


class NoiseFilter:
    """One-pole high-pass filter with configurable cutoff."""

    def __init__(self, audio: AudioConfig, cfg: NoiseConfig) -> None:
        self._enabled = cfg.enabled
        self._auto_gain = cfg.auto_gain
        self._target_rms = max(0.01, min(0.5, cfg.target_rms))
        self._max_gain = max(1.0, cfg.max_gain)
        self._peak_limit = max(0.1, min(0.99, cfg.peak_limit))
        self._prev_in = 0.0
        self._prev_out = 0.0
        dt = 1.0 / audio.sample_rate
        rc = 1.0 / (2 * math.pi * max(1, cfg.high_pass_hz))
        self._alpha = rc / (rc + dt)

    def process(self, pcm: bytes) -> bytes:
        if not pcm:
            return pcm
        samples = array.array("h"); samples.frombytes(pcm)
        if self._enabled:
            out = array.array("h", bytes(len(pcm)))
            a = self._alpha
            prev_in, prev_out = self._prev_in, self._prev_out
            for i, x in enumerate(samples):
                y = a * (prev_out + x - prev_in)
                prev_in = x
                prev_out = y
                out[i] = int(max(-32768, min(32767, y)))
            self._prev_in, self._prev_out = prev_in, prev_out
        else:
            out = samples

        if self._auto_gain and out:
            energy = math.sqrt(sum(x * x for x in out) / len(out))
            peak = max(abs(x) for x in out)
            if energy >= 1.0 and peak > 0:
                wanted = (self._target_rms * 32768.0) / energy
                safe = (self._peak_limit * 32768.0) / peak
                gain = max(1.0, min(self._max_gain, wanted, safe))
                if gain > 1.02:
                    for i, x in enumerate(out):
                        out[i] = int(max(-32768, min(32767, x * gain)))
        return out.tobytes()
