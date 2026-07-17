# AURA Memory Manager

AURA's long-term memory. It stores, retrieves, updates, deletes, searches,
summarizes and forgets memories, and publishes memory events. It **only manages
memory** — it never generates AI responses, reasons, controls hardware, or
changes emotions/modes. The Brain Manager talks to *this* class; it never touches
a storage backend directly.

**Verified:** 60 tests passing (466 across the whole project), 12× clean
including the background cleanup thread. The whole thing runs here with in-memory
+ SQLite + JSON providers; a vector DB is a drop-in later.

## The design decision: storage behind a provider interface

The Memory Manager depends on the `MemoryProvider` **interface**, never a
concrete store, so the backend is swappable and the Brain is fully insulated
from it:

| Provider | Use | Notes |
|---|---|---|
| `InMemoryProvider` | default, tests | thread-safe dict |
| `JSONProvider` | laptop | single JSON doc, atomic writes, reloads on restart |
| `SQLiteProvider` | scale | one row/memory, indexed type + expiry, `:memory:` or file |
| `VectorProvider` | future | stub for semantic search; raises until a real vector store is injected |

`set_provider()` swaps the backend live and migrates existing records — callers
never notice. Because the Brain only calls the Memory Manager's API, none of this
leaks upward.

## Short-term vs long-term memory

There's one store, and **importance drives lifetime** via the retention policy:

- **Short-term**: `TEMPORARY` memories (current conversation context, recent
  transient facts) get a short TTL (default 30 min) and are auto-expired by the
  background cleanup. A per-total cap also bounds how many temporaries pile up.
- **Long-term**: `CRITICAL` memories (user name, core preferences, goals) never
  auto-expire. `HIGH`/`MEDIUM`/`LOW` sit in between (default ~1 year / ~60 days /
  ~7 days), and low-importance memories have a per-type cap so history doesn't
  grow without bound.

Everything — TTLs and caps — is configurable in `RetentionPolicy`.

## Memory record

Immutable dataclass with `memory_id`, `memory_type`, `content`, `importance`,
`confidence`, `created_at`, `updated_at`, `expires_at`, `tags`, `metadata`.
Updates produce a new record via `evolve()` (identity preserved, `updated_at`
refreshed). `to_dict`/`from_dict` give clean JSON/SQLite serialization.

## Memory types (extensible)

User Profile, Conversation History, Study Session, Focus Session, Quiz Result,
Homework Progress, Translation Preference, Preference, Achievement, Fact, and
Temporary Context. **Adding a type is one line** in the `MemoryType` enum —
nothing else changes (Open/Closed).

## Retention & background cleanup

The `MemoryManager` implements the core `Module` protocol, and on `start()` runs
a daemon `memory-cleanup` thread. Each pass expires past-due memories (emitting
`MEMORY_EXPIRED` per record), enforces the temporary-total and low-per-type caps,
and emits `MEMORY_CLEANUP_COMPLETED`. The loop uses an **injectable clock** and a
wake event, so tests trigger a pass deterministically (`trigger_cleanup()`) with
no fixed sleeps — hence zero flakiness. `run_cleanup()` can also be called
directly, and `forget_unimportant()` deletes low-value memories on demand.

## Search

`SearchQuery` combines keyword (matched against content values + tags + type),
tag, type, importance, and time-range filters; results are scored (keyword/tag
overlap + importance + confidence) and ranked. A `semantic_hook` is accepted for
a **future vector/embedding search** — when set, it re-ranks or boosts candidates
(demonstrated in the tests). Until then, search is deterministic and
dependency-free. Expired memories are never returned.

## Summarization (no reasoning here)

`summarize(memory_type)` reduces a group of memories (e.g. old conversations,
study sessions) to a single summary record and deletes the originals, cutting
storage while keeping the gist. Crucially, the summarizer is an **injected
callable** — the Memory Manager never calls an LLM itself (that would be
reasoning). If no summarizer is injected, it falls back to a trivial non-AI
reducer (counts, time span, merged tags). A real deployment would inject a
callable that asks the Brain Manager to summarize, keeping the reasoning *outside*
this module.

