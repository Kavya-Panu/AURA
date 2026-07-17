# AURA Brain Manager

AURA's intelligence layer. It selects an AI provider, manages conversation
history, builds per-mode prompts, and handles translation and knowledge tasks —
with timeout, retry, provider fallback and caching. It **generates text only**:
it never controls hardware, changes emotions or modes, speaks, or does speech
recognition.

**Verified:** 51 tests passing (343 across the whole project), 10× clean. The
full thing runs here with a deterministic Mock provider; real providers are
drop-in on the laptop.

## The design decision: no provider is load-bearing

Every provider (OpenAI, Claude, Qwen, DeepSeek, Ollama) implements one
`AIProvider` interface, and the Brain depends only on that interface. Each real
provider **lazily imports its SDK** inside an injected `client`, so importing the
Brain never pulls in any vendor SDK, and a provider whose SDK/key is absent
simply reports `is_available() == False` instead of crashing. A `MockProvider`
gives deterministic offline responses for tests and as an offline fallback.

```python
from brain import BrainManager, BrainConfig, MockProvider
from brain.provider_registry import OllamaProvider, ClaudeProvider

brain = BrainManager(bus, BrainConfig.default())
brain.register_provider(OllamaProvider(cfg))     # local
brain.register_provider(ClaudeProvider(cfg))     # cloud
lifecycle.register(brain)                         # it's a core Module
result = brain.ask("What is Ohm's law?", mode="TEACHER")
```

Adding a provider = implement `AIProvider` (or subclass `_LazyClientProvider`)
and `register_provider(...)`. The manager is never edited.

## Provider selection (configurable)

`ProviderSelector` turns `(TaskKind, availability)` into an ordered candidate
chain from `SelectionRules`:

| Task | Default preference |
|---|---|
| Simple QA | local (Ollama) → cloud |
| Translation | local (Ollama) → Qwen |
| Complex reasoning | Claude → OpenAI → DeepSeek |
| Teaching | Claude → OpenAI → local |

Unavailable providers are filtered out; when `offline`, local providers float to
the front. The head of the chain is tried first; the rest are the **fallback
chain**. All rules live in `BrainConfig` — no hard-coded routing.

## Conversation management

`ConversationManager` holds independent sessions, each a bounded
`ConversationContext` (rolling history capped at `max_history_turns`, plus topic,
mode, and recent questions). History is fed to the provider as messages, so the
model has context. Sessions are isolated and thread-safe.

## Prompt management (external & configurable)

`PromptManager` maps each mode to a system prompt (`system_prompts.py`), with
distinct prompts for Assistant, Teacher, Homework, Quiz, Translation,
Presentation, and Focus. Prompts are data, overridable at construction, and new
modes can be added at runtime with `set_prompt(...)` — no code changes.

## Translation & knowledge

`TranslationService` supports one-shot, bidirectional and continuous translation
(automatic language detection is a stubbed future hook) and returns **translated
text only** in `BrainResult.translation` — speech is handled elsewhere.
`KnowledgeService` classifies questions (electronics, programming, math, study,
summaries, worked examples, step-by-step teaching) into a `TaskKind` and augments
the prompt with subject/style hints, so teaching requests route to
reasoning-capable providers.

## Reliability: timeout, retry, fallback, cache

Each generation runs on a thread pool with a per-request **timeout**; on
provider failure it **retries** (per-provider `max_retries` with small backoff)
then **falls back** to the next provider in the chain. Identical requests are
served from an **LRU cache**. All of this is transparent to the caller, which
just gets a `BrainResult`.

## Events

Publishes `BRAIN_REQUESTED`, `BRAIN_STARTED`, `BRAIN_COMPLETED`, `BRAIN_FAILED`,
`TRANSLATION_STARTED`, `TRANSLATION_COMPLETED`, and `PROVIDER_CHANGED`. It also
**subscribes to `QUESTION_RECEIVED`** (from the Intent layer) and answers with
**`ANSWER_READY`** — so a spoken, recognised, intent-classified question flows
into an answer with no glue code.

## Thread safety

Requests are independent and may run concurrently (verified with 20 simultaneous
asks across sessions). Shared state — conversation store, cache, provider
selection, context — is lock-guarded. Streaming responses are a future extension
of the same provider interface.

## BrainResult

`response`, `provider`, `confidence`, `processing_time`, `tokens`
(prompt/completion/total), `reasoning_summary` (a brief rationale — never full
chain-of-thought), `translation`, `success`/`error`, and `metadata` (task,
cache-hit, fallbacks tried).

## Files

| File | Role |
|---|---|
| `brain_manager.py` | Coordinator + core Module: selection, fallback, retry, timeout, cache, bus integration. |
| `provider_registry.py` | `AIProvider` interface; Mock + 5 real providers (lazy SDK); registry. |
| `provider_selector.py` | Task + availability → ordered candidate chain. |
| `conversation_manager.py` / `conversation_context.py` | Sessions + bounded rolling history. |
| `prompt_manager.py` / `system_prompts.py` | Per-mode external prompts. |
| `translation_service.py` | One-shot/bidirectional/continuous translation. |
| `knowledge_service.py` | Task classification + prompt shaping for teaching. |
| `brain_config.py` | Providers, selection rules, timeouts, retries, cache — all configurable. |
| `brain_result.py` / `brain_context.py` / `brain_events.py` / `brain_exceptions.py` | Result, live state, event mapping, errors. |

## Adding a new provider

1. Subclass `_LazyClientProvider`, implement `_build_client()` (import the SDK
   there so `is_available()` is truthful), returning a
   `(request) -> (text, prompt_tokens, completion_tokens)` callable.
2. Add a `ProviderConfig` and put its name in the relevant `SelectionRules`.
3. `brain.register_provider(MyProvider(cfg))`. Done.

## Future RAG support

The provider interface takes a `GenerationRequest` (system prompt + messages),
so retrieval-augmented generation slots in cleanly: a future `RetrievalService`
would fetch context and prepend it to the system prompt or messages before
`_run_generation`, with no change to providers or the selector. Streaming is a
natural extension of `AIProvider.generate` (add a `generate_stream`).

## Running the tests

```bash
python -m unittest discover -s brain/tests    # 51 tests, no network/keys needed
```

## Honest status

Provider selection, fallback, retry, timeout, caching, conversation history,
prompt selection, translation routing, knowledge classification, the
`QUESTION_RECEIVED → ANSWER_READY` flow, and concurrency are all verified with
the Mock provider and are stable (10× clean). **Not** tested here (no network/
keys): real OpenAI/Claude/Qwen/DeepSeek/Ollama responses. Those run the first
time you register a real provider on the laptop — the SDK imports are lazy and
availability is probed, so a missing SDK degrades gracefully to the next
provider in the chain.
