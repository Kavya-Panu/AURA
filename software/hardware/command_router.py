"""
hardware/command_router.py
==========================
CommandRouter is the dispatch layer between high-level driver calls and the
HardwareManager. It receives hardware commands, validates them, prioritizes them,
routes each to the correct driver by target, queues them on a worker thread,
prevents conflicting commands (per-target coalescing so a newer command for the
same target supersedes a queued older one), and supports cancellation.

It routes ONLY through the HardwareManager (via the drivers/sink it was given) -
it never touches serial. Thread-safe; asynchronous and non-blocking.
"""
from __future__ import annotations

import heapq
import itertools
import threading
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable

from core.logger import get_logger

from .device_types import CommandPriority
from .hardware_exceptions import CommandError

log = get_logger("hardware.router")


class CommandStatus(Enum):
    QUEUED = auto()
    SENT = auto()
    CANCELLED = auto()
    SUPERSEDED = auto()
    REJECTED = auto()


@dataclass
class HardwareCommand:
    """A routed command. `target` names the logical actuator (e.g. "face",
    "servo:pan", "led", "propeller"); `handler` performs the send when executed;
    `conflict_key` groups commands that supersede one another (defaults to
    target)."""
    target: str
    handler: Callable[[], None]
    priority: CommandPriority = CommandPriority.NORMAL
    conflict_key: str | None = None
    coalesce: bool = True
    command_id: int = 0
    status: CommandStatus = CommandStatus.QUEUED

    @property
    def key(self) -> str:
        return self.conflict_key or self.target


@dataclass(order=True)
class _Entry:
    priority: int
    sequence: int
    command: HardwareCommand = field(compare=False)
    live: bool = field(compare=False, default=True)


class CommandRouter:
    """Validates, prioritizes, queues, de-conflicts and dispatches hardware
    commands on a worker thread. Thread-safe."""

    def __init__(self, *, max_queue: int = 256,
                 validator: Callable[[HardwareCommand], bool] | None = None) -> None:
        self._max_queue = max_queue
        self._validator = validator
        self._heap: list[_Entry] = []
        self._counter = itertools.count()
        self._by_key: dict[str, _Entry] = {}       # newest live entry per key
        self._cv = threading.Condition()
        self._running = threading.Event()
        self._worker: threading.Thread | None = None
        self._ids = itertools.count(1)
        self._sent = 0
        self._cancelled = 0

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._running.is_set():
            return
        self._running.set()
        self._worker = threading.Thread(target=self._run, name="hw-router",
                                        daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._running.clear()
        with self._cv:
            self._cv.notify_all()
        if self._worker is not None:
            self._worker.join(timeout=2.0)
            self._worker = None

    # -------------------------------------------------------------- submit
    def submit(self, command: HardwareCommand) -> int:
        """Validate + enqueue a command. Returns its command_id. Raises
        CommandError if invalid or the queue is full."""
        if self._validator is not None and not self._validator(command):
            command.status = CommandStatus.REJECTED
            raise CommandError(f"command rejected for target '{command.target}'")
        with self._cv:
            if len(self._heap) >= self._max_queue:
                raise CommandError("command queue full")
            command.command_id = next(self._ids)
            # conflict handling: a newer command for the same key supersedes the
            # older queued one (prevents conflicting/stale actuator commands).
            if command.coalesce:
                prev = self._by_key.get(command.key)
                if prev is not None and prev.live:
                    prev.live = False
                    prev.command.status = CommandStatus.SUPERSEDED
            entry = _Entry(int(command.priority), next(self._counter), command)
            heapq.heappush(self._heap, entry)
            if command.coalesce:
                self._by_key[command.key] = entry
            self._cv.notify()
            return command.command_id

    def cancel(self, target: str) -> int:
        """Cancel all queued commands for a target/key. Returns count cancelled."""
        cancelled = 0
        with self._cv:
            for entry in self._heap:
                if entry.live and entry.command.key == target:
                    entry.live = False
                    entry.command.status = CommandStatus.CANCELLED
                    cancelled += 1
            self._by_key.pop(target, None)
        self._cancelled += cancelled
        return cancelled

    def cancel_all(self) -> int:
        with self._cv:
            cancelled = sum(1 for e in self._heap if e.live)
            for e in self._heap:
                e.live = False
                e.command.status = CommandStatus.CANCELLED
            self._by_key.clear()
        self._cancelled += cancelled
        return cancelled

    # -------------------------------------------------------------- worker
    def _run(self) -> None:
        while self._running.is_set():
            with self._cv:
                while self._running.is_set() and not self._has_live():
                    self._cv.wait(timeout=0.2)
                if not self._running.is_set():
                    break
                entry = self._next_live()
            if entry is None:
                continue
            self._dispatch(entry.command)

    def _has_live(self) -> bool:
        return any(e.live for e in self._heap)

    def _next_live(self) -> _Entry | None:
        while self._heap:
            entry = heapq.heappop(self._heap)
            if entry.live:
                if self._by_key.get(entry.command.key) is entry:
                    self._by_key.pop(entry.command.key, None)
                return entry
        return None

    def _dispatch(self, command: HardwareCommand) -> None:
        try:
            command.handler()
            command.status = CommandStatus.SENT
            self._sent += 1
        except Exception as exc:                        # noqa: BLE001
            command.status = CommandStatus.REJECTED
            log.warning("command for '%s' failed: %s", command.target, exc)

    # --------------------------------------------------------------- stats
    @property
    def queued(self) -> int:
        with self._cv:
            return sum(1 for e in self._heap if e.live)

    def stats(self) -> dict[str, int]:
        return {"sent": self._sent, "cancelled": self._cancelled,
                "queued": self.queued}
