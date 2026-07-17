"""
speech/speech_config.py
=======================
Configuration for the Speech Manager. Pure data (dataclasses); no behaviour and
no magic numbers elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TimingConfig:
    """Conversation rhythm (seconds)."""
    thinking_pause_s: float = 0.4        # brief 'think' before speaking
    pre_speech_delay_s: float = 0.1
    sentence_gap_s: float = 0.25         # pause between sentences
    comma_gap_s: float = 0.12
    post_speech_delay_s: float = 0.1


@dataclass
class MouthConfig:
    """Viseme animation cadence."""
    frame_interval_s: float = 0.08       # how often the mouth shape updates
    chars_per_second: float = 14.0       # rough speaking rate for duration est.
    min_duration_s: float = 0.4


@dataclass
class ExpressionConfig:
    """Facial-expression behaviour while speaking."""
    blink_interval_s: float = 3.5
    hold_expression: bool = True         # keep one expression per utterance
    smile_on_greeting: bool = True


@dataclass
class SpeechConfig:
    """Top-level Speech configuration."""
    default_profile: str = "friendly"
    default_engine: str = "pyttsx3"
    timing: TimingConfig = field(default_factory=TimingConfig)
    mouth: MouthConfig = field(default_factory=MouthConfig)
    expression: ExpressionConfig = field(default_factory=ExpressionConfig)
    max_queue: int = 32
    enable_mouth_animation: bool = True
    enable_expressions: bool = True
