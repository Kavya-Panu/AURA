"""
core/config.py
==============
Central configuration. Every tunable in AURA lives in one of these dataclasses
- no magic numbers anywhere else in the codebase.

* Sensible defaults are defined inline, so ``AuraConfig()`` alone is valid.
* :meth:`AuraConfig.from_file` overlays values from a JSON file.
* :meth:`AuraConfig.validate` raises :class:`ConfigurationError` early instead
  of letting bad values crash a module mid-run.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

from core.exceptions import ConfigurationError


@dataclass
class SerialConfig:
    """ESP32 face-engine link."""
    port: str = "COM5"                  # e.g. /dev/ttyUSB0 on Linux
    baudrate: int = 115200
    timeout_s: float = 0.1
    reconnect_interval_s: float = 3.0


@dataclass
class CameraConfig:
    index: int = 0
    width: int = 640
    height: int = 480
    fps: int = 30
    detect_every_n_frames: int = 5      # run heavy vision every Nth frame


@dataclass
class AudioConfig:
    microphone_index: int | None = None  # None = system default
    sample_rate: int = 16000
    wake_word: str = "aura"
    voice_rate: int = 175                # TTS words-per-minute
    voice_volume: float = 1.0


@dataclass
class FocusConfig:
    default_minutes: int = 120           # "focus mode" default = 2 h
    min_minutes: int = 15
    max_minutes: int = 240
    phone_warn_minutes: int = 30         # phone seen this long -> warnings
    break_minutes: int = 5


@dataclass
class AIConfig:
    provider: str = "anthropic"          # anthropic | openai | ollama
    model: str = "claude-sonnet-4-6"
    max_tokens: int = 300
    answer_style: str = "short"          # short, clear answers by default


@dataclass
class EmotionConfig:
    transition_ms: int = 350             # face cross-fade time
    celebrate_hold_s: float = 2.6
    idle_return_s: float = 8.0           # revert to NORMAL after this long


@dataclass
class LoggingConfig:
    debug: bool = False
    file_enabled: bool = True
    directory: str = "logs"
    filename: str = "aura.log"
    max_bytes: int = 1_000_000
    backup_count: int = 5


@dataclass
class AuraConfig:
    """Top-level configuration object injected into every module."""
    serial: SerialConfig = field(default_factory=SerialConfig)
    camera: CameraConfig = field(default_factory=CameraConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    focus: FocusConfig = field(default_factory=FocusConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    emotion: EmotionConfig = field(default_factory=EmotionConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    # ---------------------------------------------------------------- loading
    @classmethod
    def from_file(cls, path: str | Path) -> "AuraConfig":
        """Load config from JSON, overlaying defaults. Unknown keys raise
        ConfigurationError so typos never fail silently."""
        path = Path(path)
        if not path.exists():
            raise ConfigurationError("Config file not found", {"path": str(path)})
        try:
            raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigurationError("Config file is not valid JSON",
                                     {"path": str(path), "error": str(exc)}) from exc

        cfg = cls()
        for section_name, section_values in raw.items():
            if not hasattr(cfg, section_name):
                raise ConfigurationError("Unknown config section",
                                         {"section": section_name})
            section = getattr(cfg, section_name)
            if not is_dataclass(section) or not isinstance(section_values, dict):
                raise ConfigurationError("Malformed config section",
                                         {"section": section_name})
            valid_keys = {f.name for f in fields(section)}
            for key, value in section_values.items():
                if key not in valid_keys:
                    raise ConfigurationError("Unknown config key",
                                             {"section": section_name, "key": key})
                setattr(section, key, value)
        cfg.validate()
        return cfg

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2),
                              encoding="utf-8")

    # ------------------------------------------------------------- validation
    def validate(self) -> None:
        """Sanity-check values; raise ConfigurationError on the first problem."""
        if self.serial.baudrate <= 0:
            raise ConfigurationError("serial.baudrate must be > 0")
        if self.camera.fps <= 0 or self.camera.fps > 120:
            raise ConfigurationError("camera.fps must be in 1..120",
                                     {"fps": self.camera.fps})
        if self.camera.detect_every_n_frames < 1:
            raise ConfigurationError("camera.detect_every_n_frames must be >= 1")
        if not (self.focus.min_minutes
                <= self.focus.default_minutes
                <= self.focus.max_minutes):
            raise ConfigurationError(
                "focus.default_minutes must lie within min..max",
                {"min": self.focus.min_minutes,
                 "default": self.focus.default_minutes,
                 "max": self.focus.max_minutes})
        if not 0.0 <= self.audio.voice_volume <= 1.0:
            raise ConfigurationError("audio.voice_volume must be 0..1")
        if self.ai.provider not in ("anthropic", "openai", "ollama"):
            raise ConfigurationError("ai.provider must be anthropic|openai|ollama",
                                     {"provider": self.ai.provider})
        if self.ai.max_tokens <= 0:
            raise ConfigurationError("ai.max_tokens must be > 0")
