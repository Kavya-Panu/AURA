"""Timed, voice-controlled study sessions for AURA."""
from __future__ import annotations

import math
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable

from core.logger import get_logger

from .reminder_service import ReminderService

log = get_logger("brain.focus")


@dataclass(frozen=True)
class FocusReply:
    handled: bool
    text: str = ""


StartCallback = Callable[[int], None]
SimpleCallback = Callable[[], None]


class FocusStudyService:
    """Own one focus session and understand its natural voice commands."""

    DEFAULT_MINUTES = 25
    MAX_SECONDS = 8 * 60 * 60

    _START = re.compile(
        r"\b(?:(?:start|begin|activate|enter|turn\s+on|help\s+me|"
        r"time\s+to|i\s+want\s+to|let(?:'|\s)*s)\s+(?:a\s+)?"
        r"(?:focus|study|studying|concentration)(?:\s+(?:mode|session))?"
        r"|(?:focus|study)\s+(?:mode|session|for\b))",
        re.IGNORECASE,
    )
    _STOP = re.compile(
        r"\b(?:stop|end|exit|cancel|finish)\b.{0,24}"
        r"\b(?:focus|study|studying|session|mode)\b|"
        r"\b(?:focus|study)\b.{0,20}\b(?:stop|off|done)\b",
        re.IGNORECASE,
    )
    _PAUSE = re.compile(
        r"\b(?:pause|hold)\b.{0,20}\b(?:focus|study|session|mode)\b",
        re.IGNORECASE,
    )
    _RESUME = re.compile(
        r"\b(?:resume|continue|restart)\b.{0,20}"
        r"\b(?:focus|study|studying|session|mode)\b|\bback\s+to\s+work\b",
        re.IGNORECASE,
    )
    _STATUS = re.compile(
        r"\b(?:focus|study)\s+status\b|"
        r"\b(?:how\s+(?:much|long)|what)\b.{0,28}"
        r"\b(?:focus\s+)?time\b.{0,12}\b(?:left|remaining)\b|"
        r"\b(?:time\s+(?:left|remaining))\b.{0,20}\b(?:focus|study)\b",
        re.IGNORECASE,
    )
    _CHANGE = re.compile(
        r"\b(?:make|change|set|extend)\b.{0,24}\b(?:seconds?|minutes?|hours?)\b",
        re.IGNORECASE,
    )

    def __init__(
        self,
        *,
        on_start: StartCallback | None = None,
        on_pause: SimpleCallback | None = None,
        on_resume: StartCallback | None = None,
        on_stop: SimpleCallback | None = None,
        on_complete: SimpleCallback | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._on_start = on_start or (lambda _seconds: None)
        self._on_pause = on_pause or (lambda: None)
        self._on_resume = on_resume or (lambda _seconds: None)
        self._on_stop = on_stop or (lambda: None)
        self._on_complete = on_complete or (lambda: None)
        self._clock = clock
        self._condition = threading.Condition(threading.RLock())
        self._active = False
        self._paused = False
        self._deadline = 0.0
        self._paused_remaining = 0.0
        self._closed = False
        self._worker = threading.Thread(
            target=self._run,
            name="aura-focus",
            daemon=True,
        )
        self._worker.start()

    @property
    def active(self) -> bool:
        with self._condition:
            return self._active

    @property
    def paused(self) -> bool:
        with self._condition:
            return self._active and self._paused

    def remaining_seconds(self) -> int:
        with self._condition:
            return self._remaining_locked()

    def handles(self, text: str) -> bool:
        value = self._normalise(text)
        active = self.active
        explicit_focus = bool(re.search(r"\b(?:focus|study|studying)\b", value))
        return bool(
            self._START.search(value)
            or self._STOP.search(value)
            or self._PAUSE.search(value)
            or self._RESUME.search(value)
            or (self._STATUS.search(value) and (active or explicit_focus))
            or (active and self._CHANGE.search(value))
        )

    def handle(self, text: str) -> FocusReply:
        value = self._normalise(text)
        if not self.handles(value):
            return FocusReply(False)

        if self._STOP.search(value):
            if not self.stop():
                return FocusReply(True, "There is no active focus session.")
            return FocusReply(True, "Focus mode stopped.")

        if self._PAUSE.search(value):
            if not self.pause():
                return FocusReply(True, "There is no running focus session to pause.")
            return FocusReply(True, "Focus session paused.")

        if self._RESUME.search(value):
            if not self.resume():
                return FocusReply(True, "There is no paused focus session.")
            return FocusReply(True, "Focus session resumed.")

        if self._STATUS.search(value):
            return FocusReply(True, self.status_text())

        duration = ReminderService.parse_duration(value)
        if self._CHANGE.search(value) and self.active:
            if duration is None:
                return FocusReply(True, "How long should I make the focus session?")
            self.start(duration)
            return FocusReply(
                True,
                f"Focus time changed to {self._human_duration(duration)}.",
            )

        seconds = duration or self.DEFAULT_MINUTES * 60
        self.start(seconds)
        return FocusReply(
            True,
            f"Focus mode started for {self._human_duration(seconds)}. Let's study.",
        )

    def start(self, seconds: float) -> None:
        duration = float(seconds)
        if duration <= 0 or duration > self.MAX_SECONDS:
            raise ValueError("focus duration must be between 1 second and 8 hours")
        with self._condition:
            self._active = True
            self._paused = False
            self._paused_remaining = 0.0
            self._deadline = self._clock() + duration
            self._condition.notify_all()
        self._call(self._on_start, max(1, int(math.ceil(duration))))
        log.info("focus session started for %.1fs", duration)

    def pause(self) -> bool:
        with self._condition:
            if not self._active or self._paused:
                return False
            self._paused_remaining = max(0.0, self._deadline - self._clock())
            self._paused = True
            self._condition.notify_all()
        self._call(self._on_pause)
        log.info("focus session paused with %.1fs remaining", self._paused_remaining)
        return True

    def resume(self) -> bool:
        with self._condition:
            if not self._active or not self._paused:
                return False
            remaining = max(1.0, self._paused_remaining)
            self._deadline = self._clock() + remaining
            self._paused_remaining = 0.0
            self._paused = False
            self._condition.notify_all()
        seconds = max(1, int(math.ceil(remaining)))
        self._call(self._on_resume, seconds)
        log.info("focus session resumed with %ss remaining", seconds)
        return True

    def stop(self) -> bool:
        with self._condition:
            if not self._active:
                return False
            self._active = False
            self._paused = False
            self._deadline = 0.0
            self._paused_remaining = 0.0
            self._condition.notify_all()
        self._call(self._on_stop)
        log.info("focus session stopped")
        return True

    def status_text(self) -> str:
        with self._condition:
            if not self._active:
                return "There is no active focus session."
            remaining = self._remaining_locked()
            paused = self._paused
        if paused:
            return (
                "Your focus session is paused with "
                f"{self._human_duration(remaining)} remaining."
            )
        return (
            "Your focus session has "
            f"{self._human_duration(remaining)} remaining."
        )

    def close(self) -> None:
        with self._condition:
            was_active = self._active
            self._active = False
            self._paused = False
            self._closed = True
            self._condition.notify_all()
        self._worker.join(timeout=2.0)
        if was_active:
            self._call(self._on_stop)

    def _remaining_locked(self) -> int:
        if not self._active:
            return 0
        value = self._paused_remaining if self._paused else self._deadline - self._clock()
        return max(0, int(math.ceil(value)))

    def _run(self) -> None:
        while True:
            complete = False
            with self._condition:
                if self._closed:
                    return
                if not self._active or self._paused:
                    self._condition.wait()
                    continue
                remaining = self._deadline - self._clock()
                if remaining > 0:
                    self._condition.wait(timeout=remaining)
                    continue
                self._active = False
                self._deadline = 0.0
                complete = True
            if complete:
                log.info("focus session complete")
                self._call(self._on_complete)

    @staticmethod
    def _call(callback: Callable, *args) -> None:
        try:
            callback(*args)
        except Exception:  # noqa: BLE001
            log.exception("focus callback failed")

    @staticmethod
    def _human_duration(seconds: float) -> str:
        value = max(0, int(round(seconds)))
        hours, value = divmod(value, 3600)
        minutes, secs = divmod(value, 60)
        parts: list[str] = []
        if hours:
            parts.append(f"{hours} hour{'' if hours == 1 else 's'}")
        if minutes:
            parts.append(f"{minutes} minute{'' if minutes == 1 else 's'}")
        if secs and not hours:
            parts.append(f"{secs} second{'' if secs == 1 else 's'}")
        return " and ".join(parts[:2]) or "0 seconds"

    @staticmethod
    def _normalise(text: str) -> str:
        value = " ".join(str(text).strip().split())
        value = re.sub(
            r"^(?:(?:hey|hi|okay|ok)\s+)?(?:aura|ora|or\s+a)\b[\s,.:;!?-]*",
            "",
            value,
            flags=re.IGNORECASE,
        )
        value = re.sub(r"[^a-zA-Z0-9.'-]+", " ", value)
        return " ".join(value.casefold().split())
