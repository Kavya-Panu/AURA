from __future__ import annotations

from types import SimpleNamespace

from vision.focus_distraction import (
    DistractionTracker,
    FocusDistractionConfig,
    FocusDistractionMonitor,
)


def _tracker() -> DistractionTracker:
    return DistractionTracker(
        FocusDistractionConfig(
            phone_persist_s=4.0,
            absence_persist_s=30.0,
            warning_cooldown_s=90.0,
        )
    )


def test_phone_requires_persistent_detection() -> None:
    tracker = _tracker()
    assert tracker.observe(phone_visible=True, person_visible=True, now=10.0) is None
    assert tracker.observe(phone_visible=True, person_visible=True, now=13.9) is None
    assert tracker.observe(phone_visible=True, person_visible=True, now=14.0) == "phone"


def test_brief_phone_detection_resets_persistence() -> None:
    tracker = _tracker()
    tracker.observe(phone_visible=True, person_visible=True, now=0.0)
    tracker.observe(phone_visible=False, person_visible=True, now=3.0)
    assert tracker.observe(phone_visible=True, person_visible=True, now=5.0) is None
    assert tracker.observe(phone_visible=True, person_visible=True, now=8.0) is None


def test_warning_cooldown_prevents_nagging() -> None:
    tracker = _tracker()
    tracker.observe(phone_visible=True, person_visible=True, now=0.0)
    assert tracker.observe(phone_visible=True, person_visible=True, now=4.0) == "phone"
    assert tracker.observe(phone_visible=True, person_visible=True, now=20.0) is None
    assert tracker.observe(phone_visible=True, person_visible=True, now=94.0) == "phone"


def test_absence_requires_thirty_seconds() -> None:
    tracker = _tracker()
    tracker.observe(phone_visible=False, person_visible=False, now=20.0)
    assert tracker.observe(phone_visible=False, person_visible=False, now=49.9) is None
    assert tracker.observe(phone_visible=False, person_visible=False, now=50.0) == "absence"


def test_camera_failure_never_counts_as_absence() -> None:
    tracker = _tracker()
    tracker.observe(phone_visible=False, person_visible=False, now=0.0)
    tracker.observe(
        phone_visible=False,
        person_visible=False,
        camera_ok=False,
        now=25.0,
    )
    assert tracker.observe(phone_visible=False, person_visible=False, now=40.0) is None


def test_monitor_warns_for_a_confirmed_cell_phone() -> None:
    warnings: list[str] = []
    monitor = FocusDistractionMonitor(
        focus_active=lambda: True,
        focus_paused=lambda: False,
        snapshot=lambda: object(),
        detect=lambda _frame: [
            SimpleNamespace(label="cell phone", confidence=0.91),
        ],
        person_visible=lambda: True,
        busy=lambda: False,
        on_warning=warnings.append,
        config=FocusDistractionConfig(phone_persist_s=0.0),
    )
    monitor._step()
    assert warnings == ["phone"]


def test_monitor_does_not_run_detection_while_voice_is_busy() -> None:
    calls: list[str] = []
    monitor = FocusDistractionMonitor(
        focus_active=lambda: True,
        focus_paused=lambda: False,
        snapshot=lambda: calls.append("snapshot") or object(),
        detect=lambda _frame: calls.append("detect") or [],
        person_visible=lambda: True,
        busy=lambda: True,
        on_warning=lambda kind: calls.append(kind),
    )
    monitor._step()
    assert calls == []
