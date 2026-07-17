# AURA — AI Companion Study Robot

AURA is a desk companion robot that helps a student focus, learn, and stay
company. It can see the person in front of it, hear and understand them, reason
with a large language model, remember what matters, speak with an expressive
voice, and show emotion on an animated face — all driven by a modular Python
"brain" on a laptop that talks to an ESP32-based physical robot over serial.

This repository is the complete software stack: **twelve cooperating layers, 235
Python files, ~21,800 lines, and 595 passing unit tests.** Every layer runs on a
plain laptop with **no hardware attached**, because every external dependency
(camera, microphone, LLM APIs, TTS engines, audio output, and the serial link
itself) sits behind an interface with a mock implementation.

---

## What AURA does

A single spoken question flows through the whole system:

```
you speak ─► Voice (wake word + STT) ─► Intent (what you meant)
          ─► Brain (LLM answer / translation)  ◄──► Memory (recall + store)
          ─► Speech (voice + emotion + mouth) ─► Hardware (HAL) ─► ESP32 face
Vision watches throughout (face, gaze, phone, gestures, fatigue) and feeds the bus.
```

Everything is wired together by a central **Event Bus** — modules never call each
other directly. They publish and subscribe to events, which keeps the whole
system decoupled, testable, and easy to extend.

---

## Architecture at a glance

Three physical tiers:

1. **ESP32 Face Engine** (C++/PlatformIO) — renders animated eyes, mouth, and 17
   emotions on an ILI9341 display, and parses emotion/mouth tokens from serial.
2. **Laptop "brain"** (this repo, Python) — all perception, reasoning, memory,
   and expression logic.
3. **Physical hardware** — display, neck servo, LEDs, propeller, battery,
   camera, microphone — reached only through the Hardware Abstraction Layer.

Cross-cutting design rules that hold across every layer:

- **Event Bus only.** Modules communicate through the core `EventBus`; they never
  import one another or mutate each other's state.
- **Dependency injection at every boundary.** Cameras, models, LLM providers, TTS
  engines, audio sinks, storage backends, and the serial transport are all
  injected behind `Protocol` interfaces, each with a real (lazy-import) backend
  and a fake/mock backend. That's why the full robot runs offline on a laptop.
- **Lifecycle-managed modules.** Each manager implements a `Module` protocol
  (`initialize/start/stop/health_check`) owned by the `LifecycleManager`.
- **Additive core.** Shared enums (events, emotions) are only ever *appended* to
  in `core/constants.py`; no existing module is modified when a new layer lands.
- **Open/Closed extensibility.** New detectors, providers, memory types, devices,
  and drivers are added by registration, without editing the managers that use
  them.

---

## The twelve layers

| Layer | Package | Responsibility | Tests |
|---|---|---|---:|
| Core Framework | `core/` | Event bus, state machine, lifecycle, config, logging, constants | 28 |
| Behavior Manager | `behavior/` | Priority-based behavior arbitration; requests emotions | 16 |
| Mode Manager | `mode/` | 12 operating modes (Focus, Teacher, Quiz, Translation, …) | 27 |
| Intent Engine | `intent/` | Deterministic NLU — 86 intents, sub-50 ms | 55 |
| Voice System | `voice/` | Mic → VAD → wake word → speech-to-text | 28 |
| Vision System | `vision/` | Camera → detectors → interaction (face, gaze, phone, gestures, fatigue) + pipeline | 138 |
| Brain Manager | `brain/` | Multi-provider LLM answers, translation, conversation, teaching | 51 |
| Speech Manager | `speech/` | TTS + voice profiles + face emotion + mouth animation | 63 |
| Memory Manager | `memory/` | Store / search / summarize / forget; retention + working memory | 93 |
| Hardware (HAL) | `hardware/` | The single hardware boundary + drivers (face, servo, LED, propeller, battery) | 96 |
| ESP32 Face Engine | `../companion_face/` | On-device animated face (C++/PlatformIO) | — |
| Command Spec | `../AURA_COMMAND_SPEC.md` | The end-to-end serial/command reference | — |

**Total: 595 passing tests.**

### Core Framework (`core/`)
The foundation every other layer builds on: a thread-safe `EventBus`
(`emit`/`subscribe`/`subscribe_all`), a state machine, a `LifecycleManager` that
owns all modules, structured logging, config, timers, and the shared
`RobotEvent` / `Emotion` enums. The `Emotion` values *are* the ESP32 serial
tokens (17 emotions incl. `THINK`, `LISTEN`, `CELEBRATE`, `WORRIED`).

### Behavior, Mode & Intent
**Behavior** arbitrates competing behaviors by priority (preempt / queue / resume)
and requests emotions via `EMOTION_CHANGED`. **Mode** manages 12 operating modes
with NORMAL as the hub. **Intent** is a deterministic NLU engine (no LLM) mapping
utterances to 86 intents in under 50 ms and emitting `QUESTION_RECEIVED`.

### Voice System (`voice/`)
Microphone → voice-activity detection → wake-word → Whisper STT, all behind
`Mic`/`STT` protocols with fake backends. Publishes `TEXT_RECOGNIZED`,
`WAKE_WORD_DETECTED`, and related events.

### Vision System (`vision/`)
The largest layer, built in stages: a camera layer (thread-safe frame buffer with
drop-oldest), independent detectors (face, face-tracking, person, phone-with-
duration), interaction detectors (gestures, smile, eye-contact, head-pose,
fatigue), a runtime-configurable `VisionPipeline`, and a `PerformanceMonitor`.
Every model (MediaPipe / YOLO) is injected; the whole thing runs with fakes. It
only *observes* and publishes events — it never controls behavior.

