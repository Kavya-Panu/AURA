"""
memory/memory_config.py
=======================
Configuration for the Memory Manager. Pure data (dataclasses); no behaviour and
no magic numbers elsewhere. Retention policy, cleanup cadence, and search limits
are all configurable here.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RetentionPolicy:
    """How long memories of each importance level live (seconds). 0 = forever.

    Retention is enforced by the background cleanup task; Critical memories are
    never expired automatically.
    """
    critical_ttl_s: float = 0.0            # never auto-expire
    high_ttl_s: float = 60 * 60 * 24 * 365 # ~1 year
    medium_ttl_s: float = 60 * 60 * 24 * 60  # ~60 days
    low_ttl_s: float = 60 * 60 * 24 * 7    # ~7 days
    temporary_ttl_s: float = 60 * 30       # 30 minutes

    # Cap on how many low-importance memories to keep per type (0 = unlimited).
    max_low_per_type: int = 500
    max_temporary_total: int = 200


@dataclass
class CleanupConfig:
    """Background cleanup behaviour."""
    enabled: bool = True
    interval_s: float = 60.0               # how often the cleanup task runs
    batch_limit: int = 500                 # max deletions per cleanup pass


@dataclass
class SearchConfig:
    """Search defaults."""
    default_limit: int = 20
    max_limit: int = 200
    min_score: float = 0.0                 # drop results below this score


@dataclass
class SummarizationConfig:
    """When/how old memories get summarized (the summarizer itself is injected;
    the Memory Manager NEVER calls an LLM directly)."""
    enabled: bool = True
    summarize_after_s: float = 60 * 60 * 24 * 30   # summarize convo older than ~30d
    min_records_to_summarize: int = 20


@dataclass
class MemoryConfig:
    """Top-level Memory configuration."""
    retention: RetentionPolicy = field(default_factory=RetentionPolicy)
    cleanup: CleanupConfig = field(default_factory=CleanupConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    summarization: SummarizationConfig = field(default_factory=SummarizationConfig)
