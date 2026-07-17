"""
core/lifecycle.py
=================
Startup, health-checking and shutdown for the whole robot.

Future modules (FaceLink, Vision, Voice, Brain, Behaviors...) implement the
:class:`Module` protocol and register with the :class:`LifecycleManager`.
The manager then owns the boring-but-critical sequencing:

    startup:  BOOTING -> initialize() all -> start() all -> IDLE
    shutdown: SHUTDOWN event -> stop() all in REVERSE order -> SHUTDOWN state

A module that fails to initialize raises LifecycleError and aborts startup
(fail fast); a module that fails a health check is reported on the bus so a
future supervisor behavior can decide what to do.
"""
from __future__ import annotations

import threading
from typing import Protocol, runtime_checkable

from core.constants import RobotEvent, RobotState
from core.event_bus import EventBus
from core.exceptions import LifecycleError
from core.logger import get_logger
from core.state_machine import StateMachine

log = get_logger("lifecycle")


@runtime_checkable
class Module(Protocol):
    """Contract every AURA module must satisfy.

    Attributes:
        name: Unique, human-readable module name ("face_link", "vision"...).
    """
    name: str

    def initialize(self) -> None:
        """Acquire resources (open ports, load models). May raise AuraError."""
        ...

    def start(self) -> None:
        """Begin doing work (start threads, begin capture)."""
        ...

    def stop(self) -> None:
        """Stop work and release resources. Must be safe to call twice."""
        ...

    def health_check(self) -> bool:
        """Return True if the module is currently healthy."""
        ...


class LifecycleManager:
    """Registers modules and runs the robot's startup/shutdown sequences."""

    def __init__(self, event_bus: EventBus, state_machine: StateMachine) -> None:
        self._bus = event_bus
        self._sm = state_machine
        self._modules: list[Module] = []
        self._lock = threading.RLock()
        self._started = False

    # ---------------------------------------------------------- registration
    def register(self, module: Module) -> None:
        """Add a module. Order matters: modules start in registration order
        and stop in reverse order (dependencies first up, last down)."""
        with self._lock:
            if any(m.name == module.name for m in self._modules):
                raise LifecycleError("Duplicate module name",
                                     {"name": module.name})
            if self._started:
                raise LifecycleError("Cannot register after startup",
                                     {"name": module.name})
            self._modules.append(module)
        log.info("registered module '%s'", module.name)

    @property
    def modules(self) -> list[str]:
        with self._lock:
            return [m.name for m in self._modules]

    # --------------------------------------------------------------- startup
    def startup(self) -> None:
        """Initialize then start every registered module, then go IDLE."""
        with self._lock:
            if self._started:
                return
            self._started = True
            modules = list(self._modules)

        log.info("=== AURA startup: %d module(s) ===", len(modules))
        self._bus.start()

        for module in modules:                      # fail fast on init
            try:
                module.initialize()
                log.info("initialized '%s'", module.name)
            except Exception as exc:
                self._bus.emit(RobotEvent.MODULE_FAILED,
                               {"module": module.name, "phase": "initialize",
                                "error": str(exc)}, source="lifecycle")
                raise LifecycleError("Module failed to initialize",
                                     {"module": module.name}) from exc

        for module in modules:
            try:
                module.start()
                self._bus.emit(RobotEvent.MODULE_STARTED,
                               {"module": module.name}, source="lifecycle")
            except Exception as exc:
                self._bus.emit(RobotEvent.MODULE_FAILED,
                               {"module": module.name, "phase": "start",
                                "error": str(exc)}, source="lifecycle")
                raise LifecycleError("Module failed to start",
                                     {"module": module.name}) from exc

        if self._sm.can_transition(RobotState.IDLE):
            self._sm.transition(RobotState.IDLE, reason="startup complete")
        self._bus.emit(RobotEvent.STARTUP_COMPLETE,
                       {"modules": [m.name for m in modules]},
                       source="lifecycle")
        log.info("=== AURA startup complete ===")

    # ---------------------------------------------------------------- health
    def health_report(self) -> dict[str, bool]:
        """Run every module's health check; publish and return the results.
        A check that raises counts as unhealthy."""
        report: dict[str, bool] = {}
        with self._lock:
            modules = list(self._modules)
        for module in modules:
            try:
                report[module.name] = bool(module.health_check())
            except Exception:      # noqa: BLE001
                log.exception("health check crashed for '%s'", module.name)
                report[module.name] = False
        self._bus.emit(RobotEvent.HEALTH_REPORT, dict(report),
                       source="lifecycle")
        return report

    # -------------------------------------------------------------- shutdown
    def shutdown(self) -> None:
        """Stop all modules in reverse order and park the state machine."""
        with self._lock:
            if not self._started:
                return
            self._started = False
            modules = list(reversed(self._modules))

        log.info("=== AURA shutdown ===")
        self._bus.emit(RobotEvent.SHUTDOWN_STARTED, source="lifecycle")

        for module in modules:
            try:
                module.stop()
                self._bus.emit(RobotEvent.MODULE_STOPPED,
                               {"module": module.name}, source="lifecycle")
            except Exception:      # noqa: BLE001 - always keep shutting down
                log.exception("module '%s' failed to stop cleanly", module.name)

        if self._sm.can_transition(RobotState.SHUTDOWN):
            self._sm.transition(RobotState.SHUTDOWN, reason="lifecycle")
        self._bus.stop()
        log.info("=== AURA shutdown complete ===")

    # -------------------------------------------------------- context manager
    def __enter__(self) -> "LifecycleManager":
        self.startup()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.shutdown()
