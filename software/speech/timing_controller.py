"""
speech/timing_controller.py
===========================
Manages conversation rhythm: a brief thinking pause before answering, a small
pre-speech delay, natural gaps between sentences, and a post-speech settle. Pure
timing - it sleeps via an injected callable so tests run instantly.
"""
from __future__ import annotations

import re
import time
from typing import Callable

from .speech_config import TimingConfig

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


class TimingController:
    """Provides the pauses that make speech feel natural."""

    def __init__(self, config: TimingConfig,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._cfg = config
        self._sleep = sleep

    def thinking_pause(self) -> None:
        self._sleep(self._cfg.thinking_pause_s)

    def pre_speech_delay(self) -> None:
        self._sleep(self._cfg.pre_speech_delay_s)

    def post_speech_delay(self) -> None:
        self._sleep(self._cfg.post_speech_delay_s)

    def sentence_gap(self) -> None:
        self._sleep(self._cfg.sentence_gap_s)

    def split_sentences(self, text: str) -> list[str]:
        """Split text into sentences for paced delivery."""
        parts = [s.strip() for s in _SENTENCE_SPLIT.split(text.strip()) if s.strip()]
        return parts or ([text.strip()] if text.strip() else [])