## Events

Publishes `MEMORY_STORED`, `MEMORY_RETRIEVED`, `MEMORY_UPDATED`,
`MEMORY_DELETED`, `MEMORY_SEARCHED`, `MEMORY_SUMMARIZED`, `MEMORY_FORGOTTEN`,
`MEMORY_EXPIRED`, and `MEMORY_CLEANUP_COMPLETED`. (The spec's "MEMORY_FOUND" is
`MEMORY_SEARCHED` here.) It subscribes to nothing and drives no other module —
storage is a service the Brain *calls*, not an actor.

## Thread safety

An `RLock` guards manager-level operations, every provider is independently
thread-safe, and the cleanup runs on its own thread. Verified with 8 threads
storing concurrently and with the provider contract's concurrent-write test.

## Usage

```python
from memory import MemoryManager, MemoryConfig, MemoryType, Importance, SearchQuery
from memory.memory_provider import SQLiteProvider

mem = MemoryManager(bus, MemoryConfig(), provider=SQLiteProvider("aura.db"))
lifecycle.register(mem)                       # core Module; starts cleanup thread

mem.store(MemoryType.USER_PROFILE, {"name": "Sky", "subject": "physics"},
          importance=Importance.CRITICAL, tags=("profile",))
mem.store(MemoryType.TEMPORARY_CONTEXT, {"note": "asked about resistors"},
          importance=Importance.TEMPORARY)    # auto-expires

hits = mem.search(SearchQuery(text="physics"))
mem.summarize(MemoryType.CONVERSATION)        # inject a summarizer for real use
```

The Brain Manager would hold a reference to `mem` and call `store`/`search`/
`retrieve` — never a provider.

## Files

| File | Role |
|---|---|
| `memory_manager.py` | Coordinator + core Module: CRUD, retention, cleanup thread, summarize/forget, events. |
| `memory_provider.py` | `MemoryProvider` interface; In-Memory / JSON / SQLite / Vector(stub). |
| `memory_record.py` | `MemoryType`, `Importance`, immutable `MemoryRecord`. |
| `memory_search.py` | Keyword/tag/type/time/importance search + scoring + semantic hook. |
| `memory_config.py` | Retention policy, cleanup cadence, search + summarization config. |
| `memory_events.py` | Event mapping. |
| `memory_exceptions.py` | Error types. |

## Adding a new memory type

Add a member to `MemoryType`. Retention, search, storage, and events all work
with it immediately — no other change.

## Future semantic memory / vector database

`VectorProvider` already satisfies the storage interface (raising until wired),
and `MemorySearch` already accepts a `semantic_hook`. To enable semantic recall:
implement a vector-backed `MemoryProvider` (embed on `put`, ANN on a new query
path) and pass an embedding-based `semantic_hook` to `MemorySearch`. Nothing in
the manager or the Brain changes — they target the same interfaces.

## Honest status

All logic — CRUD, importance-driven expiry, retention caps, background cleanup,
summarization with an injected reducer, keyword/tag/type/time/importance search,
provider swap-and-migrate, events, and concurrency — is verified across the
in-memory, JSON, and SQLite providers and is stable (12× clean). **Not** exercised
here: a real vector database (the `VectorProvider` is an honest stub) and a real
LLM summarizer (injected, by design). Those slot in behind the existing
interfaces without touching this module.

---

# Memory System Completion — Summary, Retention & Context

Three focused services complete the memory system. Each has a single
responsibility and a hard boundary: **summary** returns records without storing,
**retention** returns decisions without deleting, **context** holds runtime state
without persisting. None modifies any existing module.

**Verified:** 33 new tests (93 memory total, 499 project-wide), 12× clean.

## `memory_summary.py` — MemorySummary

Summarizes a group of `MemoryRecord`s into one concise summary record, reducing
storage while preserving important facts. It summarizes long conversations,
completed study/focus sessions, and quiz history, and can compress many
low-importance memories into one.

