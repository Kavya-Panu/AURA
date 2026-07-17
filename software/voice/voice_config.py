"""
voice/voice_config.py
=====================
Configuration for the Voice System. Pure data (dataclasses); no behaviour.
Values chosen for a laptop build; every field is overridable.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AudioConfig:
    """Capture format. 16 kHz mono int16 is what Whisper + most VAD expect."""
    sample_rate: int = 16_000
    channels: int = 1
    frame_ms: int = 20                 # frame size fed to VAD/wake (10/20/30)
    dtype: str = "int16"

    @property
    def frame_samples(self) -> int:
        return int(self.sample_rate * self.frame_ms / 1000)


@dataclass
class WakeWordConfig:
    phrases: tuple[str, ...] = ("aura", "hey aura", "okay aura")
    confidence_threshold: float = 0.70    # only wake on high confidence
    cooldown_s: float = 1.5               # ignore re-triggers for this long


@dataclass
class VADConfig:
    aggressiveness: int = 2               # 0..3 (webrtcvad style)
    start_frames: int = 3                 # consecutive speech frames to start
    silence_timeout_s: float = 0.8        # trailing silence that ends speech
    max_utterance_s: float = 15.0         # hard cap to avoid endless recordings
    pre_roll_ms: int = 300                # audio kept before speech onset


@dataclass
class STTConfig:
    model_size: str = "base"              # tiny|base|small|medium|large
    device: str = "auto"                  # auto -> cuda if available else cpu
    compute_type: str = "int8"            # cpu-friendly default
    beam_size: int = 1
    language: str | None = None           # None -> auto-detect


@dataclass
class NoiseConfig:
    enabled: bool = True
    sensitivity: float = 0.5              # 0..1; higher removes more noise
    high_pass_hz: int = 80                # remove low fan/hum rumble


@dataclass
class MicrophoneConfig:
    preferred_name: str | None = None     # substring match; None -> default
    device_index: int | None = None       # explicit index wins if set
    reconnect_interval_s: float = 3.0
    max_reconnect_attempts: int = 0       # 0 = retry forever


@dataclass
class VoiceConfig:
    audio: AudioConfig = field(default_factory=AudioConfig)
    wake_word: WakeWordConfig = field(default_factory=WakeWordConfig)
    vad: VADConfig = field(default_factory=VADConfig)
    stt: STTConfig = field(default_factory=STTConfig)
    noise: NoiseConfig = field(default_factory=NoiseConfig)
    microphone: MicrophoneConfig = field(default_factory=MicrophoneConfig)
    require_wake_word: bool = True        # continuous modes may disable
    default_language: str = "en"
