"""
brain/provider_selector.py
==========================
Chooses which provider handles a request, based on configurable rules and live
availability. Simple questions/translation -> local model; complex reasoning ->
strong cloud model; offline -> local fallback. Returns an ordered candidate
chain so the Brain can fall back on failure.
"""
from __future__ import annotations

from core.logger import get_logger

from .brain_config import SelectionRules, TaskKind
from .brain_exceptions import NoProviderAvailable
from .provider_registry import ProviderRegistry

log = get_logger("brain.selector")


class ProviderSelector:
    """Turns (task, availability) into an ordered provider chain."""

    def __init__(self, registry: ProviderRegistry, rules: SelectionRules) -> None:
        self._registry = registry
        self._rules = rules

    def candidate_chain(self, task: TaskKind, *, offline: bool = False) -> list[str]:
        """Ordered list of provider names to try for this task. Filters to
        available providers; if offline, prefers local providers first."""
        preferred = self._rules.chain_for(task)
        available = set(self._registry.available())

        chain = [name for name in preferred if name in available]
        # Append any other available providers not already listed (last-resort).
        for name in self._registry.available():
            if name not in chain:
                chain.append(name)

        if offline and self._rules.prefer_local_when_offline:
            chain.sort(key=lambda n: 0 if self._is_local(n) else 1)

        if not chain:
            raise NoProviderAvailable(
                f"no available provider for task '{task.value}'")
        return chain

    def select(self, task: TaskKind, *, offline: bool = False) -> str:
        """The single best provider for a task (head of the chain)."""
        return self.candidate_chain(task, offline=offline)[0]

    def _is_local(self, name: str) -> bool:
        provider = self._registry.get(name)
        return bool(getattr(provider, "is_local", False))
