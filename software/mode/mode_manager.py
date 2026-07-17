"""
mode/mode_manager.py
====================
The Mode Manager: owns "what kind of robot AURA is being". It stores the current
and previous mode, validates and performs transitions, publishes the full mode
lifecycle on the Event Bus, supports enter/exit/change callbacks and veto guards
(cancellation), and offers optional plugin + persistence hooks.

It works WITH the core StateMachine, never replacing it: modes are orthogonal to
states. A future module can, for example, subscribe to FOCUS_MODE_STARTED and
then drive the StateMachine through STUDYING/WARNING/BREAK states - that is not
this module's job.

Thread-safe: voice, vision and AI threads may all request mode changes at once;
every transition is performed atomically under a lock.
"""
from __future__ import annotations

import threading
from dataclasses import asdict, is_dataclass
from typing import Any, Callable, Protocol

from core.constants import RobotEvent
from core.event_bus import Event, EventBus
from core.logger import get_logger

from .mode_context import ModeContext, ModeSnapshot
from .mode_events import MODE_REQUEST_EVENT
from .mode_registry import ModeRegistry, registry as default_registry
from .mode_transition import TransitionValidator
from .mode_types import ModeParams, ModeType

log = get_logger("mode.manager")

# (from_mode, to_mode) -> the callback returns False to VETO (cancel) the change.
ModeGuard = Callable[[ModeType, ModeType], bool]
ModeCallback = Callable[[ModeSnapshot], None]


class ModePlugin(Protocol):
    """Optional plugin hook. Future persistence/telemetry plugins implement it."""
    def on_mode_changed(self, snapshot: ModeSnapshot) -> None: ...


class ModePersistence(Protocol):
    """Optional persistence provider (interface only; no storage here)."""
    def save(self, snapshot: ModeSnapshot) -> None: ...
    def load(self) -> ModeType | None: ...


def _params_to_dict(params: ModeParams | None) -> dict[str, Any]:
    """Serialise typed params for event payloads."""
    if params is None:
        return {}
    if is_dataclass(params):
        return asdict(params)
    return {}


