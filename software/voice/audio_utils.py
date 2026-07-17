"""
voice/audio_utils.py
====================
Small, dependency-light audio helpers. int16 PCM is represented as raw bytes;
these helpers avoid importing numpy so the module works even in minimal
environments (the STT backend may still use numpy internally).
"""
from __future__ import annotations

import array
import math


def bytes_to_int16(pcm: bytes) -> array.array:
    """View raw little-endian PCM bytes as an int16 array (no copy of values)."""
    a = array.array("h")
    a.frombytes(pcm)
    return a


def int16_to_bytes(samples: array.array) -> bytes:
    return samples.tobytes()


def rms(pcm: bytes) -> float:
    """Root-mean-square amplitude of int16 PCM, normalised to 0..1."""
    if not pcm:
        return 0.0
    samples = bytes_to_int16(pcm)
    if len(samples) == 0:
        return 0.0
    acc = 0
    for s in samples:
        acc += s * s
    return math.sqrt(acc / len(samples)) / 32768.0


def duration_s(pcm: bytes, sample_rate: int) -> float:
    """Duration of int16 mono PCM in seconds."""
    return (len(pcm) / 2) / sample_rate if sample_rate else 0.0


def concat(frames: list[bytes]) -> bytes:
    return b"".join(frames)
