"""
behavior/behaviors.py
=====================
A starter set of concrete behaviors that register themselves. These are generic
personality shells - they set emotions, request states and speak, but contain
NO vision / AI / focus-timer logic (those modules arrive later and will feed
this layer through events).

Importing this module is enough to register every behavior::

    import behavior.behaviors   # noqa: F401  (registers on import)

Each behavior shows the pattern for the real ones you'll add.
"""
from __future__ import annotations

from core.constants import Emotion, RobotState

from .behavior_base import Behavior, Requirements
from .behavior_registry import register
from .behavior_types import BehaviorType, InterruptPolicy, Priority

# Durations kept here as named constants (no magic numbers in logic).
_GREETING_S = 2.0
_WARNING_MAX_S = 30.0
_CELEBRATION_S = 3.0
_ANSWERING_S = 4.0
_ERROR_S = 2.5
_LOW_BATTERY_S = 3.0


@register(BehaviorType.IDLE)
class IdleBehavior(Behavior):
    """Resting behavior. Runs until something with higher priority preempts it.
    Never finishes on its own, so it is AURA's safe default."""
    interrupt_policy = InterruptPolicy.PREEMPT

    def priority(self) -> Priority:
        return Priority.BACKGROUND

    def enter(self) -> None:
        self._actions.request_emotion(Emotion.NORMAL)

    def update(self, dt_s: float) -> bool:
        return False   # idle forever until preempted


@register(BehaviorType.GREETING)
class GreetingBehavior(Behavior):
    """Say hello when the user appears or greets AURA."""

    def priority(self) -> Priority:
        return Priority.NORMAL

    def enter(self) -> None:
        self._actions.request_emotion(Emotion.HAPPY)
        self._actions.request_speech("Hi! I'm AURA.")

    def update(self, dt_s: float) -> bool:
        return self.elapsed_s >= _GREETING_S


@register(BehaviorType.LISTENING)
class ListeningBehavior(Behavior):
    """Active after the wake word. Ends when a question is received (which the
    manager turns into THINKING) or on timeout."""
    max_duration_s = 8.0

    def priority(self) -> Priority:
        return Priority.NORMAL

    def enter(self) -> None:
        self._actions.request_emotion(Emotion.LISTENING)

    def update(self, dt_s: float) -> bool:
        # Stays active until a QUESTION preempts it or max_duration_s elapses.
        return False


@register(BehaviorType.THINKING)
class ThinkingBehavior(Behavior):
    """Shown while the AI processes a question."""
    max_duration_s = 15.0

    def priority(self) -> Priority:
        return Priority.NORMAL

    def enter(self) -> None:
        self._actions.request_emotion(Emotion.THINKING)

    def update(self, dt_s: float) -> bool:
        return False   # ends when ANSWER_READY preempts/queues ANSWERING


@register(BehaviorType.ANSWERING)
class AnsweringBehavior(Behavior):
    """Deliver the answer, then hand back to whatever came before."""

    def priority(self) -> Priority:
        return Priority.ELEVATED

    def enter(self) -> None:
        self._actions.request_emotion(Emotion.NORMAL)

    def update(self, dt_s: float) -> bool:
        return self.elapsed_s >= _ANSWERING_S


@register(BehaviorType.FOCUS)
class FocusBehavior(Behavior):
    """Study-focus session. Long-running; ends when focus is no longer active
    in the context (a future Focus module flips that flag / emits events)."""
    interrupt_policy = InterruptPolicy.PREEMPT

    def priority(self) -> Priority:
        return Priority.NORMAL

    def enter(self) -> None:
        self._actions.request_emotion(Emotion.HAPPY)

    def update(self, dt_s: float) -> bool:
        return not self._actions.snapshot().focus_active


@register(BehaviorType.WARNING)
class WarningBehavior(Behavior):
    """Phone-use warning. HIGH priority so it preempts FOCUS; ends when the
    phone is gone, then FOCUS resumes automatically."""
    interrupt_policy = InterruptPolicy.PREEMPT
    max_duration_s = _WARNING_MAX_S

    def priority(self) -> Priority:
        return Priority.HIGH

    def enter(self) -> None:
        self._actions.request_emotion(Emotion.ANGRY)
        self._actions.request_speech("Put the phone away. Let's finish this.")

    def update(self, dt_s: float) -> bool:
        return not self._actions.snapshot().phone_detected


@register(BehaviorType.CELEBRATION)
class CelebrationBehavior(Behavior):
    """The 🤩 moment when a session finishes."""

    def priority(self) -> Priority:
        return Priority.ELEVATED

    def enter(self) -> None:
        self._actions.request_emotion(Emotion.CELEBRATE)
        self._actions.request_speech("Excellent work! You stayed focused.")

    def update(self, dt_s: float) -> bool:
        return self.elapsed_s >= _CELEBRATION_S


@register(BehaviorType.BREAK)
class BreakBehavior(Behavior):
    """Break between focus blocks."""

    def priority(self) -> Priority:
        return Priority.NORMAL

    def enter(self) -> None:
        self._actions.request_emotion(Emotion.SLEEPY)

    def update(self, dt_s: float) -> bool:
        return not self._actions.snapshot().extra.get("break_active", False)


@register(BehaviorType.LOW_BATTERY)
class LowBatteryBehavior(Behavior):
    """Critical: warn about battery. Preempts almost everything."""
    interrupt_policy = InterruptPolicy.PREEMPT

    def priority(self) -> Priority:
        return Priority.CRITICAL

    def enter(self) -> None:
        self._actions.request_emotion(Emotion.WORRIED)
        self._actions.request_speech("My battery is low.")

    def update(self, dt_s: float) -> bool:
        return self.elapsed_s >= _LOW_BATTERY_S


@register(BehaviorType.ERROR)
class ErrorBehavior(Behavior):
    """Camera/voice error indicator."""

    def priority(self) -> Priority:
        return Priority.CRITICAL

    def enter(self) -> None:
        self._actions.request_emotion(Emotion.ERROR)

    def update(self, dt_s: float) -> bool:
        return self.elapsed_s >= _ERROR_S


@register(BehaviorType.SLEEP)
class SleepBehavior(Behavior):
    """Night mode / shutdown. SYSTEM priority - nothing preempts it."""
    interrupt_policy = InterruptPolicy.REPLACE

    def priority(self) -> Priority:
        return Priority.SYSTEM

    def requirements(self) -> Requirements:
        return Requirements()   # always allowed

    def enter(self) -> None:
        self._actions.request_emotion(Emotion.SLEEP)

    def update(self, dt_s: float) -> bool:
        return False   # stays asleep until explicitly replaced (WAKE)
