"""
core/event_bus.py
=================
The nervous system of AURA. Modules NEVER call each other directly - they
publish events and subscribe to the ones they care about, exactly like ROS
topics.

Example (future modules)::

    bus.subscribe(RobotEvent.PHONE_DETECTED, behavior.on_phone, priority=10)
    bus.subscribe(RobotEvent.PHONE_DETECTED, emotions.on_phone)
    ...
    bus.publish(Event(RobotEvent.PHONE_DETECTED, {"seconds": 61}, source="vision"))

Features:
* subscribe / unsubscribe / publish
* per-subscriber priority (higher runs first)
* wildcard subscription (``subscribe_all``) - used by loggers/recorders
* thread safety (RLock around the registry, handlers called outside locks
  where possible)
* optional asynchronous delivery: ``publish_async`` enqueues onto a
  priority queue drained by a background dispatcher thread
* handler exceptions are caught and logged, never crash the bus
"""
from __future__ import annotations

import itertools
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from core.constants import RobotEvent
from core.logger import get_logger

log = get_logger("event_bus")

EventHandler = Callable[["Event"], None]


@dataclass(frozen=True)
class Event:
    """A single message on the bus.

    Attributes:
        type: What happened (from :class:`RobotEvent`).
        data: Structured payload, e.g. ``{"seconds": 61}``.
        priority: Queue priority for async delivery (higher = sooner).
        source: Name of the publishing module, for logs and debugging.
        timestamp: Creation time (``time.monotonic()``).
    """
    type: RobotEvent
    data: dict[str, Any] = field(default_factory=dict)
    priority: int = 0
    source: str = "unknown"
    timestamp: float = field(default_factory=time.monotonic)


@dataclass(frozen=True)
class _Subscription:
    sub_id: int
    handler: EventHandler
    priority: int


class EventBus:
    """Thread-safe publish/subscribe hub with sync and async delivery."""

    _WILDCARD = "__ALL__"

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subs: dict[RobotEvent | str, list[_Subscription]] = {}
        self._id_iter = itertools.count(1)
        self._seq = itertools.count()          # FIFO tie-break in the queue
        self._queue: queue.PriorityQueue = queue.PriorityQueue()
        self._worker: threading.Thread | None = None
        self._running = threading.Event()

    # ------------------------------------------------------------- subscribe
    def subscribe(self, event_type: RobotEvent, handler: EventHandler,
                  priority: int = 0) -> int:
        """Register ``handler`` for ``event_type``. Returns a subscription id
        that can be passed to :meth:`unsubscribe`. Higher priority handlers
        are invoked first."""
        sub = _Subscription(next(self._id_iter), handler, priority)
        with self._lock:
            handlers = self._subs.setdefault(event_type, [])
            handlers.append(sub)
            handlers.sort(key=lambda s: -s.priority)
        log.debug("subscribed #%d to %s (priority %d)",
                  sub.sub_id, event_type.name, priority)
        return sub.sub_id

    def subscribe_all(self, handler: EventHandler, priority: int = 0) -> int:
        """Register ``handler`` for EVERY event (loggers, recorders)."""
        sub = _Subscription(next(self._id_iter), handler, priority)
        with self._lock:
            handlers = self._subs.setdefault(self._WILDCARD, [])
            handlers.append(sub)
            handlers.sort(key=lambda s: -s.priority)
        log.debug("subscribed #%d to ALL events (priority %d)",
                  sub.sub_id, priority)
        return sub.sub_id

    def unsubscribe(self, sub_id: int) -> bool:
        """Remove a subscription by id. Returns True if it was found."""
        with self._lock:
            for key, handlers in self._subs.items():
                for sub in handlers:
                    if sub.sub_id == sub_id:
                        handlers.remove(sub)
                        log.debug("unsubscribed #%d from %s", sub_id,
                                  key if isinstance(key, str) else key.name)
                        return True
        return False

    # --------------------------------------------------------------- publish
    def publish(self, event: Event) -> int:
        """Deliver ``event`` synchronously to all matching handlers, in
        priority order. Returns the number of handlers invoked. Handler
        exceptions are logged and swallowed so one bad module cannot take
        down the bus."""
        with self._lock:   # snapshot so handlers can (un)subscribe safely
            targets = list(self._subs.get(event.type, []))
            targets += self._subs.get(self._WILDCARD, [])
        targets.sort(key=lambda s: -s.priority)

        log.debug("publish %s from %s data=%s -> %d handler(s)",
                  event.type.name, event.source, event.data, len(targets))

        delivered = 0
        for sub in targets:
            try:
                sub.handler(event)
                delivered += 1
            except Exception:            # noqa: BLE001 - bus must survive
                log.exception("handler #%d failed for %s",
                              sub.sub_id, event.type.name)
        return delivered

    def emit(self, event_type: RobotEvent, data: dict[str, Any] | None = None,
             *, source: str = "unknown", priority: int = 0) -> int:
        """Convenience wrapper: build the Event and publish synchronously."""
        return self.publish(Event(event_type, data or {}, priority, source))

    # ---------------------------------------------------------- async worker
    def start(self) -> None:
        """Start the background dispatcher used by :meth:`publish_async`."""
        if self._running.is_set():
            return
        self._running.set()
        self._worker = threading.Thread(target=self._drain, name="event-bus",
                                        daemon=True)
        self._worker.start()
        log.info("event bus dispatcher started")

    def stop(self, timeout_s: float = 2.0) -> None:
        """Stop the dispatcher, draining pending events first."""
        if not self._running.is_set():
            return
        self._running.clear()
        self._queue.put((0, next(self._seq), None))     # wake the worker
        if self._worker is not None:
            self._worker.join(timeout=timeout_s)
        log.info("event bus dispatcher stopped")

    def publish_async(self, event: Event) -> None:
        """Enqueue ``event`` for delivery by the dispatcher thread.
        Higher ``event.priority`` is delivered first; ties are FIFO."""
        self._queue.put((-event.priority, next(self._seq), event))

    def _drain(self) -> None:
        while self._running.is_set() or not self._queue.empty():
            try:
                _, _, event = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if event is not None:
                self.publish(event)
            self._queue.task_done()
