"""
brain/provider_registry.py
==========================
The provider abstraction. The Brain depends on the AIProvider INTERFACE, never
on a concrete provider, so no single vendor is load-bearing.

Providers:
    * MockProvider   - deterministic, offline; for tests and offline fallback.
    * OpenAIProvider / ClaudeProvider / QwenProvider / DeepSeekProvider /
      OllamaProvider - real; each lazily imports its SDK and is driven through
      an injected `client` callable so the Brain never imports vendor SDKs at
      module load. Adding a provider = implement AIProvider + register it.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable

from core.logger import get_logger

from .brain_config import ProviderConfig
from .brain_exceptions import ProviderError, ProviderUnavailable
from .brain_result import BrainResult, TokenUsage

log = get_logger("brain.provider")


@dataclass(frozen=True)
class GenerationRequest:
    """One generation request handed to a provider."""
    system_prompt: str
    messages: tuple[dict[str, str], ...]     # [{"role","content"}, ...]
    temperature: float = 0.7
    max_tokens: int = 1024
    metadata: dict | None = None


@runtime_checkable
class AIProvider(Protocol):
    """Common interface every provider implements."""
    name: str
    def is_available(self) -> bool: ...
    def generate(self, request: GenerationRequest) -> BrainResult: ...


class MockProvider:
    """Deterministic offline provider. Echoes a shaped response so selection,
    fallback, conversation and translation logic can all be tested without a
    network or API key. Can be told to fail or be unavailable for tests."""

    def __init__(self, name: str = "mock", *, available: bool = True,
                 fail: bool = False, is_local: bool = False,
                 responder: Callable[[GenerationRequest], str] | None = None) -> None:
        self.name = name
        self._available = available
        self._fail = fail
        self.is_local = is_local
        self._responder = responder
        self.calls = 0

    def set_available(self, available: bool) -> None:
        self._available = available

    def set_fail(self, fail: bool) -> None:
        self._fail = fail

    def is_available(self) -> bool:
        return self._available

    def generate(self, request: GenerationRequest) -> BrainResult:
        self.calls += 1
        if not self._available:
            raise ProviderUnavailable(f"provider '{self.name}' unavailable")
        if self._fail:
            raise ProviderError(f"provider '{self.name}' failed")
        last = request.messages[-1]["content"] if request.messages else ""
        if self._responder is not None:
            text = self._responder(request)
        else:
            text = f"[{self.name}] {last}"
        return BrainResult(
            response=text, provider=self.name, confidence=0.9,
            tokens=TokenUsage(prompt_tokens=len(last.split()),
                              completion_tokens=len(text.split())),
            reasoning_summary="", success=True)


class _LazyClientProvider:
    """Base for real providers. The vendor call is an injected `client`
    callable: (GenerationRequest) -> (text, prompt_tokens, completion_tokens).
    This keeps SDK imports lazy and makes real providers unit-testable by
    injecting a stand-in client. Subclasses set `name` and a default client
    factory that lazily imports the SDK."""

    def __init__(self, cfg: ProviderConfig,
                 client: Callable[[GenerationRequest], tuple[str, int, int]] | None = None
                 ) -> None:
        self.name = cfg.name
        self._cfg = cfg
        self._client = client

    def is_available(self) -> bool:
        if not self._cfg.enabled:
            return False
        if self._client is not None:
            return True
        try:
            self._client = self._build_client()
            return True
        except Exception as exc:                        # noqa: BLE001
            log.debug("provider %s unavailable: %s", self.name, exc)
            return False

    def _build_client(self) -> Callable[[GenerationRequest], tuple[str, int, int]]:
        raise ProviderUnavailable(f"no client for '{self.name}'")

    def generate(self, request: GenerationRequest) -> BrainResult:
        if self._client is None and not self.is_available():
            raise ProviderUnavailable(f"provider '{self.name}' unavailable")
        try:
            text, ptok, ctok = self._client(request)
        except Exception as exc:                        # noqa: BLE001
            raise ProviderError(f"{self.name} generation failed: {exc}") from exc
        return BrainResult(
            response=text, provider=self.name, confidence=0.85,
            tokens=TokenUsage(ptok, ctok), success=True)


class OpenAIProvider(_LazyClientProvider):
    def _build_client(self):
        from openai import OpenAI                        # import now -> unavailable if missing
        def client(req: GenerationRequest):
            oai = OpenAI()
            msgs = [{"role": "system", "content": req.system_prompt},
                    *req.messages]
            resp = oai.chat.completions.create(
                model=self._cfg.model, messages=msgs,
                temperature=req.temperature, max_tokens=req.max_tokens)
            text = resp.choices[0].message.content or ""
            u = resp.usage
            return text, getattr(u, "prompt_tokens", 0), getattr(u, "completion_tokens", 0)
        return client


class ClaudeProvider(_LazyClientProvider):
    def _build_client(self):
        import anthropic                                 # import now -> unavailable if missing
        def client(req: GenerationRequest):
            cl = anthropic.Anthropic()
            resp = cl.messages.create(
                model=self._cfg.model, system=req.system_prompt,
                messages=list(req.messages), temperature=req.temperature,
                max_tokens=req.max_tokens)
            text = "".join(b.text for b in resp.content if b.type == "text")
            u = resp.usage
            return text, getattr(u, "input_tokens", 0), getattr(u, "output_tokens", 0)
        return client


class QwenProvider(_LazyClientProvider):
    def _build_client(self):
        from openai import OpenAI                        # Qwen: OpenAI-compatible API
        def client(req: GenerationRequest):
            oai = OpenAI(base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
            msgs = [{"role": "system", "content": req.system_prompt}, *req.messages]
            resp = oai.chat.completions.create(
                model=self._cfg.model, messages=msgs,
                temperature=req.temperature, max_tokens=req.max_tokens)
            text = resp.choices[0].message.content or ""
            u = resp.usage
            return text, getattr(u, "prompt_tokens", 0), getattr(u, "completion_tokens", 0)
        return client


class DeepSeekProvider(_LazyClientProvider):
    def _build_client(self):
        from openai import OpenAI                        # DeepSeek: OpenAI-compatible API
        def client(req: GenerationRequest):
            oai = OpenAI(base_url="https://api.deepseek.com")
            msgs = [{"role": "system", "content": req.system_prompt}, *req.messages]
            resp = oai.chat.completions.create(
                model=self._cfg.model, messages=msgs,
                temperature=req.temperature, max_tokens=req.max_tokens)
            text = resp.choices[0].message.content or ""
            u = resp.usage
            return text, getattr(u, "prompt_tokens", 0), getattr(u, "completion_tokens", 0)
        return client


class OllamaProvider(_LazyClientProvider):
    def _build_client(self):
        import ollama                                    # import now -> unavailable if missing
        def client(req: GenerationRequest):
            msgs = [{"role": "system", "content": req.system_prompt}, *req.messages]
            resp = ollama.chat(model=self._cfg.model, messages=msgs,
                               options={"temperature": req.temperature})
            text = resp["message"]["content"]
            return text, resp.get("prompt_eval_count", 0), resp.get("eval_count", 0)
        return client


class ProviderRegistry:
    """Thread-safe registry of providers keyed by name."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._providers: dict[str, AIProvider] = {}

    def register(self, provider: AIProvider) -> None:
        if not isinstance(provider, AIProvider):
            raise ProviderError(
                f"object '{type(provider).__name__}' is not an AIProvider")
        with self._lock:
            self._providers[provider.name] = provider
        log.info("registered provider '%s'", provider.name)

    def unregister(self, name: str) -> bool:
        with self._lock:
            return self._providers.pop(name, None) is not None

    def get(self, name: str) -> AIProvider | None:
        with self._lock:
            return self._providers.get(name)

    def names(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._providers)

    def available(self) -> tuple[str, ...]:
        with self._lock:
            provs = list(self._providers.values())
        return tuple(p.name for p in provs if _safe_available(p))


def _safe_available(p: AIProvider) -> bool:
    try:
        return p.is_available()
    except Exception:                                   # noqa: BLE001
        return False
