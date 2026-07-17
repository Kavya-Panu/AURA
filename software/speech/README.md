# AURA Speech Manager

AURA's expression layer — the piece that turns the Brain's answers into
**expressive, spoken output** and drives the physical face while speaking. It
chooses a voice profile and a face emotion, holds a stable expression, animates
the mouth, synthesizes speech through a pluggable TTS engine, and plays it — all
on a background worker so the robot never blocks. It **only expresses**: it never
generates answers, calls an LLM, does speech recognition, changes modes, or makes
decisions.

**Verified:** 63 tests passing (406 across the whole project), 12× clean despite
heavy threading. The full pipeline runs here with fake TTS + a fake audio sink;
real engines are drop-in on the laptop.

## The design decision: engines and audio behind interfaces

Real TTS (pyttsx3, Edge, Piper) and audio playback aren't available in every
environment. So — like every other AURA layer — the Speech Manager depends on
**interfaces**, not libraries:

| Interface | Real | Fake (tests/dev) |
|---|---|---|
| `TTSEngine` | `Pyttsx3Engine`, `EdgeTTSEngine`, `PiperEngine` (lazy import) | `FakeTTS` (synthetic audio + duration estimate) |
| `AudioSink` | `RealAudioSink` (simpleaudio, lazy) | `FakeAudioSink` (time-scaled, honours stop flag) |

Every real engine lazily imports its library, so importing the Speech Manager
never pulls in a TTS package, and a missing engine reports `is_available() ==
False` and the manager falls through to the next one.

## The pipeline (per utterance, on the speak-worker thread)

```
 text ─► EmotionMapper ─► (emotion token, voice profile)
      ─► ExpressionManager.set_expression ─► EMOTION_CHANGED (face token)
      ─► TimingController.thinking_pause
      ─► TTSManager.synthesize ─► audio clip + duration
      ─► MouthAnimator.start (visemes) ═╗ run together
      ─► AudioPlayer.play ══════════════╝
      ─► SPEECH_FINISHED
```

The mouth animation and audio playback run together for the utterance's
duration; the expression is set once and **held** (no per-word switching).

## Voice & emotion mapping

`EmotionMapper` turns *what was said* into *how AURA looks and sounds*: a base
style per mode (Teacher → calm/neutral, Quiz → excited, Translation →
listening/translator) plus content cues (greeting → HAPPY, congratulations →
CELEBRATE 🤩, apology → SAD, "stay focused / put your phone away" → WORRIED,
"hmm, let me think" → THINKING). Translation deliberately stays neutral to avoid
distracting expression churn. Emotion tokens match the core `Emotion` enum
values — i.e. the **exact ESP32 serial tokens** — and are sent via the same
`EMOTION_CHANGED` event the Behavior layer uses, so a FaceLink renders them with
no special casing.

`VoiceProfileRegistry` holds named profiles (friendly, teacher, translator,
assistant, calm, excited) with speed/pitch/volume/pause, and supports custom
voices at runtime.

## Speech queue: priority, interruption, cancellation

`SpeechQueue` is a thread-safe priority queue. Normal speech is FIFO; a
high-priority item (lower number) jumps ahead; `interrupt=True` stops the current
utterance immediately; `cancel_all()` clears everything and emits
`SPEECH_CANCELLED`. This is what lets a focus-mode phone warning cut in over
chatter.

## Mouth animation

`MouthAnimator` maps text to a viseme sequence (CLOSED / SMALL / MEDIUM / WIDE —
vowels open wider) and emits mouth-shape commands to the Face Engine on its own
thread for the utterance's duration, always ending closed. It's rhythm, not
perfect lip-sync — cheap and good enough for a desk companion.

## Events

Publishes `SPEECH_STARTED`, `SPEECH_FINISHED`, `SPEECH_CANCELLED`, `TTS_STARTED`,
`TTS_FINISHED`, `VOICE_CHANGED`, `EXPRESSION_CHANGED`,
`MOUTH_ANIMATION_STARTED/STOPPED`, and sends face emotions via `EMOTION_CHANGED`.
It **subscribes to `ANSWER_READY`** (from the Brain) and speaks the answer — so a
recognised, intent-classified, brain-answered question is spoken and shown on the
face with no glue code.

## Threading

A single `speech-worker` thread consumes the queue, so synthesis, playback,
expression and mouth animation are serialized per-utterance and thread-safe.
Concurrent `say()` calls from any thread are safe (verified with 6 threads).

## Files

| File | Role |
|---|---|
| `speech_manager.py` | Coordinator + core Module: worker, pipeline, queue, bus integration. |
| `tts_manager.py` | `TTSEngine` interface; Fake + pyttsx3/Edge/Piper (lazy); engine selection. |
| `audio_player.py` | `AudioSink` interface; Fake + real playback; interruption + volume. |
| `emotion_mapper.py` | Text/mode → face emotion token + voice profile. |
| `voice_profiles.py` | Named voice profiles (+ custom). |
| `mouth_animation.py` | Viseme sequence → mouth-shape events. |
| `expression_manager.py` | Holds one stable expression; sends face commands. |
| `timing_controller.py` | Thinking pause, sentence gaps, sentence splitting. |
| `speech_queue.py` | Thread-safe priority queue with interrupt/cancel. |
| `speech_config.py` / `speech_context.py` / `speech_events.py` / `speech_result.py` / `speech_exceptions.py` | Config, live state, event mapping, result, errors. |

## Usage

```python
from speech import SpeechManager, SpeechConfig
from speech.tts_manager import TTSManager, Pyttsx3Engine, EdgeTTSEngine
from speech.audio_player import AudioPlayer, RealAudioSink

tts = TTSManager([EdgeTTSEngine(), Pyttsx3Engine()])   # Edge preferred, pyttsx3 fallback
speech = SpeechManager(bus, SpeechConfig(), tts, AudioPlayer(RealAudioSink()))
lifecycle.register(speech)                              # core Module

speech.say("Hello!", mode="NORMAL")                    # explicit
# ...or it speaks Brain answers automatically via ANSWER_READY
speech.say("Put your phone away.", mode="FOCUS", priority=0, interrupt=True)  # cut in
```

## Laptop setup

```bash
pip install pyttsx3 simpleaudio        # offline baseline
pip install edge-tts                   # better online voices
# piper: install piper-tts + a voice model, pass model_path to PiperEngine
```

## Honest status

The whole pipeline — emotion/profile mapping, expression holding, mouth-viseme
animation, timing, priority queue, interruption, cancellation, TTS-engine
selection and fallback, the `ANSWER_READY → speech` flow, and concurrency — is
verified with the fake TTS + fake audio sink and is stable (12× clean). **Not**
tested here (no audio hardware/TTS libs): real pyttsx3/Edge/Piper synthesis and
real playback. Those run the first time you inject a real engine + sink on the
laptop, where you'll pick voices and tune speaking rate. The mouth shapes are
sent as face commands; the ESP32 Face Engine renders them — that half is wired by
FaceLink (the serial bridge), which consumes the `EMOTION_CHANGED` events this
layer already emits.
