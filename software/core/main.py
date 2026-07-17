"""
main.py
=======
AURA composition root.

This is the ONLY place where concrete objects are constructed and wired
together (dependency injection). Modules receive the bus/config/machine they
need - they never import each other.

Right now no real modules exist (Voice, Vision, AI and Behaviors come later),
so a tiny HeartbeatModule demonstrates the contract every future module will
follow: implement the Module protocol, talk only via the EventBus.

Run:  python main.py
Stop: Ctrl+C
"""
from __future__ import annotations

import time

from core.config import AuraConfig
from core.constants import ROBOT_NAME, VERSION, RobotEvent
from core.event_bus import Event, EventBus
from core.lifecycle import LifecycleManager
from core.logger import configure_logging, get_logger
from core.state_machine import build_aura_state_machine
from core.timer import Timer

log = get_logger("main")


class HeartbeatModule:
    """Example module: publishes HEALTH_REPORT ticks on a repeating timer.

    This exists purely to demonstrate the Module protocol + EventBus wiring.
    Delete it once real modules (face_link, vision, voice...) are registered.
    """

    name = "heartbeat"

    def __init__(self, bus: EventBus, interval_s: float = 5.0) -> None:
        self._bus = bus
        self._interval = interval_s
        self._timer: Timer | None = None
        self._ticks = 0

    def initialize(self) -> None:
        log.debug("heartbeat: nothing to acquire")

    def start(self) -> None:
        self._timer = Timer(self._interval, self._tick,
                            repeating=True, name="heartbeat").start()

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.cancel()

    def health_check(self) -> bool:
        return self._timer is not None and self._timer.is_running()

    def _tick(self, _timer: Timer) -> None:
        self._ticks += 1
        self._bus.emit(RobotEvent.TIMER_EXPIRED,
                       {"name": "heartbeat", "tick": self._ticks},
                       source=self.name)


def main() -> None:
    # 1. Configuration (defaults; overlay a file with AuraConfig.from_file).
    config = AuraConfig()
    config.validate()
    configure_logging(config.logging)
    log.info("%s v%s booting", ROBOT_NAME, VERSION)

    # 2. Core plumbing.
    bus = EventBus()
    machine = build_aura_state_machine(bus)
    lifecycle = LifecycleManager(bus, machine)

    # 3. Observability: log every event that crosses the bus (wildcard sub).
    def trace(event: Event) -> None:
        log.debug("EVENT %-18s from %-10s %s",
                  event.type.name, event.source, event.data)
    bus.subscribe_all(trace)

    # 4. Register modules. Future: FaceLink, Vision, Voice, Brain, Behaviors.
    lifecycle.register(HeartbeatModule(bus))

    # 5. Run.
    with lifecycle:                      # startup() ... shutdown()
        log.info("state=%s - press Ctrl+C to shut down", machine.state.name)
        try:
            while True:
                time.sleep(1.0)
        except KeyboardInterrupt:
            log.info("Ctrl+C received")


if __name__ == "__main__":
    main()
