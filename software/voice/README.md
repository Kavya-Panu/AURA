# AURA Voice System

AURA's ears: microphone audio in → recognised text on the Event Bus. It
**listens; it never decides.** No intent classification, no LLM, no emotions, no
hardware control — its only output is a `TEXT_RECOGNIZED` event that the Intent
Engine consumes.

**Verified:** 28 voice tests passing (154 across the whole project). The full
pipeline runs here with fake backends; the real `sounddevice` + `faster-whisper`
backends are drop-in on the laptop.

## The one thing to understand: dependency-injected backends

`sounddevice`, `faster-whisper`, and a physical microphone don't exist in every
environment (CI, this sandbox). So the Voice System depends on **interfaces**,
not libraries:

| Interface | Real (laptop) | Fake (tests/dev) |
|---|---|---|
| `MicrophoneBackend` | `SoundDeviceMicrophone` | `FakeMicrophone` (scripted frames) |
| `STTBackend` | `WhisperSTT` (faster-whisper) | `FakeSTT` (scripted transcripts) |
| `WakeWordBackend` | openWakeWord/Porcupine (inject) | `FakeWakeWord` (scripted scores) |
| `VADBackend` | WebRTC VAD (inject) | built-in `EnergyVAD` |

Real libraries are **lazily imported** inside the real backends, so importing
the module never requires them. Pick backends with the factory:

```python
from voice.factory import build_real_voice_system   # laptop
voice = build_real_voice_system(bus)                 # sounddevice + whisper
lifecycle.register(voice)                            # it's a core Module

from voice.factory import build_fake_voice_system    # tests / no hardware
```

## Pipeline

```
mic frames ─► [wake word?] ─► VAD / endpointer ─► noise filter ─► STT ─► bus
   20 ms        gated by         start/stop         high-pass     Whisper   TEXT_
   int16      require_wake      + pre-roll +                      /fake     RECOGNIZED
              (off in cont.     silence-timeout
               modes)           + max-utterance
```

Per-utterance state machine: `IDLE ──wake──► LISTENING ──endpoint──►
RECOGNIZING ──► publish ──► IDLE`.

## Events published (core `RobotEvent`s)

| Event | When | Payload |
|---|---|---|
| `VOICE_STARTED` / `VOICE_STOPPED` | capture thread start/stop | — |
| `WAKE_WORD_DETECTED` | wake phrase fired | — |
| `SPEECH_STARTED` / `SPEECH_FINISHED` | utterance boundaries | — |
| `LANGUAGE_DETECTED` | before text | `language`, `confidence` |
| **`TEXT_RECOGNIZED`** | **the output the Intent Engine consumes** | `text`, `language`, `confidence`, `duration_s` |
| `NO_SPEECH_DETECTED` | endpointed audio transcribed empty | — |
| `MICROPHONE_ERROR` | disconnect / permanent failure | `message` |

It only publishes. The Intent Engine subscribes to `TEXT_RECOGNIZED`; nothing in
this module reaches into another.

## Files

| File | Role |
|---|---|
| `voice_system.py` | The `Module`: capture loop, per-utterance state machine, all bus publishing. |
| `backends.py` | `MicrophoneBackend` + `STTBackend` protocols; real (lazy) + fake implementations. |
| `factory.py` | `build_real_voice_system` / `build_fake_voice_system` (DI root). |
| `wake_word.py` | `WakeWordDetector` (threshold + cooldown) + backend protocol + fake. |
| `vad.py` | `Endpointer` (pre-roll, silence-timeout, max-utterance) + `EnergyVAD` fallback. |
| `speech_recognizer.py` | Utterance PCM → `RecognitionResult` via the STT backend. |
| `microphone_manager.py` | Mic lifecycle + transparent auto-reconnect. |
| `noise_filter.py` | One-pole high-pass pre-filter (swappable). |
| `language_detector.py` | Resolves detected language with a stable fallback. |
| `audio_utils.py` | numpy-free int16 helpers (rms, duration…). |
| `voice_config.py` | All tunables (audio, wake, VAD, STT, noise, mic) as dataclasses. |
| `voice_events.py` | Voice → `RobotEvent` mapping. |
| `voice_exceptions.py` | Voice errors, rooted in `AuraError`. |

## Continuous modes (TRANSLATION / QUIZ)

Per the command spec, these transcribe every utterance without a wake word:

```python
voice.set_require_wake_word(False)   # on MODE_ENTERED for TRANSLATION/QUIZ
voice.set_require_wake_word(True)    # on return to a wake-gated mode
```

A wake-worded command (e.g. "Aura stop") still works while continuous.

## Configuration highlights

`VoiceConfig` → 16 kHz mono int16; wake phrases `aura` / `hey aura` /
`okay aura` at 0.70 threshold with 1.5 s cooldown; VAD 3-frame start, 0.8 s
silence timeout, 15 s max utterance, 300 ms pre-roll; Whisper `base`/`int8`
auto-device; mic auto-reconnect every 3 s (forever by default).

## Laptop setup

```bash
pip install faster-whisper sounddevice numpy
# optional: pip install webrtcvad openwakeword
python -c "from faster_whisper import WhisperModel; WhisperModel('base')"  # cache model
```

## Running the tests

```bash
python -m unittest discover -s voice/tests    # 28 tests, no hardware needed
```

## Honest status

The pipeline logic — wake gating, endpointing, reconnect, language handling,
state machine, and every bus event — is verified with fakes. What is **not**
tested here (no hardware/network in this environment): real `sounddevice`
capture and real `faster-whisper` accuracy/latency. Those live behind the
backend interfaces and are exercised the first time you run
`build_real_voice_system` on the laptop. Expect to tune `VADConfig` (silence
timeout, aggressiveness) and the wake threshold to your room on first run.

## Scope

Audio → text only. Wake-word models, real VAD/STT accuracy tuning, TTS
(AURA's voice output), and turning recognised text into actions all live in
other modules. This one just makes AURA *hear*.
