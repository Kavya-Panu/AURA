from __future__ import annotations

import threading
from datetime import datetime, timezone

from brain.reminder_service import ReminderService


def _service(**callbacks) -> ReminderService:
    return ReminderService(
        now=lambda: datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc),
        **callbacks,
    )


def test_remind_me_in_twenty_minutes() -> None:
    service = _service()
    try:
        reply = service.handle("Hey AURA, remind me in twenty minutes")
        assert reply.handled
        assert "20 minutes" in reply.text
        entry = service.entries()[0]
        assert entry.kind == "reminder"
        assert entry.duration_s == 1200
    finally:
        service.close()


def test_reminder_keeps_the_message() -> None:
    service = _service()
    try:
        reply = service.handle("Remind me to drink water in 5 minutes")
        assert "drink water" in reply.text
        assert service.entries()[0].label == "drink water"
    finally:
        service.close()


def test_timer_status_and_cancel() -> None:
    service = _service()
    try:
        assert service.handle("Set a timer for 90 seconds").handled
        assert "remaining" in service.handle("How much time is left?").text
        assert "Cancelled" in service.handle("Cancel the timer").text
        assert not service.entries()
    finally:
        service.close()


def test_bare_timer_number_asks_for_a_unit_instead_of_using_clock_time() -> None:
    service = _service()
    try:
        reply = service.handle("Set a timer for 10")
        assert reply.handled
        assert reply.text == "How long should I set the timer for?"
        assert not service.entries()
    finally:
        service.close()


def test_alarm_at_clock_time() -> None:
    service = _service()
    try:
        reply = service.handle("Set an alarm for 3:30 PM")
        entry = service.entries()[0]
        assert entry.kind == "alarm"
        assert entry.due_at.hour == 15
        assert entry.due_at.minute == 30
        assert reply.text == "Alarm set for 3:30 PM."
    finally:
        service.close()


def test_expiry_calls_spoken_alert_callback() -> None:
    fired = threading.Event()
    seen = []
    service = _service(on_alert=lambda entry: (seen.append(entry), fired.set()))
    try:
        service.schedule(0.05, kind="timer")
        assert fired.wait(1.0)
        assert seen[0].kind == "timer"
        assert not service.entries()
    finally:
        service.close()
