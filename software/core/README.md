# AURA Core — Software Foundation

The architectural skeleton of the AURA companion robot. **No voice, AI,
vision or behaviors live here** — this layer exists so those modules can be
added later without ever touching each other. Think ROS, not chatbot.

Verified: `python -m unittest discover -s tests` → **28/28 passing**, and
`main.py` boots BOOTING → IDLE with a demo heartbeat module.

---

## Architecture

```
                        ┌─────────────────────────────┐
                        │          main.py            │  composition root:
                        │  builds & injects everything │  the ONLY wiring point
                        └──────────────┬──────────────┘
                                       │
     ┌──────────────┬──────────────────┼──────────────────┬─────────────┐
     ▼              ▼                  ▼                  ▼             ▼
┌─────────┐  ┌────────────┐   ┌───────────────┐   ┌───────────┐  ┌─────────┐
│ config  │  │   logger   │   │   EventBus    │   │ State     │  │ Lifecycle│
│ (data-  │  │ console +  │   │  pub / sub    │◄──┤ Machine   │  │ Manager │
│ classes)│  │ rot. file  │   │  priorities   │   │ validated │  │ start / │
└─────────┘  └────────────┘   │  thread-safe  │   │ + history │  │ health /│
                              └───────▲───────┘   └───────────┘  │ shutdown│
                                      │                          └────┬────┘
                 ═════════ all future modules plug in here ═══════════╪═════
                                      │                               │
              ┌────────┬──────────┬───┴────┬──────────┬───────────────┘
              ▼        ▼          ▼        ▼          ▼
          FaceLink   Vision     Voice    Brain     Behaviors      (LATER)
          (ESP32)   (camera)  (mic/tts)  (LLM)   (focus mode...)
```

**The rule that keeps this clean:** modules never import or call each other.
Vision publishes `PHONE_DETECTED`; whoever cares (behaviors, emotions,
logger) subscribes. Adding a module never means editing another one.

## Folder guide

| Path | What it is |
|---|---|
| `main.py` | Composition root. Builds config → logger → bus → FSM → lifecycle, registers modules, runs. |
| `core/event_bus.py` | Thread-safe pub/sub. Subscriber priorities, wildcard subscription, sync `publish()` + async `publish_async()` with a priority-queue dispatcher thread. Handler exceptions are logged, never fatal. |
| `core/state_machine.py` | Validated FSM (illegal transitions raise `StateTransitionError`), entry/exit callbacks, bounded history, publishes `STATE_CHANGED`. Ships with the AURA transition map (BOOTING…SHUTDOWN, incl. FOCUS↔LISTENING for mid-session questions). |
| `core/logger.py` | `configure_logging()` once; `get_logger("vision")` everywhere. Console + rotating file, per-module names, runtime `set_debug()`. |
| `core/config.py` | All tunables as dataclasses (`serial`, `camera`, `audio`, `focus`, `ai`, `emotion`, `logging`). JSON overlay via `AuraConfig.from_file`, strict validation, unknown keys rejected. |
| `core/constants.py` | Every enum: `RobotState`, `RobotEvent`, `Emotion` (values = ESP32 serial tokens!), `FaceCommand`, `HardwareType`, `VERSION`. |
| `core/timer.py` | Pausable one-shot/repeating timers on daemon threads: `pause/resume/cancel`, `elapsed()/remaining()`, monotonic-clock based. |
| `core/exceptions.py` | `AuraError` base + Configuration/Hardware/Vision/Voice/AI/Communication/StateTransition/Lifecycle errors, all with structured context. |
| `core/lifecycle.py` | `Module` protocol (`initialize/start/stop/health_check`) + `LifecycleManager`: init all → start all → IDLE; stop in reverse on shutdown; health reports on the bus. Context-manager friendly. |
| `tests/` | 28 unit tests covering bus, FSM, timer, logger. |

## Writing a future module (the contract)

```python
from core.constants import RobotEvent, Emotion
from core.event_bus import Event, EventBus
from core.logger import get_logger

log = get_logger("face_link")

class FaceLinkModule:                      # satisfies core.lifecycle.Module
    name = "face_link"

    def __init__(self, bus: EventBus, cfg):        # dependencies INJECTED
        self._bus, self._cfg = bus, cfg

    def initialize(self):                  # open the serial port here
        self._bus.subscribe(RobotEvent.EMOTION_CHANGED, self._on_emotion)

    def start(self): ...
    def stop(self): ...
    def health_check(self) -> bool: return True

    def _on_emotion(self, event: Event):
        emotion = Emotion[event.data["emotion"]]
        # serial.write(f"{emotion.value}\n")   # token matches the ESP32 engine
```

Register it in `main.py`: `lifecycle.register(FaceLinkModule(bus, config.serial))`.
That is the *only* line that changes.

## Best practices baked in

1. **Dependency injection** — modules receive the bus/config; nothing reaches
   for globals. Trivial to unit-test with fakes.
2. **Fail fast, degrade gracefully** — bad config and illegal transitions
   raise immediately; runtime handler/callback errors are contained + logged.
3. **No magic numbers** — if you're typing a literal outside `config.py` or
   `constants.py`, stop.
4. **Thread safety by default** — bus, FSM and timers all lock internally;
   future camera/mic threads can publish from anywhere.
5. **Reverse-order shutdown** — dependencies come up first, go down last.

## Running

```bash
python main.py                       # boot with the demo heartbeat
python -m unittest discover -s tests # run the test suite
```

## Status / next steps

Foundation only, by design. Next modules to port onto it: `face_link`
(ESP32 serial), then `vision`, `voice`, `brain`, and the focus-mode behavior
— each as a `Module` publishing/subscribing on the bus. Targets laptop now,
Jetson Nano later; nothing here is platform-specific.
