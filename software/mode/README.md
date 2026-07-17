# AURA Mode Management System

Owns **what kind of robot AURA is being** — a layer that sits beside (not on top
of) the core StateMachine and changes only on explicit request.

**Verified:** 27 mode tests passing (71 across the whole project), plus a live
run of every transition rule in the spec.

## Mode vs State — the whole point

| | **State** (core) | **Mode** (this module) |
|---|---|---|
| Answers | *What is AURA doing right now?* | *What kind of robot is AURA being?* |
| Examples | LISTENING → THINKING → ANSWERING | FOCUS, TRANSLATION, NIGHT |
| Changes | constantly, automatically | rarely, only on explicit request |
| Owner | `core.state_machine` | `mode.mode_manager` |

One mode contains many states over its lifetime:

```
MODE:  ┌──────────────────── FOCUS ────────────────────┐
STATE: LISTENING → THINKING → ANSWERING → STUDYING → WARNING → STUDYING → BREAK
```

The mode stays FOCUS the whole time; the state churns underneath it.

## Architecture

```
 Voice / Vision / AI  ──emit MODE_REQUESTED──►┐
                                              ▼
                                   ┌──────────────────────┐
                                   │      Event Bus       │ (core)
                                   └──────────┬───────────┘
                                              │ subscribe
                                              ▼
        ┌───────────────────────────────────────────────────────────┐
        │                     MODE MANAGER                           │
        │  request_mode() → validate → guards → exit → enter → emit  │
        │                                                            │
        │  TransitionValidator   ModeRegistry   ModeContext          │
        │  (NORMAL = hub)        (12 modes +    (current/previous,    │
        │                         params +      params, timing)      │
        │                         entry events)                      │
        └───────┬─────────────────────────────────────┬─────────────┘
                │ publishes MODE_* + FOCUS_MODE_STARTED│
                ▼                                      ▼
     Behavior System / Emotion / Hardware   (subscribe; never coupled)
```

Mode Manager and StateMachine are independent. A future Focus module subscribes
to `FOCUS_MODE_STARTED`, then drives the StateMachine through STUDYING/WARNING/
BREAK — that orchestration is *not* this module's job.

## Execution flow of a transition

1. `request_mode(FOCUS, params=…)` (direct) **or** `MODE_REQUESTED` on the bus.
2. Idempotency check — requesting the current mode just patches its params.
3. Registration + validation via `TransitionValidator`. Illegal → `MODE_FAILED`.
4. Veto **guards** for the target run; any returning `False` cancels → `MODE_FAILED`.
5. `MODE_EXITING` (old) → exit callbacks → `MODE_ENTERING` (new).
6. Context updated (previous, params, entered-time), enter callbacks run.
7. Per-mode entry event (e.g. `FOCUS_MODE_STARTED`) fires with params.
8. `MODE_EXITED`, `MODE_ENTERED`, `MODE_CHANGED`; change callbacks + plugins +
   optional persistence.

Everything in steps 2–8 happens atomically under one lock, so simultaneous
requests from voice/vision/AI threads can never interleave into a half-changed
mode.

## Transition rules (default)

NORMAL is the hub. Working modes must return to NORMAL before switching to
another working mode. System/physical modes (NIGHT, CHARGING, MAINTENANCE) are
reachable from anywhere; NIGHT and CHARGING only exit to each other or NORMAL.

```
NORMAL → FOCUS            ✓        FOCUS → TRANSLATION   ✗ (hub via NORMAL)
FOCUS  → NORMAL           ✓        NIGHT → FOCUS         ✗ (wake to NORMAL first)
<any>  → CHARGING/NIGHT   ✓        TRANSLATION → NORMAL  ✓
```

Extend in one line: `validator.allow(FOCUS, TRANSLATION)`,
`validator.allow_from_anywhere(MAINTENANCE)`, or pass `force=True` to a request.

## Examples

```python
from mode.mode_manager import ModeManager
from mode.mode_types import ModeType, TranslationParams, FocusParams

mgr = ModeManager(bus); mgr.attach()

mgr.request_mode(ModeType.FOCUS, params=FocusParams(duration_minutes=90))
mgr.request_mode(ModeType.NORMAL)                       # hub
mgr.request_mode(ModeType.TRANSLATION,
                 params=TranslationParams(source_language="English",
                                          target_language="Japanese",
                                          bidirectional=True))
mgr.update_params(target_language="French")            # live param patch
mgr.resume_previous()                                   # back to NORMAL

# Decoupled request from another module:
bus.emit(RobotEvent.MODE_REQUESTED, {"mode": "NIGHT"}, source="voice")
```

## Adding a new mode

1. Add a member to `ModeType` in `mode_types.py`.
2. (Optional) add a typed `…Params` dataclass and register its factory in
   `DEFAULT_PARAM_FACTORIES`.
3. (Optional) add a per-mode entry event in `mode_events.MODE_ENTRY_EVENT`.
4. `build_default_registry()` auto-registers it; adjust transition rules if the
   defaults don't fit (`validator.allow(...)`).

No `ModeManager` changes required.

## Files

`mode_types.py` (ModeType + typed params) · `mode_events.py` (bus mapping) ·
`mode_transition.py` (extensible validator) · `mode_context.py` (current/
previous/params/timing) · `mode_registry.py` (definitions for all 12 modes) ·
`mode_manager.py` (the manager) · `tests/`.

## Tests

```bash
python -m unittest discover -s mode/tests    # 27 tests
```

Covers mode changes, invalid transitions, parameters, previous-mode resume,
callbacks + veto guards, event publishing, and 8-thread concurrent safety.

## Scope

Mode management only. Voice, AI, Emotion, Hardware, Focus-timer, book animation
and phone detection are separate modules that will *subscribe* to `MODE_*` /
`FOCUS_MODE_STARTED` and *request* modes via `MODE_REQUESTED` — none of them are
implemented here.
