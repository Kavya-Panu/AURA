"""
brain/brain_config.py
=====================
Configuration for the Brain Manager. Pure data (dataclasses); no behaviour and
no magic numbers elsewhere. Every provider, selection rule, timeout and retry is
configurable here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TaskKind(Enum):
    """The kind of work a request represents - drives provider selection."""
    SIMPLE_QA = "simple_qa"          # short factual question -> local model
    COMPLEX_REASONING = "complex"    # multi-step reasoning -> strong cloud model
    TRANSLATION = "translation"      # translate -> local model
    TEACHING = "teaching"            # explanations / step-by-step
    SUMMARY = "summary"
    GENERAL = "general"


@dataclass
class ProviderConfig:
    """Settings for one provider instance."""
    name: str
    model: str = ""
    priority: int = 100              # lower = preferred among candidates
    timeout_s: float = 30.0
    max_retries: int = 2
    is_local: bool = False           # local models work offline
    enabled: bool = True
    temperature: float = 0.7
    max_tokens: int = 1024


@dataclass
class SelectionRules:
    """Maps a TaskKind to an ordered list of preferred provider names. The first
    available one wins; remaining names are the fallback chain."""
    by_task: dict[str, list[str]] = field(default_factory=dict)
    default_chain: list[str] = field(default_factory=list)
    prefer_local_when_offline: bool = True

    def chain_for(self, task: TaskKind) -> list[str]:
        return self.by_task.get(task.value, []) or self.default_chain


@dataclass
class BrainConfig:
    """Top-level Brain configuration."""
    providers: list[ProviderConfig] = field(default_factory=list)
    selection: SelectionRules = field(default_factory=SelectionRules)
    max_history_turns: int = 12          # conversation context length
    request_timeout_s: float = 30.0
    enable_cache: bool = True
    cache_size: int = 256
    default_temperature: float = 0.7

    @staticmethod
    def default() -> "BrainConfig":
        """A sensible default wiring for the five named providers + fallback."""
        providers = [
            ProviderConfig("ollama", "qwen2.5:7b", priority=10, is_local=True),
            ProviderConfig("qwen", "qwen-max", priority=40),
            ProviderConfig("deepseek", "deepseek-chat", priority=50),
            ProviderConfig("openai", "gpt-4o", priority=60),
            ProviderConfig("claude", "claude-sonnet-4", priority=30),
        ]
        rules = SelectionRules(
            by_task={
                TaskKind.SIMPLE_QA.value: ["ollama", "qwen", "openai"],
                TaskKind.TRANSLATION.value: ["ollama", "qwen"],
                TaskKind.COMPLEX_REASONING.value: ["claude", "openai", "deepseek"],
                TaskKind.TEACHING.value: ["claude", "openai", "ollama"],
                TaskKind.SUMMARY.value: ["ollama", "qwen", "openai"],
            },
            default_chain=["ollama", "claude", "openai"],
        )
        return BrainConfig(providers=providers, selection=rules)
