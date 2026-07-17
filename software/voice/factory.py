"""
voice/factory.py
================
Builders that wire real backends for the laptop, or fakes for tests. Keeps all
backend selection in one place (dependency injection root for the Voice System).
"""
from __future__ import annotations

from core.event_bus import EventBus
from .backends import (
    FakeMicrophone, FakeSTT, SoundDeviceMicrophone, WhisperSTT,
)
from .voice_config import VoiceConfig
from .voice_system import VoiceSystem


def build_real_voice_system(bus: EventBus,
                            config: VoiceConfig | None = None) -> VoiceSystem:
    """Voice System backed by sounddevice + faster-whisper (laptop build).
    Requires those libraries + a microphone at runtime."""
    cfg = config or VoiceConfig()
    mic = SoundDeviceMicrophone(cfg.audio, cfg.microphone.device_index)
    stt = WhisperSTT(cfg.stt)
    return VoiceSystem(bus, cfg, microphone=mic, stt=stt)


def build_fake_voice_system(bus: EventBus,
                            config: VoiceConfig | None = None,
                            mic: FakeMicrophone | None = None,
                            stt: FakeSTT | None = None) -> VoiceSystem:
    """Voice System backed by fakes (tests / dev without hardware)."""
    cfg = config or VoiceConfig()
    return VoiceSystem(bus, cfg,
                       microphone=mic or FakeMicrophone(),
                       stt=stt or FakeSTT())
