# AURA Behavior System

The decision-making layer between perception and action — AURA's personality.
It turns events (phone detected, wake word, focus finished…) into intent
(which behavior runs, which emotion to request, whether to speak, wait,
interrupt, resume). It sits on top of the existing Core Framework and changes
none of it.

**Verified:** 16 behavior tests + 28 core tests = **44 passing**, plus a live
end-to-end run of the focus→phone→warning→resume flow.

## Where it sits

```
Voice / Vision / Sensors  (future, foreign threads)
          │ publish events
          ▼
      ┌─────────────────────────────────────────────┐
      │              Event Bus (core)               │
      └───────────────────┬─────────────────────────┘
                          │ subscribe
                          ▼
      ┌─────────────────────────────────────────────┐
      │            BEHAVIOR MANAGER                  │  ← this module
      │  arbitration: priority / preempt / queue /  │
      │  resume-stack / timeout / tick loop         │
      │                                             │
      │  reads ► BehaviorContext (world model)      │
      │  builds ► BehaviorRegistry (type → class)   │
      └───────┬───────────────────────┬─────────────┘
              │ request_state()        │ request_emotion() / request_speech()
              ▼                        ▼  (events only — never hardware)
      State Machine (core)      Emotion / Speech / Action Managers (future)
                                        ▼
                                Hardware Manager → ESP32   (future)
```

The Behavior Manager **requests** state transitions (the FSM validates them)
and **emits** emotion/speech intents on the bus. It never mutates state and
never touches hardware — exactly as specified.

## Files

| File | Role |
|---|---|
| `behavior_types.py` | `BehaviorType`, `Priority` (IntEnum tiers), `InterruptPolicy` (PREEMPT/REPLACE/QUEUE/REJECT), `BehaviorStatus`. |
| `behavior_events.py` | `BehaviorTrigger` + `TRIGGER_TO_EVENT` mapping onto core `RobotEvent`s (no parallel event system). |
| `behavior_context.py` | Thread-safe world model; `snapshot()` returns an immutable `ContextSnapshot`. |
| `behavior_base.py` | Abstract `Behavior` (enter/execute/update/exit/interrupt/resume/cancel/priority/requirements) + `BehaviorActions` facade + `Requirements`. |
| `behavior_registry.py` | `@register(BehaviorType.X)` self-registration; factory `create()`. No if/else chains. |
| `behavior_manager.py` | The arbitration core + tick loop + bus/FSM integration. |
| `behaviors.py` | A starter set of concrete behaviors (generic shells; no vision/AI/focus logic). |
| `tests/` | Switching, priority, preemption, interrupt+resume, queue, timeout, cancellation, event-driven flows. |

## Execution model

* **Priority** — every behavior returns a `Priority`. Higher preempts lower.
* **Preemption** — a higher-priority behavior pauses the current one and pushes
  it onto a **resume stack**; when the interrupter ends, the paused behavior
  resumes exactly where it was. (IDLE, the `BACKGROUND` fallback, is never
  parked — it's regenerated.)
* **Queue** — an equal-priority behavior with `QUEUE` policy waits, then runs
  when the current one finishes.
* **Replace** — `REPLACE` cancels the current behavior outright (no resume),
  used by SYSTEM-level behaviors like SLEEP.
* **Timeout** — `max_duration_s` caps any behavior; the base class enforces it.
* **Tick loop** — a single manager thread steps the active behavior at 20 Hz,
  so behaviors run single-threaded and stay simple while perception events
  arrive safely from other threads.

### The two canonical flows (both covered by tests)

```
Wake word → LISTENING → (question) THINKING → (answer) ANSWERING → IDLE

FOCUS running → PHONE_DETECTED → WARNING preempts (FOCUS parked)
             → PHONE_GONE → WARNING ends → FOCUS resumes automatically
```

## Creating a new behavior (one file, one decorator)

```python
from core.constants import Emotion
from behavior.behavior_base import Behavior, Requirements
from behavior.behavior_registry import register
from behavior.behavior_types import BehaviorType, Priority, InterruptPolicy

@register(BehaviorType.FOLLOW_USER)
class FollowUserBehavior(Behavior):
    interrupt_policy = InterruptPolicy.PREEMPT
    max_duration_s = None                      # runs until preempted

    def priority(self) -> Priority:
        return Priority.LOW

    def requirements(self) -> Requirements:
        return Requirements(needs_person=True)  # only when a person is present

    def enter(self) -> None:
        self._actions.request_emotion(Emotion.CURIOUS)

    def update(self, dt_s: float) -> bool:
        ctx = self._actions.snapshot()          # read the world
        return not ctx.person_present           # finish when the person leaves
```

That's the whole integration — no manager edits, no if/else. The manager
discovers it through the registry and arbitrates it by its `priority()`.

## What a behavior may and may not do

* **May:** `self._actions.request_emotion(...)`, `request_state(...)`,
  `request_speech(...)`, `emit(event_name, **data)`, `snapshot()`.
* **Must not:** import Voice/Vision/AI/Hardware, mutate state, or call another
  behavior. All coupling goes through events and the context.

## Running the tests

```bash
python -m unittest discover -s behavior/tests   # 16 behavior tests
python -m unittest discover -s tests            # 28 core tests
```

## Scope

This is the behavior layer only. Voice, Vision, AI, Emotion Manager, Hardware
Manager and the Focus Manager are separate modules that will publish events
into (and subscribe to intents from) this layer. The behaviors in
`behaviors.py` are personality shells ready to be fleshed out as those modules
come online.
