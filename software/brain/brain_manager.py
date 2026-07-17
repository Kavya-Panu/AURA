"""
brain/brain_manager.py
======================
The Brain Manager - AURA's intelligence layer. It selects a provider, manages
conversation history, builds prompts per mode, generates responses, and handles
translation and knowledge tasks, with timeout, retry, provider fallback and
caching. It implements the core Module protocol so the LifecycleManager owns it.

It GENERATES TEXT ONLY. It never controls hardware, changes emotions or modes,
speaks, or does speech recognition. It integrates by:
  * subscribing to QUESTION_RECEIVED (from the Intent layer) and answering with
    ANSWER_READY, and
  * publishing BRAIN_REQUESTED/STARTED/COMPLETED/FAILED, TRANSLATION_STARTED/
    COMPLETED, and PROVIDER_CHANGED.
It modifies no existing module.

Thread-safety: requests are independent and may run concurrently; shared state
(context, cache, provider selection) is lock-guarded. Cancellation and timeouts
are supported via a per-request future run on a thread pool.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FTimeout
from typing import Callable

from core.event_bus import Event, EventBus
from core.logger import get_logger

from . import brain_events as ev
from .brain_config import BrainConfig, TaskKind
from .brain_context import BrainContext
from .brain_exceptions import (
    BrainCancelled, BrainError, BrainTimeout, NoProviderAvailable,
    ProviderError, ProviderUnavailable,
)
from .brain_result import BrainResult
from .conversation_manager import ConversationManager
from .knowledge_service import KnowledgeRequest, KnowledgeService
from .prompt_manager import PromptManager
from .provider_registry import GenerationRequest, ProviderRegistry
from .provider_selector import ProviderSelector
from .translation_service import TranslationRequest, TranslationService

log = get_logger("brain.manager")


class BrainManager:
    """Coordinates providers, conversation, prompts, translation and knowledge."""

    name = "brain"

    def __init__(self, event_bus: EventBus, config: BrainConfig | None = None,
                 registry: ProviderRegistry | None = None,
                 prompt_manager: PromptManager | None = None,
                 conversation_manager: ConversationManager | None = None,
                 max_workers: int = 4,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._bus = event_bus
        self._cfg = config or BrainConfig.default()
        self._registry = registry or ProviderRegistry()
        self._selector = ProviderSelector(self._registry, self._cfg.selection)
        self._prompts = prompt_manager or PromptManager()
        self._conversations = conversation_manager or ConversationManager(
            self._cfg.max_history_turns)
        self._knowledge = KnowledgeService()
        self._translation = TranslationService(self._run_generation)
        self._ctx = BrainContext()
        self._clock = clock

        self._lock = threading.RLock()
        self._cache: "OrderedDict[str, BrainResult]" = OrderedDict()
        self._executor: ThreadPoolExecutor | None = None
        self._max_workers = max_workers
        self._offline = False
        self._sub_id: int | None = None
        self._announced_provider: str | None = None   # last PROVIDER_CHANGED value

    # =====================================================================
    #  Module protocol
    # =====================================================================
    def initialize(self) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=self._max_workers, thread_name_prefix="brain")
        available = self._registry.available()
        if available:
            self._ctx.set_provider(available[0])
        log.info("brain initialised (%d providers, %d available)",
                 len(self._registry.names()), len(available))

    def start(self) -> None:
        if self._sub_id is None:
            self._sub_id = self._bus.subscribe(
                ev.QUESTION_RECEIVED, self._on_question, priority=50)
        log.info("brain started")

    def stop(self) -> None:
        if self._sub_id is not None:
            self._bus.unsubscribe(self._sub_id)
            self._sub_id = None
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None
        log.info("brain stopped")

    def health_check(self) -> bool:
        return self._executor is not None and len(self._registry.available()) > 0

    # =====================================================================
    #  Provider registration passthrough (no manager edits to add providers)
    # =====================================================================
    def register_provider(self, provider) -> None:
        self._registry.register(provider)
        if self._ctx.current_provider is None:
            self._ctx.set_provider(provider.name)

    @property
    def context(self) -> BrainContext:
        return self._ctx

    @property
    def providers(self) -> tuple[str, ...]:
        return self._registry.names()

    def set_offline(self, offline: bool) -> None:
        with self._lock:
            self._offline = offline

    # =====================================================================
    #  Public API
    # =====================================================================
    def ask(self, question: str, *, mode: str | None = None,
            session_id: str = ConversationManager.DEFAULT_SESSION,
            task: TaskKind | None = None,
            timeout_s: float | None = None) -> BrainResult:
        """Answer a question, using conversation history + the mode's prompt."""
        conversation = self._conversations.get(session_id)
        conversation.set_mode(mode)
        conversation.add_user(question)

        system_prompt = self._prompts.get_prompt(mode)
        resolved_task = task or self._infer_task(question, mode)
        gen = GenerationRequest(
            system_prompt=system_prompt,
            messages=tuple(conversation.messages()),
            temperature=self._cfg.default_temperature,
            max_tokens=1024,
            metadata={"mode": mode, "session": session_id})

        result = self._run_generation(gen, resolved_task, timeout_s=timeout_s)
        if result.success:
            conversation.add_assistant(result.response)
        return result

    def teach(self, req: KnowledgeRequest, *, mode: str | None = "TEACHER",
              session_id: str = ConversationManager.DEFAULT_SESSION,
              timeout_s: float | None = None) -> BrainResult:
        """Knowledge/teaching request: classify, shape the prompt, generate."""
        task = self._knowledge.classify(req)
        base = self._prompts.get_prompt(mode)
        system_prompt = self._knowledge.augment_prompt(base, req)
        conversation = self._conversations.get(session_id)
        conversation.add_user(req.question)
        gen = GenerationRequest(
            system_prompt=system_prompt,
            messages=tuple(conversation.messages()),
            temperature=self._cfg.default_temperature, max_tokens=1024,
            metadata={"subject": req.subject, "style": req.style})
        result = self._run_generation(gen, task, timeout_s=timeout_s)
        if result.success:
            conversation.add_assistant(result.response)
        return result

    def translate(self, text: str, target_lang: str, *,
                  source_lang: str = "auto",
                  timeout_s: float | None = None) -> BrainResult:
        """One-shot translation. Returns translated text in `.translation`."""
        self._bus.emit(ev.TRANSLATION_STARTED,
                       {"target_lang": target_lang, "source_lang": source_lang},
                       source=self.name)
        result = self._translation.translate(
            TranslationRequest(text, source_lang, target_lang))
        self._bus.emit(ev.TRANSLATION_COMPLETED,
                       {"success": result.success, "provider": result.provider},
                       source=self.name)
        return result

    # =====================================================================
    #  Core generation with timeout / retry / fallback / cache
    # =====================================================================
    def _run_generation(self, gen: GenerationRequest, task: TaskKind,
                        *, timeout_s: float | None = None) -> BrainResult:
        self._ctx.record_request()
        self._bus.emit(ev.BRAIN_REQUESTED, {"task": task.value}, source=self.name)

        cache_key = self._cache_key(gen, task)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return _with_meta(cached, cache_hit=True)

        try:
            chain = self._selector.candidate_chain(task, offline=self._offline)
        except NoProviderAvailable as exc:
            return self._fail(str(exc), task)

        timeout = timeout_s or self._cfg.request_timeout_s
        self._bus.emit(ev.BRAIN_STARTED,
                       {"task": task.value, "chain": chain}, source=self.name)

        last_error = "no provider attempted"
        for name in chain:
            provider = self._registry.get(name)
            if provider is None:
                continue
            result = self._try_provider(provider, gen, timeout)
            if result is not None and result.success:
                self._announce_provider(name)
                self._cache_put(cache_key, result)
                self._bus.emit(ev.BRAIN_COMPLETED,
                               {"provider": name, "task": task.value,
                                "tokens": result.tokens.total}, source=self.name)
                return _with_meta(result, task=task.value,
                                  fallbacks=chain[:chain.index(name)])
            last_error = result.error if result else f"{name} timed out"
            log.warning("provider '%s' failed: %s; falling back", name, last_error)

        return self._fail(last_error, task)

    def _try_provider(self, provider, gen: GenerationRequest,
                      timeout: float) -> BrainResult | None:
        """Run one provider with retries + timeout. Returns a BrainResult
        (success or failure) or None if it should be skipped."""
        cfg = self._provider_cfg(provider.name)
        retries = cfg.max_retries if cfg else 1
        t0 = self._clock()
        for attempt in range(retries + 1):
            try:
                result = self._call_with_timeout(provider, gen, timeout)
                elapsed = self._clock() - t0
                return BrainResult(
                    response=result.response, provider=result.provider,
                    confidence=result.confidence, processing_time=elapsed,
                    tokens=result.tokens, reasoning_summary=result.reasoning_summary,
                    success=True, metadata=result.metadata)
            except BrainTimeout as exc:
                return BrainResult.failure(str(exc), provider.name)
            except (ProviderUnavailable,) as exc:
                return BrainResult.failure(str(exc), provider.name)
            except ProviderError as exc:
                if attempt >= retries:
                    return BrainResult.failure(str(exc), provider.name)
                time.sleep(min(0.05 * (attempt + 1), 0.2))   # small backoff
        return None

    def _call_with_timeout(self, provider, gen: GenerationRequest,
                           timeout: float) -> BrainResult:
        """Run provider.generate on the pool and enforce a timeout."""
        if self._executor is None:
            # Not started via lifecycle; run inline (still honours provider errors).
            return provider.generate(gen)
        future: Future = self._executor.submit(provider.generate, gen)
        try:
            return future.result(timeout=timeout)
        except FTimeout as exc:
            future.cancel()
            raise BrainTimeout(
                f"provider '{provider.name}' exceeded {timeout}s") from exc

    # =====================================================================
    #  Bus integration: answer QUESTION_RECEIVED with ANSWER_READY
    # =====================================================================
    def _on_question(self, event: Event) -> None:
        question = event.data.get("text") or event.data.get("question", "")
        mode = event.data.get("mode")
        session = event.data.get("session", ConversationManager.DEFAULT_SESSION)
        if not question:
            return
        result = self.ask(question, mode=mode, session_id=session)
        self._bus.emit(ev.ANSWER_READY,
                       {"text": result.response, "provider": result.provider,
                        "success": result.success,
                        "confidence": round(result.confidence, 3)},
                       source=self.name)

    # =====================================================================
    #  Helpers
    # =====================================================================
    def _infer_task(self, question: str, mode: str | None) -> TaskKind:
        m = (mode or "").upper()
        if m == "TRANSLATION":
            return TaskKind.TRANSLATION
        if m in ("TEACHER", "HOMEWORK", "QUIZ"):
            return TaskKind.TEACHING
        if len(question.split()) > 40:
            return TaskKind.COMPLEX_REASONING
        return TaskKind.SIMPLE_QA

    def _provider_cfg(self, name: str):
        for p in self._cfg.providers:
            if p.name == name:
                return p
        return None

    def _announce_provider(self, name: str) -> None:
        self._ctx.set_provider(name)
        if self._announced_provider != name:
            self._announced_provider = name
            self._bus.emit(ev.PROVIDER_CHANGED, {"provider": name},
                           source=self.name)

    def _fail(self, error: str, task: TaskKind) -> BrainResult:
        self._ctx.record_failure(error)
        self._bus.emit(ev.BRAIN_FAILED, {"error": error, "task": task.value},
                       source=self.name)
        return BrainResult.failure(error)

    # ---- cache (LRU) ----
    def _cache_key(self, gen: GenerationRequest, task: TaskKind) -> str:
        last = gen.messages[-1]["content"] if gen.messages else ""
        return f"{task.value}|{gen.system_prompt[:40]}|{last}"

    def _cache_get(self, key: str) -> BrainResult | None:
        if not self._cfg.enable_cache:
            return None
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        return None

    def _cache_put(self, key: str, result: BrainResult) -> None:
        if not self._cfg.enable_cache:
            return
        with self._lock:
            self._cache[key] = result
            self._cache.move_to_end(key)
            while len(self._cache) > self._cfg.cache_size:
                self._cache.popitem(last=False)


def _with_meta(result: BrainResult, **meta) -> BrainResult:
    return BrainResult(
        response=result.response, provider=result.provider,
        confidence=result.confidence, processing_time=result.processing_time,
        tokens=result.tokens, reasoning_summary=result.reasoning_summary,
        translation=result.translation, success=result.success,
        error=result.error, metadata={**result.metadata, **meta})
