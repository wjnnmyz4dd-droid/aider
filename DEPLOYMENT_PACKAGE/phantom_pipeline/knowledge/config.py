"""Versioned configuration for the Knowledge & RAG subsystem (`ADR-020`).

Every tunable here is an implementation default naming *how* this
package's own read-only retrieval/indexing behaves, never new
architecture (`CLAUDE.md` §7, §3) — the same discipline every prior
stage's `config.py` already establishes.
"""

from __future__ import annotations

from dataclasses import dataclass

KNOWLEDGE_VERSION = "1.0.0-phase1"


@dataclass(frozen=True)
class KnowledgeConfig:
    embedding_dimension: int = 256
    default_top_k: int = 10
    deduplicate_documents: bool = True
    recent_insights_limit: int = 10
    recent_trade_memory_limit: int = 20
    recent_ai_explanations_limit: int = 10


DEFAULT_CONFIG = KnowledgeConfig()

__all__ = ["KNOWLEDGE_VERSION", "KnowledgeConfig", "DEFAULT_CONFIG"]
