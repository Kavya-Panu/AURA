"""
speech/voice_profiles.py
========================
Voice profiles: named bundles of voice/speed/pitch/volume/pause settings. These
are data and configurable; new profiles can be registered without code changes.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

from .speech_exceptions import VoiceProfileError


@dataclass(frozen=True)
class VoiceProfile:
    """One speaking style."""
    name: str
    voice: str = "default"       # engine-specific voice id/name
    speed: float = 1.0           # rate multiplier (1.0 = normal)
    pitch: float = 1.0           # pitch multiplier
    volume: float = 1.0          # 0..1
    sentence_pause_s: float = 0.25


DEFAULT_PROFILES: dict[str, VoiceProfile] = {
    "friendly":   VoiceProfile("friendly", speed=1.0, pitch=1.05, volume=1.0),
    "teacher":    VoiceProfile("teacher", speed=0.9, pitch=1.0, volume=1.0,
                               sentence_pause_s=0.4),
    "translator": VoiceProfile("translator", speed=1.1, pitch=1.0, volume=1.0,
                               sentence_pause_s=0.15),
    "assistant":  VoiceProfile("assistant", speed=1.0, pitch=1.0, volume=1.0),
    "calm":       VoiceProfile("calm", speed=0.85, pitch=0.98, volume=0.9,
                               sentence_pause_s=0.45),
    "excited":    VoiceProfile("excited", speed=1.15, pitch=1.12, volume=1.0,
                               sentence_pause_s=0.15),
}


class VoiceProfileRegistry:
    """Thread-safe registry of voice profiles; supports future custom voices."""

    def __init__(self, profiles: dict[str, VoiceProfile] | None = None) -> None:
        self._lock = threading.RLock()
        self._profiles = dict(DEFAULT_PROFILES)
        if profiles:
            self._profiles.update(profiles)

    def register(self, profile: VoiceProfile) -> None:
        with self._lock:
            self._profiles[profile.name] = profile

    def get(self, name: str) -> VoiceProfile:
        with self._lock:
            profile = self._profiles.get(name)
        if profile is None:
            raise VoiceProfileError(f"unknown voice profile '{name}'")
        return profile

    def has(self, name: str) -> bool:
        with self._lock:
            return name in self._profiles

    def names(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._profiles))
