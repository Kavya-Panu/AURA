"""Low-noise distraction monitoring for AURA focus sessions."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterable, Protocol

from core.logger import get_logger

log = get_logger("vision.focus_distraction")


class Observation(Protocol):
    label: str
    confidence: float


@dataclass(frozen=True)
class FocusDistractionConfig:
    """Thresholds chosen to avoid reacting to brief or uncertain detections."""

    poll_interval_s: float = 1.0
    phone_confidence: float = 0.45
    phone_persist_s: float = 4.0
    absence_persist_s: float = 30.0
    warning_cooldown_s: float = 90.0


class DistractionTracker:
    """Convert persistent phone/absence observations into rare warnings."""

    def __init__(
        self,
        config: FocusDistractionConfig,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._clock = clock
        self._phone_since: float | None = None
        self._absence_since: float | None = None
        self._last_warning: dict[str, float] = {}

    def reset(self) -> None:
        self._phone_since = None
        self._absence_since = None

    def observe(
        self,
        *,
        phone_visible: bool,
        person_visible: bool,
        camera_ok: bool = True,
        now: float | None = None,
    ) -> str | None:
        """Return ``phone`` or ``absence`` only after persistence/cooldown."""
        current = self._clock() if now is None else float(now)
        if not camera_ok:
            self.reset()
            return None

        self._phone_since = self._update_since(
            self._phone_since,
            phone_visible,
            current,
        )
        self._absence_since = self._update_since(
            self._absence_since,
            not person_visible,
            current,
        )

        # A visible phone is more actionable than absence, and is checked
        # first when both conditions happen at the same time.
        if self._due("phone", self._phone_since, self._config.phone_persist_s, current):
            self._last_warning["phone"] = current
            self._phone_since = current
            return "phone"
        if self._due(
            "absence",
            self._absence_since,
            self._config.absence_persist_s,
            current,
        ):
            self._last_warning["absence"] = current
            self._absence_since = current
            return "absence"
        return None

    @staticmethod
    def _update_since(
        previous: float | None,
        active: bool,
        now: float,
    ) -> float | None:
        if not active:
            return None
        return now if previous is None else previous

    def _due(
        self,
        kind: str,
        since: float | None,
        persistence_s: float,
        now: float,
    ) -> bool:
        if since is None or now - since < max(0.0, persistence_s):
            return False
        last = self._last_warning.get(kind)
        return last is None or now - last >= max(0.0, self._config.warning_cooldown_s)


class FocusDistractionMonitor:
    """Poll AURA's shared camera only while an active focus session is idle."""

    name = "focus_distraction"
    _PHONE_LABELS = {"cell phone", "mobile phone", "phone", "smartphone"}

    def __init__(
        self,
        *,
        focus_active: Callable[[], bool],
        focus_paused: Callable[[], bool],
        snapshot: Callable[[], object | None],
        detect: Callable[[object], Iterable[Observation]],
        person_visible: Callable[[], bool],
        busy: Callable[[], bool],
        on_warning: Callable[[str], None],
        config: FocusDistractionConfig | None = None,
    ) -> None:
        self._focus_active = focus_active
        self._focus_paused = focus_paused
        self._snapshot = snapshot
        self._detect = detect
        self._person_visible = person_visible
        self._busy = busy
        self._on_warning = on_warning
        self._config = config or FocusDistractionConfig()
        self._tracker = DistractionTracker(self._config)
        self._running = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._running.is_set():
            return
        self._running.set()
        self._thread = threading.Thread(
            target=self._run,
            name="aura-focus-distraction",
            daemon=True,
        )
        self._thread.start()
        log.info("focus distraction monitor started")

    def stop(self) -> None:
        self._running.clear()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        self._tracker.reset()

    def health_check(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        interval = max(0.25, float(self._config.poll_interval_s))
        while self._running.is_set():
            started = time.monotonic()
            try:
                self._step()
            except Exception:  # noqa: BLE001
                # Vision must never stop the focus timer or voice assistant.
                log.exception("focus distraction check failed")
                self._tracker.reset()
            remaining = interval - (time.monotonic() - started)
            if remaining > 0:
                time.sleep(remaining)

    def _step(self) -> None:
        if (
            not self._focus_active()
            or self._focus_paused()
            or self._busy()
        ):
            self._tracker.reset()
            return

        frame = self._snapshot()
        if frame is None:
            self._tracker.observe(
                phone_visible=False,
                person_visible=False,
                camera_ok=False,
            )
            return

        observations = tuple(self._detect(frame))
        phone_visible = any(
            item.label.casefold().strip() in self._PHONE_LABELS
            and float(item.confidence) >= self._config.phone_confidence
            for item in observations
        )
        warning = self._tracker.observe(
            phone_visible=phone_visible,
            person_visible=self._person_visible(),
        )
        if warning:
            log.info("persistent focus distraction detected: %s", warning)
            self._on_warning(warning)
