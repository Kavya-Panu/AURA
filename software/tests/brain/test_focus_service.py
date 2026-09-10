from __future__ import annotations

import threading
import time

from brain.focus_service import FocusStudyService


def test_starts_default_focus_session_from_natural_phrases() -> None:
    starts: list[int] = []
    service = FocusStudyService(on_start=starts.append)
    try:
        for phrase in ("Hey AURA, start focus mode", "AURA, let's study"):
            reply = service.handle(phrase)
            assert reply.handled
            assert "25 minutes" in reply.text
            assert service.active
            service.stop()
        assert starts == [1500, 1500]
    finally:
        service.close()


def test_custom_duration_pause_resume_status_and_stop() -> None:
    events: list[object] = []
    service = FocusStudyService(
        on_start=lambda seconds: events.append(("start", seconds)),
        on_pause=lambda: events.append("pause"),
        on_resume=lambda seconds: events.append(("resume", seconds)),
        on_stop=lambda: events.append("stop"),
    )
    try:
        reply = service.handle("Start study mode for twenty minutes")
        assert "20 minutes" in reply.text
        assert events[0] == ("start", 1200)
        assert service.handle("focus status").text.startswith(
            "Your focus session has 20 minutes remaining."
        )
        assert service.handle("pause focus mode").text == "Focus session paused."
        assert service.paused
        assert service.handle("focus status").text.startswith(
            "Your focus session is paused with 20 minutes remaining."
        )
        assert service.handle("resume focus mode").text == "Focus session resumed."
        assert not service.paused
        assert service.handle("stop focus mode").text == "Focus mode stopped."
        assert not service.active
        assert events[1] == "pause"
        assert events[2][0] == "resume"
        assert events[3] == "stop"
    finally:
        service.close()


def test_duration_can_be_changed_during_focus() -> None:
    starts: list[int] = []
    service = FocusStudyService(on_start=starts.append)
    try:
        service.handle("start focus for 10 minutes")
        reply = service.handle("make it 30 minutes")
        assert reply.handled
        assert reply.text == "Focus time changed to 30 minutes."
        assert starts == [600, 1800]
    finally:
        service.close()


def test_completion_callback_fires_once() -> None:
    completed = threading.Event()
    calls = []
    service = FocusStudyService(
        on_complete=lambda: (calls.append("complete"), completed.set()),
    )
    try:
        service.start(0.05)
        assert completed.wait(1.0)
        time.sleep(0.05)
        assert calls == ["complete"]
        assert not service.active
    finally:
        service.close()


def test_unrelated_questions_are_not_intercepted() -> None:
    service = FocusStudyService()
    try:
        assert not service.handle("What is depth of focus in photography?").handled
        assert not service.handle("Explain Ohm's law").handled
    finally:
        service.close()
