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
    aggressiveness: int = 1               # 0..3; lower is friendlier to soft voices
    start_frames: int = 3                 # consecutive speech frames to start
    silence_timeout_s: float = 1.25       # normal end-of-speech pause
    short_silence_timeout_s: float = 1.80 # extra patience for short phrases
    long_silence_timeout_s: float = 1.55  # breathing/thinking pause in long speech
    short_utterance_s: float = 1.5
    long_utterance_s: float = 4.0
    max_utterance_s: float = 30.0         # hard cap to avoid endless recordings
    pre_roll_ms: int = 500                # preserve the beginning of soft speech
    calibration_s: float = 1.0            # initial room-noise calibration
    wait_for_speech_s: float = 20.0
    min_speech_s: float = 0.25            # reject clicks and accidental noises
    noise_multiplier: float = 2.2
    noise_margin: float = 0.004


@dataclass
class STTConfig:
    model_size: str = "distil-medium.en"  # stronger English/accent recognition
    device: str = "cpu"                  # auto -> cuda if available else cpu
    compute_type: str = "int8"            # cpu-friendly default
    beam_size: int = 5
    best_of: int = 5
    patience: float = 1.2
    repetition_penalty: float = 1.08
    no_repeat_ngram_size: int = 3
    language: str | None = "en"
    min_confidence: float = 0.30
    hotwords: str | None = (
        "AURA ESP32 ESP32-S3 Arduino Jetson Nano OpenCV MediaPipe Whisper "
        "Qwen Ollama PlatformIO ILI9341 ES8311 embedded systems electronics "
        "computer vision robotics"
    )
    # Keep this empty. Whisper can repeat an initial prompt as a hallucinated
    # transcript when the microphone contains only room noise.
    initial_prompt: str | None = None


@dataclass
class NoiseConfig:
    enabled: bool = True
    sensitivity: float = 0.5              # 0..1; higher removes more noise
    high_pass_hz: int = 80                # remove low fan/hum rumble
    auto_gain: bool = True                # lift quiet onboard-microphone speech
    target_rms: float = 0.09              # healthy level for Whisper
    max_gain: float = 8.0                 # avoid amplifying noise without limit
    peak_limit: float = 0.92              # prevent digital clipping


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