class ModeManager:
    """Owns and arbitrates AURA's current mode."""

    def __init__(self,
                 event_bus: EventBus,
                 context: ModeContext | None = None,
                 registry: ModeRegistry | None = None,
                 validator: TransitionValidator | None = None) -> None:
        self._bus = event_bus
        self._ctx = context or ModeContext(ModeType.NORMAL)
        self._registry = registry or default_registry
        self._validator = validator or TransitionValidator()

        self._lock = threading.RLock()
        self._enter_cbs: dict[ModeType, list[ModeCallback]] = {}
        self._exit_cbs: dict[ModeType, list[ModeCallback]] = {}
        self._change_cbs: list[ModeCallback] = []
        self._guards: dict[ModeType, list[ModeGuard]] = {}
        self._plugins: list[ModePlugin] = []
        self._persistence: ModePersistence | None = None
        self._sub_id: int | None = None

    # =====================================================================
    #  Wiring
    # =====================================================================
    def attach(self) -> None:
        """Subscribe to MODE_REQUESTED so other modules can request changes
        without coupling to this class."""
        if self._sub_id is None:
            self._sub_id = self._bus.subscribe(MODE_REQUEST_EVENT,
                                               self._on_request, priority=50)
            log.info("ModeManager attached (current=%s)",
                     self._ctx.current.name)

    def detach(self) -> None:
        if self._sub_id is not None:
            self._bus.unsubscribe(self._sub_id)
            self._sub_id = None

    # =====================================================================
    #  Registration of hooks
    # =====================================================================
    def on_enter(self, mode: ModeType, cb: ModeCallback) -> None:
        self._enter_cbs.setdefault(mode, []).append(cb)

    def on_exit(self, mode: ModeType, cb: ModeCallback) -> None:
        self._exit_cbs.setdefault(mode, []).append(cb)

    def on_change(self, cb: ModeCallback) -> None:
        """Global callback fired after every successful mode change."""
        self._change_cbs.append(cb)

    def add_guard(self, mode: ModeType, guard: ModeGuard) -> None:
        """Register a veto guard: if any guard for the target mode returns
        False, the transition is cancelled and MODE_FAILED is published."""
        self._guards.setdefault(mode, []).append(guard)

    def register_plugin(self, plugin: ModePlugin) -> None:
        self._plugins.append(plugin)

    def set_persistence(self, provider: ModePersistence) -> None:
        self._persistence = provider

    # =====================================================================
    #  Introspection
    # =====================================================================
    @property
    def current_mode(self) -> ModeType:
        return self._ctx.current

    @property
    def previous_mode(self) -> ModeType | None:
        return self._ctx.previous

    def snapshot(self) -> ModeSnapshot:
        return self._ctx.snapshot()

    def can_change(self, to_mode: ModeType) -> bool:
        return self._validator.is_allowed(self._ctx.current, to_mode)

    # =====================================================================
    #  The transition itself
    # =====================================================================
    def request_mode(self,
                     mode: ModeType,
                     *,
                     params: ModeParams | None = None,
                     requested_by: str = "system",
                     reason: str = "",
                     force: bool = False) -> bool:
        """Request a change to ``mode``. Returns True on success.

        Steps: validate -> run veto guards -> exit old -> enter new -> publish
        lifecycle events. Idempotent: requesting the current mode just patches
        its params. Everything happens atomically under the lock.
        """
        with self._lock:
            current = self._ctx.current

            # Idempotent re-entry: update params in place, no transition.
            if mode == current:
                if params is not None:
                    self._ctx._params = params  # direct set; already locked
                    log.debug("re-entered %s with new params", mode.name)
                return True

            if not self._registry.is_registered(mode):
                return self._fail(current, mode, "unregistered mode")

            if not force and not self._validator.is_allowed(current, mode):
                return self._fail(current, mode, "transition not allowed")

            # Veto guards (cancellation).
            for guard in self._guards.get(mode, []):
                try:
                    if guard(current, mode) is False:
                        return self._fail(current, mode, "vetoed by guard")
                except Exception:      # noqa: BLE001
                    log.exception("mode guard crashed for %s", mode.name)
                    return self._fail(current, mode, "guard error")

            resolved = params or self._registry.get(mode).default_params_factory()

            # ---- lifecycle: exiting old ----
            self._emit(RobotEvent.MODE_EXITING, current, extra={"to": mode.name})
            self._run_callbacks(self._exit_cbs.get(current, []),
                                self._ctx.snapshot())

            # ---- lifecycle: entering new ----
            self._emit(RobotEvent.MODE_ENTERING, mode,
                       extra={"from": current.name})
            self._ctx.set_mode(mode, resolved, requested_by, reason)
            snap = self._ctx.snapshot()
            self._run_callbacks(self._enter_cbs.get(mode, []), snap)

            # Per-mode "started" event (e.g. FOCUS_MODE_STARTED) for hardware.
            entry_event = self._registry.get(mode).entry_event
            if entry_event is not None:
                self._bus.emit(entry_event, _params_to_dict(resolved),
                               source="mode")

            # ---- completion events ----
            self._emit(RobotEvent.MODE_EXITED, current)
            self._emit(RobotEvent.MODE_ENTERED, mode,
                       extra={"params": _params_to_dict(resolved),
                              "requested_by": requested_by, "reason": reason})
            self._bus.emit(RobotEvent.MODE_CHANGED,
                           {"from": current.name, "to": mode.name,
                            "reason": reason}, source="mode")

            self._run_callbacks(self._change_cbs, snap)
            self._notify_plugins(snap)
            if self._persistence is not None:
                try:
                    self._persistence.save(snap)
                except Exception:      # noqa: BLE001
                    log.exception("persistence.save failed")

            log.info("mode %s -> %s (by %s%s)", current.name, mode.name,
                     requested_by, f", {reason}" if reason else "")
            return True

    def resume_previous(self, requested_by: str = "system") -> bool:
        """Return to the previous mode if the transition is currently allowed."""
        prev = self._ctx.previous
        if prev is None:
            log.debug("resume_previous: no previous mode")
            return False
        return self.request_mode(prev, requested_by=requested_by,
                                 reason="resume previous")

    def update_params(self, **fields: Any) -> None:
        """Patch parameters of the current mode (e.g. quiz score, progress)."""
        self._ctx.update_params(**fields)

    # =====================================================================
    #  Internals
    # =====================================================================
    def _on_request(self, event: Event) -> None:
        """Handle a MODE_REQUESTED bus event: ``data={'mode': 'FOCUS', ...}``."""
        name = event.data.get("mode")
        try:
            mode = ModeType[name] if isinstance(name, str) else name
        except KeyError:
            log.warning("MODE_REQUESTED with unknown mode '%s'", name)
            return
        if not isinstance(mode, ModeType):
            return
        self.request_mode(
            mode,
            params=event.data.get("params"),
            requested_by=event.data.get("requested_by", event.source),
            reason=event.data.get("reason", ""),
            force=bool(event.data.get("force", False)),
        )

    def _fail(self, current: ModeType, target: ModeType, reason: str) -> bool:
        log.warning("mode change %s -> %s failed: %s",
                    current.name, target.name, reason)
        self._bus.emit(RobotEvent.MODE_FAILED,
                       {"from": current.name, "to": target.name,
                        "reason": reason}, source="mode")
        return False

    def _emit(self, event: RobotEvent, mode: ModeType,
              extra: dict[str, Any] | None = None) -> None:
        data = {"mode": mode.name}
        if extra:
            data.update(extra)
        self._bus.emit(event, data, source="mode")

    @staticmethod
    def _run_callbacks(callbacks: list[ModeCallback],
                       snap: ModeSnapshot) -> None:
        for cb in callbacks:
            try:
                cb(snap)
            except Exception:          # noqa: BLE001 - never break a transition
                log.exception("mode callback failed")

    def _notify_plugins(self, snap: ModeSnapshot) -> None:
        for plugin in self._plugins:
            try:
                plugin.on_mode_changed(snap)
            except Exception:          # noqa: BLE001
                log.exception("mode plugin failed")
