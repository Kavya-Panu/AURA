"""
behavior/behavior_registry.py
=============================
A registry that maps :class:`BehaviorType` -> behavior class. Behaviors
self-register with the ``@register`` decorator, so adding a new behavior is a
single line and there are zero if/else chains anywhere in the manager.

    @register(BehaviorType.GREETING)
    class GreetingBehavior(Behavior): ...

The manager asks the registry to build instances::

    behavior = registry.create(BehaviorType.GREETING, actions)
"""
from __future__ import annotations

import threading
from typing import Callable, Type

from core.logger import get_logger
from .behavior_base import Behavior, BehaviorActions
from .behavior_types import BehaviorType

log = get_logger("behavior.registry")


class BehaviorRegistry:
    """Thread-safe BehaviorType -> class registry with a factory method."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._classes: dict[BehaviorType, Type[Behavior]] = {}

    def register(self, behavior_type: BehaviorType
                 ) -> Callable[[Type[Behavior]], Type[Behavior]]:
        """Decorator: register ``cls`` as the implementation of ``behavior_type``."""
        def decorator(cls: Type[Behavior]) -> Type[Behavior]:
            with self._lock:
                if behavior_type in self._classes:
                    raise ValueError(
                        f"{behavior_type.name} already registered to "
                        f"{self._classes[behavior_type].__name__}")
                cls.behavior_type = behavior_type
                self._classes[behavior_type] = cls
            log.debug("registered behavior %s -> %s",
                      behavior_type.name, cls.__name__)
            return cls
        return decorator

    def create(self, behavior_type: BehaviorType,
               actions: BehaviorActions) -> Behavior:
        """Instantiate the behavior registered for ``behavior_type``."""
        with self._lock:
            cls = self._classes.get(behavior_type)
        if cls is None:
            raise KeyError(f"No behavior registered for {behavior_type.name}")
        return cls(actions)

    def is_registered(self, behavior_type: BehaviorType) -> bool:
        with self._lock:
            return behavior_type in self._classes

    def registered_types(self) -> list[BehaviorType]:
        with self._lock:
            return list(self._classes)

    def clear(self) -> None:
        """Mainly for tests / hot-reload."""
        with self._lock:
            self._classes.clear()


# Module-level default registry + convenience decorator so behaviors can do:
#   from behavior.behavior_registry import register
registry = BehaviorRegistry()


def register(behavior_type: BehaviorType
             ) -> Callable[[Type[Behavior]], Type[Behavior]]:
    """Register against the default module-level registry."""
    return registry.register(behavior_type)
