# AURA Intent Engine

Converts natural language into structured **intents**. It is a deterministic NLP
preprocessing layer — **not** an LLM, not a chatbot. It only *understands*; it
never controls hardware, changes emotions, calls the LLM, speaks, or moves the
robot. Its single output is an `IntentResult`.

**Verified:** 55 intent tests passing (126 across the whole project);
**0.17 ms/utterance** average — ~290× inside the 50 ms budget. Every intent
name, parameter, mode rule and clarification follows `AURA_COMMAND_SPEC.md`.

## What it does

```
"Aura help me focus for two hours"
        │
        ▼
IntentResult(
    intent = START_FOCUS,
    confidence = 1.0,
    parameters = {"duration_minutes": 120},
    missing_parameters = [],
    clarification_needed = False,
    response_hint = "entering focus mode",
    raw_text = "Aura help me focus for two hours",
)
```

## Data flow

```
text ─► IntentParser ─► normalise + strip wake word + extract parameters
                           │
                           ▼
        ┌────────── generic mode-verb resolver ("Aura stop" → mode) ─────────┐
        │  no                                                          yes ──►│ result
        ▼                                                                     │
   continuous-mode free speech? (TRANSLATION→TRANSLATE_UTTERANCE, QUIZ→ANSWER)│
        │ no                                                                  │
        ▼                                                                     │
   IntentMatcher.score(all definitions, params, mode)                        │
        │                                                                     │
        ▼                                                                     │
   confidence band ─► EXECUTE / EXECUTE_LOG / CLARIFY / UNKNOWN               │
        │                                                                     │
        ▼                                                                     │
   validate params ─► inherit context ─► clarify missing ─► IntentResult ◄────┘
```

Everything is dictionaries + regex + arithmetic — no ML, no network — so it is
fully deterministic and sub-millisecond.

## Architecture (files)

| File | Responsibility |
|---|---|
| `intent_engine.py` | Facade: `process(text, mode, context, session)` → `IntentResult`. Orchestrates the pipeline. |
| `intent_parser.py` | text → `ParsedUtterance` (normalise, wake-word, tokens, params). |
| `natural_language.py` | Normalisation: lowercase, apostrophes, word-numbers, wake-word stripping. |
| `parameter_extractor.py` | Deterministic slot extraction (durations, languages, subjects, times, reminders, expressions…). |
| `intent_registry.py` | `IntentDefinition` for every spec intent (phrases, keywords, params, mode rules). |
| `intent_matcher.py` | Scores utterances against the registry; mode-aware shaping. |
| `synonym_dictionary.py` | Synonym groups (`token_class`), languages, subjects, difficulty, fillers. |
| `confidence.py` | The four bands: >0.90 execute · 0.70–0.90 execute+log · 0.40–0.70 clarify · <0.40 unknown. |
| `clarification.py` | Per-missing-parameter and low-confidence questions. |
| `validator.py` | Parameter validation/repair (duration clamps, language/difficulty canonicalisation…). |
| `fallback.py` | The `UNKNOWN` result (confused + reprompt). |
| `intent_context.py` | Conversation history + session state; subject inheritance. |
| `intent_result.py` | The `IntentResult` dataclass (the only output). |
| `intent_types.py` | The `Intent` enum (frozen names from the spec). |
| `intent_exceptions.py` | Engine exceptions (rooted in `AuraError`). |
| `utils.py` | Small pure helpers. |

## API

```python
from intent import IntentEngine, IntentContext, Intent

engine = IntentEngine()
ctx = IntentContext()

result = engine.process(
    text="Aura translate English to Japanese",
    current_mode="NORMAL",            # str or a ModeType enum
    conversation_context=ctx,          # optional; enables inheritance/history
    session_state={"user": "sky"},     # optional
)
# result.intent == Intent.START_TRANSLATION
# result.parameters == {"source_language": "English", "target_language": "Japanese", ...}
```

`process()` **never raises** on user speech — bad input becomes `Intent.UNKNOWN`.

### Integrating with the existing architecture (no modifications needed)

The engine produces data; it does not act. A thin adapter (outside this module)
turns an `IntentResult` into the events the Behavior/Mode managers already
consume:

```python
res = engine.process(text, current_mode=mode_manager.current_mode.name)
if res.clarification_needed:
    bus.emit(RobotEvent.SPEECH_STARTED, {"text": res.clarification_question}, source="intent")
else:
    if (defn := registry.get(res.intent)) and defn.target_mode:
        bus.emit(RobotEvent.MODE_REQUESTED,
                 {"mode": defn.target_mode, "params": res.parameters}, source="intent")
    # else: emit a behavior request keyed by res.intent
```

The Behavior Manager and Mode Manager are untouched — they receive the same
`MODE_REQUESTED` / behavior events they already handle.

## Mode & context awareness

- **"Aura stop" never guesses.** It resolves by current mode: FOCUS→`STOP_FOCUS`,
  TRANSLATION→`STOP_TRANSLATION`, QUIZ→`END_QUIZ`, TEACHER→`STOP_TEACHING`,
  HOMEWORK→`STOP_HOMEWORK`, PRESENTATION→`STOP_PRESENTATION`; bare stop in
  NORMAL→`CANCEL`. Same for pause/resume/next/repeat.
- **Continuous modes.** In TRANSLATION/QUIZ, speech without a wake word is
  treated as content (`TRANSLATE_UTTERANCE` / `QUIZ_ANSWER`), while a wake-worded
  command (e.g. "Aura stop") still interrupts.
- **Subject inheritance.** "Teach me physics" … later "quiz me" → quiz inherits
  `subject=physics` from conversation history.

## Confidence bands (per spec)

| Confidence | Action |
|---|---|
| > 0.90 | Execute immediately. |
| 0.70 – 0.90 | Execute and log the confidence. |
| 0.40 – 0.70 | Ask a clarification question (never act). |
| < 0.40 | `UNKNOWN` → confused + reprompt. |

## Extending

**Add an intent** — one enum value + one registry entry:
```python
# intent_types.py
NEW_THING = "NEW_THING"
# intent_registry.py (inside build_default_registry)
r.register(IntentDefinition(
    Intent.NEW_THING,
    phrases=("do the new thing", "new thing please"),
    keywords=_kw("thing"),
    param_names=("topic",),
    modes=_m("NORMAL"),          # optional
    target_mode=None,            # optional
))
```
No matcher/engine edits — the matcher discovers it.

**Add synonyms** — extend a group in `synonym_dictionary._GROUPS`; both patterns
and utterances route through `token_class`, so the new word matches everywhere.

**Add a parameter** — add an extractor in `parameter_extractor.py`, list it in
the relevant `IntentDefinition.param_names`, and add a rule in `validator.py`.
Optionally add a clarification question in `clarification.py`.

**Add a validation rule** — extend `validator._validate_one`.

## Running

```bash
python -m unittest discover -s intent/tests     # 55 tests
```

## Scope

Understanding only. It does not call the LLM, speak, render the face, move
servos, or change modes/emotions — it hands a structured `IntentResult` to the
layers that do.
