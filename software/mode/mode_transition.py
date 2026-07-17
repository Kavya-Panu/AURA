"""
mode/mode_transition.py
=======================
Validates whether a mode change is allowed. The default policy makes NORMAL the
hub: you switch between "working" modes by returning to NORMAL first, which is
exactly the behaviour the spec calls for.

    NORMAL -> FOCUS            allowed   (NORMAL reaches everything)
    FOCUS  -> TRANSLATION      blocked   (must return to NORMAL first)
    FOCUS  -> NORMAL           allowed   (working modes can always go home)
    NIGHT  -> FOCUS            blocked   (must wake to NORMAL first)
    <any>  -> CHARGING/NIGHT   allowed   (physical/system modes are reachable
                                          from anywhere)

All rules are data, so they extend with one call: ``validator.allow(a, b)``,
``validator.allow_from_anywhere(m)``, or ``validator.disallow(a, b)``.
"""
from __future__ import annotations

import threading

from .mode_types import ModeType

# Modes reachable from ANY mode (system/physical). NIGHT: user can say goodnight
# mid-task; CHARGING: plugging in; MAINTENANCE: diagnostics.
_REACHABLE_FROM_ANYWHERE: frozenset[ModeType] = frozenset({
    ModeType.NIGHT, ModeType.CHARGING, ModeType.MAINTENANCE,
})


def build_default_rules() -> dict[ModeType, set[ModeType]]:
    """Construct the default allow-map described above."""
    all_modes = set(ModeType)
    rules: dict[ModeType, set[ModeType]] = {}

    # NORMAL is the hub: it can reach every other mode.
    rules[ModeType.NORMAL] = all_modes - {ModeType.NORMAL}

    # Working modes: home to NORMAL, plus the always-reachable system modes.
    working = all_modes - {ModeType.NORMAL} - _REACHABLE_FROM_ANYWHERE
    for mode in working:
        rules[mode] = {ModeType.NORMAL} | _REACHABLE_FROM_ANYWHERE - {mode}

    # System/physical modes: constrained exits.
    rules[ModeType.NIGHT] = {ModeType.NORMAL, ModeType.CHARGING}
    rules[ModeType.CHARGING] = {ModeType.NORMAL, ModeType.NIGHT}
    rules[ModeType.MAINTENANCE] = {ModeType.NORMAL}

    return rules


class TransitionValidator:
    """Thread-safe, extensible mode-transition allow-list."""

    def __init__(self, rules: dict[ModeType, set[ModeType]] | None = None) -> None:
        self._lock = threading.RLock()
        self._rules = rules if rules is not None else build_default_rules()

    def is_allowed(self, from_mode: ModeType, to_mode: ModeType) -> bool:
        """True if ``from_mode -> to_mode`` is permitted. Same-mode is False
        (there is nothing to transition); the manager treats that as a no-op."""
        if from_mode == to_mode:
            return False
        with self._lock:
            return to_mode in self._rules.get(from_mode, set())

    def allowed_targets(self, from_mode: ModeType) -> set[ModeType]:
        with self._lock:
            return set(self._rules.get(from_mode, set()))

    # ------------------------------------------------------------- extension
    def allow(self, from_mode: ModeType, to_mode: ModeType) -> None:
        with self._lock:
            self._rules.setdefault(from_mode, set()).add(to_mode)

    def disallow(self, from_mode: ModeType, to_mode: ModeType) -> None:
        with self._lock:
            self._rules.get(from_mode, set()).discard(to_mode)

    def allow_from_anywhere(self, to_mode: ModeType) -> None:
        """Make ``to_mode`` reachable from every other mode."""
        with self._lock:
            for from_mode in ModeType:
                if from_mode != to_mode:
                    self._rules.setdefault(from_mode, set()).add(to_mode)