### Brain Manager (`brain/`)
AURA's intelligence. Five LLM providers (OpenAI, Claude, Qwen, DeepSeek, Ollama)
behind one `AIProvider` interface, plus a deterministic `MockProvider`.
Configurable provider selection (local for simple/offline, cloud for reasoning),
conversation history, per-mode prompts, translation, and knowledge/teaching —
with timeout, retry, provider fallback, and caching. Subscribes to
`QUESTION_RECEIVED`, answers with `ANSWER_READY`. It generates text only.

### Speech Manager (`speech/`)
Turns Brain answers into expressive, spoken output: chooses a voice profile and
face emotion, holds a stable expression, animates the mouth (visemes), synthesizes
via a pluggable TTS engine (pyttsx3 / Edge / Piper + fake), and plays audio on a
background worker. Subscribes to `ANSWER_READY`; drives the face via
`EMOTION_CHANGED`.

### Memory Manager (`memory/`)
Long-term memory behind a storage-provider interface (in-memory / JSON / SQLite,
with a vector-DB stub for future semantic search). Stores 11 memory types, searches
by keyword/tag/type/time/importance, summarizes old memories (via an injected
summarizer — never an LLM call inside memory), and forgets by a configurable
retention policy with background cleanup. Includes a retention decision service
and a runtime working-memory context.

### Hardware Abstraction Layer (`hardware/`)
The **only** module allowed to touch physical hardware. Stage 1 owns the ESP32
serial link (auto-detect, priority queue, reader/writer threads, auto-reconnect,
heartbeat) and a device registry; it forwards `EMOTION_CHANGED` to the physical
face. Stage 2 adds concrete drivers (face, servo, LED, propeller, battery) and a
command router — all routing *through* the HardwareManager, never the port
directly (a test enforces that no other module imports `serial`).

---

## Running it

Everything runs offline with mock backends — no hardware, no API keys, no network.

```bash
# from the AURA/ directory
python -m unittest discover -s tests            # core
python -m unittest discover -s vision/tests     # any layer
# ...or the whole suite:
for d in tests behavior/tests mode/tests intent/tests voice/tests \
         vision/tests brain/tests speech/tests memory/tests hardware/tests; do
  python -m unittest discover -s "$d"
done
```

### Going live on a laptop + robot

Each layer swaps its mock for a real backend by injection — no code changes
elsewhere:

```bash
pip install openai anthropic ollama     # LLM providers you want (Brain)
pip install openai-whisper sounddevice  # real STT + mic (Voice)
pip install mediapipe ultralytics opencv-python  # real detectors (Vision)
pip install pyttsx3 edge-tts simpleaudio         # real TTS + audio (Speech)
pip install pyserial                    # real ESP32 link (Hardware)
```

Then construct each manager with its real backend (e.g.
`HardwareManager(bus, cfg, PySerialTransport())`, `BrainManager` with real
providers registered) and register them all with the `LifecycleManager`.

---

## Design principles (why it's built this way)

- **Testability first.** Every hardware/model/network dependency is injected, so
  595 tests run in seconds with no external anything. Threaded code is tested with
  `wait_until` polling and injectable clocks, not fixed sleeps — so the suite is
  flake-free (each threaded suite verified 10–15× consecutively).
- **Separation of concerns.** Vision only observes. Brain only generates text.
  Speech only expresses. Memory only remembers. Hardware is the only thing that
  touches a port. No layer reaches across these lines.
- **The Event Bus is the spine.** A recognized → intent-classified → brain-
  answered → spoken → physically-expressed interaction happens with zero direct
  calls between those layers.
- **Honest status.** Logic verified with fakes is proven; real hardware/model
  paths are exercised only when you inject real backends on the laptop. Each
  package README says exactly what is and isn't verified.

---

## Repository layout

```
AURA/
├── core/          # event bus, state machine, lifecycle, constants
├── behavior/      # priority behavior arbitration
├── mode/          # 12 operating modes
├── intent/        # deterministic NLU (86 intents)
├── voice/         # mic -> VAD -> wake word -> STT
├── vision/        # camera -> detectors -> interaction + pipeline
├── brain/         # multi-provider LLM, translation, teaching
├── speech/        # TTS + emotion + mouth animation
├── memory/        # store/search/summarize/forget + retention + context
├── hardware/      # HAL: serial link + drivers (the only hardware boundary)
└── <package>/tests/   # comprehensive unit tests per layer

companion_face/    # ESP32 face engine (C++/PlatformIO)
AURA_COMMAND_SPEC.md   # end-to-end command/serial reference
```

Each package has its own README with architecture details, usage, and an honest
verified-vs-untested status section.

---

## Status & what's next

The software stack is complete end-to-end: AURA can perceive, understand, reason,
remember, speak, and physically express — every decision reaching the ESP32 face
over serial. All 595 tests pass and the suite is flake-free.

Natural next steps:
- **Focus Manager** — the signature feature: a focus timer with phone-warning
  escalation (using the vision `PHONE_DETECTED` / `PHONE_DURATION_UPDATED`
  events), driving the face and LEDs through the HAL and logging session stats to
  Memory. It ties vision, hardware, and memory together.
- **ESP32 firmware handlers** for the new `SERVO:` / `LED:` / `PROP:` tokens (the
  emotion and `MOUTH:` tokens already match the Face Engine).
- **Real-backend bring-up** on the laptop + robot, one layer at a time.

---

*AURA is an MSc dissertation project — a full-stack AI companion robot spanning
embedded firmware, computer vision, speech, LLM reasoning, memory, and hardware
control, built as twelve decoupled, individually-tested layers.*
