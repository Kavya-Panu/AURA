"""Timers, alarms, and reminders for AURA.

Scheduling stays on the laptop so it remains accurate while the ESP32 is busy
with audio.  The ESP32 receives only the nearest countdown and renders it from
its own millisecond clock.  Multiple future alerts are supported.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from core.logger import get_logger

log = get_logger("brain.reminders")


@dataclass(frozen=True)
class ScheduledAlert:
    alert_id: int
    kind: str
    label: str
    duration_s: float
    due_at: datetime
    deadline: float

    def remaining(self, now: float | None = None) -> float:
        return max(0.0, self.deadline - (time.monotonic() if now is None else now))


@dataclass(frozen=True)
class ReminderReply:
    handled: bool
    text: str = ""


DisplayCallback = Callable[[ScheduledAlert, int], None]
AlertCallback = Callable[[ScheduledAlert], None]
ClearCallback = Callable[[], None]


class ReminderService:
    """Thread-safe scheduler with a small spoken-language command parser."""

    _KEYWORD = re.compile(
        r"\b(?:timer|countdown|alarm|remind|reminder|wake\s+me|time\s+left|"
        r"time\s+(?:is\s+)?left|time\s+remaining)\b",
        re.IGNORECASE,
    )
    _CANCEL = re.compile(
        r"\b(?:cancel|delete|remove|stop|clear|turn\s+off)\b",
        re.IGNORECASE,
    )
    _QUERY = re.compile(
        r"\b(?:how\s+(?:much|long).{0,15}time|time\s+(?:is\s+)?left|"
        r"time\s+remaining|list|show|what)\b",
        re.IGNORECASE,
    )
    _NUMBER_WORDS = {
        "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4,
        "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
        "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
        "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
        "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
        "forty": 40, "fifty": 50, "sixty": 60, "ninety": 90,
    }
    _NUMBER = (
        r"(?:\d+(?:\.\d+)?|a|an|one|two|three|four|five|six|seven|eight|"
        r"nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|"
        r"seventeen|eighteen|nineteen|twenty(?:[- ](?:one|two|three|four|"
        r"five|six|seven|eight|nine))?|thirty(?:[- ](?:one|two|three|four|"
        r"five|six|seven|eight|nine))?|forty(?:[- ](?:one|two|three|four|"
        r"five|six|seven|eight|nine))?|fifty(?:[- ](?:one|two|three|four|"
        r"five|six|seven|eight|nine))?|sixty|ninety)"
    )
    _DURATION = re.compile(
        rf"(?P<value>{_NUMBER})\s*(?P<unit>seconds?|secs?|minutes?|mins?|"
        rf"hours?|hrs?|days?)\b",
        re.IGNORECASE,
    )
    _CLOCK_TIME = re.compile(
        r"\b(?:at|for)\s+(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?"
        r"\s*(?P<ampm>a\.?m\.?|p\.?m\.?)?\b",
        re.IGNORECASE,
    )

    def __init__(
        self,
        *,
        on_display: DisplayCallback | None = None,
        on_alert: AlertCallback | None = None,
        on_clear: ClearCallback | None = None,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    ) -> None:
        self._on_display = on_display or (lambda _entry, _seconds: None)
        self._on_alert = on_alert or (lambda _entry: None)
        self._on_clear = on_clear or (lambda: None)
        self._clock = clock
        self._now = now
        self._condition = threading.Condition(threading.RLock())
        self._entries: list[ScheduledAlert] = []
        self._next_id = 1
        self._closed = False
        self._displayed_id: int | None = None
        self._worker = threading.Thread(
            target=self._run,
            name="aura-reminders",
            daemon=True,
        )
        self._worker.start()

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        self._worker.join(timeout=2.0)
        try:
            self._on_clear()
        except Exception:  # hardware may already be shutting down
            log.debug("countdown display was already unavailable during shutdown")

    def handles(self, text: str) -> bool:
        return bool(self._KEYWORD.search(self._normalise(text)))

    def handle(self, text: str) -> ReminderReply:
        normalized = self._normalise(text)
        if not self.handles(normalized):
            return ReminderReply(False)

        if self._CANCEL.search(normalized):
            kind = self._kind_from_text(normalized, allow_default=False)
            count = self.cancel(kind)
            if count == 0:
                noun = kind or "timer or reminder"
                return ReminderReply(True, f"There is no active {noun} to cancel.")
            noun = kind if count == 1 and kind else "alert"
            suffix = "" if count == 1 else "s"
            return ReminderReply(True, f"Cancelled {count} {noun}{suffix}.")

        if self._QUERY.search(normalized) and not re.search(
            r"\b(?:set|start|create|remind|alarm\s+(?:for|at)|timer\s+for)\b",
            normalized,
        ):
            return ReminderReply(True, self.status_text())

        kind = self._kind_from_text(normalized)
        duration_s = self._parse_duration(normalized)
        due_at: datetime | None = None
        # A bare timer such as "set a timer for 10" is missing a unit.  It
        # must not be interpreted as ten o'clock (which can silently create a
        # many-hour timer).  Clock-time parsing is reserved for alarms and
        # reminders; ambiguous timers receive a clarification question.
        if duration_s is None and kind in {"alarm", "reminder"}:
            due_at = self._parse_clock_time(normalized)
            if due_at is not None:
                duration_s = max(1.0, (due_at - self._now()).total_seconds())
        if duration_s is None:
            question = (
                "When should I remind you?"
                if kind == "reminder"
                else f"How long should I set the {kind} for?"
            )
            return ReminderReply(True, question)

        label = self._extract_label(normalized, kind)
        entry = self.schedule(duration_s, kind=kind, label=label, due_at=due_at)
        return ReminderReply(True, self._confirmation(entry))

    def schedule(
        self,
        duration_s: float,
        *,
        kind: str = "timer",
        label: str = "",
        due_at: datetime | None = None,
    ) -> ScheduledAlert:
        duration = float(duration_s)
        if duration <= 0 or duration > 31 * 24 * 3600:
            raise ValueError("duration must be between 1 second and 31 days")
        kind = kind if kind in {"timer", "reminder", "alarm"} else "timer"
        now_wall = self._now()
        entry = ScheduledAlert(
            self._next_id,
            kind,
            label.strip(),
            duration,
            due_at or now_wall + timedelta(seconds=duration),
            self._clock() + duration,
        )
        with self._condition:
            self._next_id += 1
            self._entries.append(entry)
            self._entries.sort(key=lambda item: item.deadline)
            self._condition.notify_all()
        self._refresh_display()
        log.info("scheduled %s #%s for %.1fs: %s", kind, entry.alert_id, duration, label)
        return entry

    def cancel(self, kind: str | None = None) -> int:
        with self._condition:
            before = len(self._entries)
            if kind is None:
                self._entries.clear()
            else:
                self._entries = [item for item in self._entries if item.kind != kind]
            removed = before - len(self._entries)
            self._condition.notify_all()
        self._refresh_display(force=True)
        return removed

    def entries(self) -> tuple[ScheduledAlert, ...]:
        with self._condition:
            return tuple(self._entries)

    def status_text(self) -> str:
        active = self.entries()
        if not active:
            return "You have no active timers, alarms, or reminders."
        first = active[0]
        remaining = self._human_duration(round(first.remaining(self._clock())))
        if len(active) == 1:
            return f"Your {first.kind} has {remaining} remaining."
        return (
            f"You have {len(active)} active alerts. The next {first.kind} "
            f"has {remaining} remaining."
        )

    def _run(self) -> None:
        while True:
            expired: ScheduledAlert | None = None
            with self._condition:
                if self._closed:
                    return
                if not self._entries:
                    self._condition.wait()
                    continue
                first = self._entries[0]
                wait_s = first.deadline - self._clock()
                if wait_s > 0:
                    self._condition.wait(timeout=min(wait_s, 60.0))
                    continue
                expired = self._entries.pop(0)
                self._displayed_id = None
            if expired is not None:
                log.info("%s #%s expired", expired.kind, expired.alert_id)
                try:
                    self._on_alert(expired)
                except Exception:  # noqa: BLE001
                    log.exception("alert callback failed")
                self._refresh_display(force=True)

    def _refresh_display(self, *, force: bool = False) -> None:
        with self._condition:
            first = self._entries[0] if self._entries else None
            if first is None:
                changed = force or self._displayed_id is not None
                self._displayed_id = None
            else:
                changed = force or self._displayed_id != first.alert_id
                self._displayed_id = first.alert_id
                seconds = max(1, int(round(first.remaining(self._clock()))))
        if first is None:
            if changed:
                self._on_clear()
        elif changed:
            self._on_display(first, seconds)

    @classmethod
    def parse_duration(cls, text: str) -> float | None:
        """Parse a spoken duration for timers and other timed AURA modes."""
        if re.search(r"\bhalf\s+(?:an?\s+)?hour\b", text):
            return 1800.0
        total = 0.0
        found = False
        for match in cls._DURATION.finditer(text):
            value = cls._number_value(match.group("value"))
            if value is None:
                continue
            unit = match.group("unit").casefold()
            multiplier = 1
            if unit.startswith(("min", "minute")):
                multiplier = 60
            elif unit.startswith(("h", "hour")):
                multiplier = 3600
            elif unit.startswith("day"):
                multiplier = 86400
            total += value * multiplier
            found = True
        return total if found and total > 0 else None

    def _parse_duration(self, text: str) -> float | None:
        return self.parse_duration(text)

    def _parse_clock_time(self, text: str) -> datetime | None:
        match = self._CLOCK_TIME.search(text)
        if not match:
            return None
        hour = int(match.group("hour"))
        minute = int(match.group("minute") or 0)
        if minute > 59:
            return None
        ampm = re.sub(r"[^apm]", "", (match.group("ampm") or "").casefold())
        now = self._now()
        tomorrow = bool(re.search(r"\btomorrow\b", text))
        if ampm:
            if hour < 1 or hour > 12:
                return None
            hour = hour % 12 + (12 if ampm.startswith("p") else 0)
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if tomorrow or target <= now:
                target += timedelta(days=1)
            return target
        if hour > 23:
            return None
        if hour <= 12:
            candidates = []
            for candidate_hour in {hour % 12, hour % 12 + 12}:
                candidate = now.replace(
                    hour=candidate_hour,
                    minute=minute,
                    second=0,
                    microsecond=0,
                )
                if tomorrow:
                    candidate += timedelta(days=1)
                elif candidate <= now:
                    candidate += timedelta(days=1)
                candidates.append(candidate)
            return min(candidates)
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if tomorrow or target <= now:
            target += timedelta(days=1)
        return target

    @classmethod
    def _number_value(cls, value: str) -> float | None:
        try:
            return float(value)
        except ValueError:
            pass
        words = value.casefold().replace("-", " ").split()
        if not words:
            return None
        numbers = [cls._NUMBER_WORDS.get(word) for word in words]
        if any(number is None for number in numbers):
            return None
        return float(sum(number for number in numbers if number is not None))

    @staticmethod
    def _kind_from_text(text: str, *, allow_default: bool = True) -> str | None:
        if re.search(r"\b(?:remind|reminder)\b", text):
            return "reminder"
        if re.search(r"\b(?:alarm|wake\s+me)\b", text):
            return "alarm"
        if re.search(r"\b(?:timer|countdown)\b", text):
            return "timer"
        return "timer" if allow_default else None

    @staticmethod
    def _extract_label(text: str, kind: str) -> str:
        if kind != "reminder":
            return ""
        match = re.search(
            r"\bremind\s+me(?:\s+to|\s+about)?\s+(.*?)"
            r"(?=\s+(?:in|at)\s+|\s+tomorrow\b|$)",
            text,
            re.IGNORECASE,
        )
        if not match:
            return ""
        label = match.group(1).strip(" ,.!?")
        return "" if re.fullmatch(r"(?:in|at)?", label) else label

    def _confirmation(self, entry: ScheduledAlert) -> str:
        duration = self._human_duration(round(entry.duration_s))
        if entry.kind == "reminder":
            if entry.label:
                return f"Okay. I will remind you to {entry.label} in {duration}."
            return f"Okay. I set a reminder for {duration}."
        if entry.kind == "alarm" and entry.duration_s > 3600:
            clock_text = entry.due_at.strftime("%I:%M %p").lstrip("0")
            return f"Alarm set for {clock_text}."
        return f"{entry.kind.capitalize()} set for {duration}."

    @staticmethod
    def alert_text(entry: ScheduledAlert) -> str:
        if entry.kind == "reminder":
            return f"Reminder: {entry.label}." if entry.label else "Your reminder is due."
        if entry.kind == "alarm":
            return "Your alarm is going off."
        return "Your timer is finished."

    @staticmethod
    def _human_duration(seconds: int) -> str:
        seconds = max(0, int(seconds))
        parts: list[str] = []
        for size, name in ((86400, "day"), (3600, "hour"), (60, "minute")):
            value, seconds = divmod(seconds, size)
            if value:
                parts.append(f"{value} {name}{'' if value == 1 else 's'}")
        if seconds or not parts:
            parts.append(f"{seconds} second{'' if seconds == 1 else 's'}")
        return " and ".join(parts[:2])

    @staticmethod
    def _normalise(text: str) -> str:
        value = " ".join(str(text).strip().split())
        value = re.sub(
            r"^(?:(?:hey|hi|okay|ok)\s+)?(?:aura|ora|or\s+a)\b[\s,.:;!?-]*",
            "",
            value,
            flags=re.IGNORECASE,
        )
        return value.strip().casefold()