Hard boundaries (by design): it **never** calls an LLM, stores, deletes, or
touches a provider. It receives records and returns a `SummaryOutcome`
(`summary` record + `source_ids`), leaving the decision to replace originals to
the `MemoryManager`.

The reduction is delegated to a `SummaryStrategy` (dependency injection). The
default `HeuristicSummary` is deterministic and non-AI (counts, time span, merged
tags, importance profile, a size-capped digest). **An LLM summarizer plugs in
later without changing the interface**: wrap a callable — e.g. one that routes to
the Brain Manager — in `CallableSummaryStrategy` and inject it. The reasoning
lives entirely inside that callable; `MemorySummary` stays reasoning-free.

```python
from memory.memory_summary import MemorySummary, CallableSummaryStrategy

summary = MemorySummary()                              # heuristic default
outcome = summary.summarize_conversation(old_turns, force=True)
manager_replaces = outcome.source_ids                  # manager deletes these

# later: swap in an LLM-backed strategy, same interface
summary.set_strategy(CallableSummaryStrategy(my_brain_summarizer, "llm"))
```

## `memory_retention.py` — MemoryRetention

Decides what to **KEEP / ARCHIVE / SUMMARIZE / REMOVE** for each memory, based on
importance, age, usage and confidence. It **only decides** — it never deletes or
archives — returning a `RetentionReport` of `RetentionDecision`s the
`MemoryManager` can execute.

Default policy (all configurable via `RetentionPolicy` + the additive
`DecisionPolicy`):

| Importance | Decision |
|---|---|
| CRITICAL | KEEP (never delete) |
| HIGH | KEEP indefinitely |
| MEDIUM | SUMMARIZE after a configurable period |
| LOW | ARCHIVE after a period, then REMOVE when very old / low-confidence |
| TEMPORARY | REMOVE once past its TTL / `expires_at` |

Extra rules: an explicit `expires_at` always wins (even a HIGH memory past it is
REMOVEd), and a frequently-used memory (a metadata `use_count`) is sticky and
kept past its age threshold.

```python
from memory.memory_retention import MemoryRetention, RetentionAction

retention = MemoryRetention()
report = retention.evaluate(manager.all_live())
manager_removes    = report.to_remove       # ids
manager_summarizes = report.to_summarize
manager_archives   = report.to_archive
```

## `memory_context.py` — MemoryContext

AURA's current **working memory** — runtime state only, **never persisted**. It
tracks the current conversation/session id, the current provider name, recently
retrieved/stored memory ids (bounded deques), an in-RAM **LRU cache** of records
with hit/miss statistics, and the timestamps of the last cleanup/summary passes.
It imports no provider and performs no file/DB I/O; `reset()` drops in-RAM state
for a new user session. Thread-safe; `snapshot()` returns an immutable view.

```python
from memory.memory_context import MemoryContext

ctx = MemoryContext(cache_capacity=128)
ctx.set_conversation("conv-42"); ctx.set_provider("sqlite")
hit = ctx.cache_get(mem_id)                 # None on miss -> manager hits provider
ctx.record_stored(record); ctx.mark_cleanup()
stats = ctx.cache_stats()                   # hits/misses/size, .hit_rate
```

## How they compose (in the MemoryManager)

These are building blocks the `MemoryManager` orchestrates; they never call back
into it, so there are no cycles:

```
MemoryRetention.evaluate(records)  ─► actions ─► MemoryManager executes
                                                  (delete / archive / trigger summary)
MemoryManager gathers a group ─► MemorySummary.summarize(...) ─► summary record
                                                  ─► MemoryManager stores it + deletes sources
Every op ─► MemoryContext.record_* / cache / mark_* (working-memory state, no persistence)
```

## Honest status (completion)

Summarization (heuristic + pluggable strategy), retention decisions across all
five importance levels plus expiry/usage/confidence rules, and the runtime
context (LRU cache, stats, session tracking, snapshot) are all verified and
stable (12× clean). No existing file was modified. **Not** exercised here: a real
LLM summary strategy (injected by design) — it slots into
`CallableSummaryStrategy` without any interface change.
