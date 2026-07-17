"""
behavior/behavior_types.py
===========================
Enums and small value types for the Behavior System. No logic here - just the
vocabulary every other behavior file shares (keeps ``constants.py`` focused on
core-level enums while behavior-specific ones live beside the behaviors).
"""
from __future__ import annotations

from enum import Enum, IntEnum, auto


class BehaviorType(Enum):
    """Every behavior AURA can run. One value per behavior class."""
    IDLE = auto()
    GREETING = auto()
    LISTENING = auto()
    THINKING = auto()
    ANSWERING = auto()
    FOCUS = auto()
    BOOK_MODE = auto()
    SEARCHING = auto()
    FOLLOW_USER = auto()
    WARNING = auto()
    CELEBRATION = auto()
    BREAK = auto()
    SLEEP = auto()
    WAKE = auto()
    GOODBYE = auto()
    LOW_BATTERY = auto()
    CHARGING = auto()
    ERROR = auto()


class Priority(IntEnum):
    """Higher value preempts lower. IntEnum so behaviors compare with ``>``.

    Gaps left between tiers so new behaviors can slot in without renumbering.
    """
    BACKGROUND = 0     # idle wandering
    LOW = 10           # follow user, searching
    NORMAL = 20        # greeting, listening, focus, book mode
    ELEVATED = 40      # answering, celebration
    HIGH = 60          # warnings (phone use)
    CRITICAL = 80      # low battery, errors
    SYSTEM = 100       # sleep / shutdown / wake - always wins


class InterruptPolicy(Enum):
    """What happens to the running behavior when a higher-priority one wins."""
    PREEMPT = auto()   # pause current, run new, resume current afterwards
    REPLACE = auto()   # cancel current entirely, do not resume
    QUEUE = auto()     # wait: run new only after current finishes
    REJECT = auto()    # drop the new behavior, keep current


class BehaviorStatus(Enum):
    """Lifecycle status of a behavior instance."""
    PENDING = auto()    # created, not yet entered
    RUNNING = auto()
    PAUSED = auto()     # interrupted, may resume
    COMPLETED = auto()  # finished normally
    CANCELLED = auto()  # cancelled or replaced
    FAILED = auto()     # raised during execution
    TIMED_OUT = auto()
