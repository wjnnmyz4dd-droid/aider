"""Knowledge & RAG subsystem input/output objects (ADR-020 §2, §3).

Every field on `TradeMemoryRecord` is read directly from an
already-produced `TradeProvenanceRecord` (or its own `scanner_observation`/
`candidate`/`score_result`/`risk_decision`/`compliance_decision`/
`execution_decision`/`position_management_decisions`/`final_outcome`
sub-fields) — never re-derived, never fabricated (`ADR-020` Hard Rule 8).
This module holds no logic; construction happens in `ingestion.py`/
`engine.py`.

No field anywhere in this module is capable of representing a trade
decision, a sizing instruction, or an execution/compliance/risk/scoring
verdict of this package's own making (`ADR-020` Hard Rules 1-2) — every
verdict-shaped field here (`compliance_verdict`, `execution_verdict`,
`risk_tier`) is a plain string mirror of another stage's own already-
produced enum value, read once and never recomputed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Mapping, Optional, Tuple

from ..scanner.models import Direction

SCHEMA_VERSION = 1


class DocumentKind(Enum):
    """The exhaustive set of documentation/report sources this package
    ingests (`ADR-020` §2) — never an arbitrary directory walk."""

    ADR = "ADR"
    TEAM_DOC = "TEAM_DOC"
    INTERFACE_SPEC = "INTERFACE_SPEC"
    IMPLEMENTATION_PLAN = "IMPLEMENTATION_PLAN"
    VALIDATION_MATRIX = "VALIDATION_MATRIX"
    CHANGELOG = "CHANGELOG"
    PLAN_DOC = "PLAN_DOC"
    DEPLOYMENT_GUIDE = "DEPLOYMENT_GUIDE"
    STRATEGY_DOC = "STRATEGY_DOC"
    ANALYTICS_REPORT = "ANALYTICS_REPORT"
    REPLAY_REPORT = "REPLAY_REPORT"
    PAPER_TRADING_REPORT = "PAPER_TRADING_REPORT"
    PRODUCTION_REPORT = "PRODUCTION_REPORT"
    WEEKLY_REPORT = "WEEKLY_REPORT"
    TRADE_JOURNAL = "TRADE_JOURNAL"
    DASHBOARD_REPORT = "DASHBOARD_REPORT"
    HEALTH_REPORT = "HEALTH_REPORT"


class ResearchCategory(Enum):
    """The exhaustive research-suggestion vocabulary (`ADR-020` §1) —
    every suggestion is exported as data; none may be applied
    automatically to any pipeline stage."""

    FILTER = "FILTER"
    CONFLUENCE = "CONFLUENCE"
    PARAMETER = "PARAMETER"
    SESSION = "SESSION"
    RISK = "RISK"
    MARKET_OBSERVATION = "MARKET_OBSERVATION"


@dataclass(frozen=True)
class KnowledgeDocument:
    """One ingested document (`ADR-020` §2). `content_hash` is a SHA-256
    of `content`, used by `ingestion.py` for automatic deduplication —
    re-ingesting an unchanged file is a no-op, never a duplicate entry."""

    schema_version: int
    document_id: str
    kind: DocumentKind
    title: str
    content: str
    source_path: Optional[str]
    content_hash: str
    metadata: Mapping[str, str]
    ingested_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True)
class EmbeddingVector:
    """One document's/trade's embedding (`ADR-020` §6) — `model_name`
    records which `EmbeddingProvider` produced it, so a vector produced
    by one provider is never silently compared against one produced by
    another."""

    document_id: str
    vector: Tuple[float, ...]
    model_name: str
    dimension: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "vector", tuple(self.vector))


@dataclass(frozen=True)
class SearchQuery:
    text: str
    top_k: int = 10
    filters: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "filters", dict(self.filters))


@dataclass(frozen=True)
class SearchResult:
    """One ranked retrieval result (`ADR-020` §3) — `document`/`trade`
    are mutually exclusive; exactly one is populated depending on what
    `document_id` resolved to."""

    document_id: str
    score: float
    rank: int
    document: Optional[KnowledgeDocument] = None
    trade: Optional["TradeMemoryRecord"] = None


@dataclass(frozen=True)
class TradeMemoryRecord:
    """Long-term trade memory (`ADR-020` §2) — every field is read
    directly from an already-produced `TradeProvenanceRecord`, never
    re-derived (`ADR-020` Hard Rule 8). `why_trade_happened`/
    `why_trade_skipped`/`rule_explanations`/`ai_explanation` are built by
    `engine.py`'s deterministic templates over this same record's own
    `reason_codes`/`blocking_rules`/`blocking_reasons`/`decision_reason`
    fields — never a fabricated narrative."""

    schema_version: int
    trace_id: str
    symbol: Optional[str]
    direction: Optional[Direction]
    entry_price: Optional[float]
    exit_price: Optional[float]
    sessions: Tuple[str, ...]
    market_regime: Optional[str]
    strategy_id: Optional[str]
    score_total: Optional[float]
    risk_tier: Optional[str]
    compliance_verdict: Optional[str]
    execution_verdict: Optional[str]
    position_management_actions: Tuple[str, ...]
    realized_pnl: Optional[float]
    mae: Optional[float]
    mfe: Optional[float]
    why_trade_happened: str
    why_trade_skipped: Optional[str]
    rule_explanations: Tuple[str, ...]
    ai_explanation: str
    replay_link: Optional[str]
    collected_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "sessions", tuple(self.sessions))
        object.__setattr__(self, "position_management_actions", tuple(self.position_management_actions))
        object.__setattr__(self, "rule_explanations", tuple(self.rule_explanations))


@dataclass(frozen=True)
class ResearchSuggestion:
    """An exported, inert research idea (`ADR-020` §1, Hard Rule 3) —
    structurally incapable of being applied to a pipeline stage: no
    pipeline-stage package imports this module (enforced by
    `scripts/check_architecture.py`), and nothing on this type is a
    trading instruction."""

    schema_version: int
    category: ResearchCategory
    description: str
    supporting_evidence: Tuple[str, ...]
    generated_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "supporting_evidence", tuple(self.supporting_evidence))


@dataclass(frozen=True)
class KnowledgeDashboardSnapshot:
    """Read-only Knowledge Dashboard snapshot (`ADR-020` Hard Rule 4) —
    additive; `dashboard.models.ViewName` is untouched and this type is
    never consumed by `dashboard/`. Mirrors `paper_trading.
    validation_dashboard.ValidationDashboardSnapshot`'s own precedent."""

    schema_version: int
    generated_at: datetime
    recent_insights: Tuple[str, ...]
    recent_trade_memory: Tuple[TradeMemoryRecord, ...]
    research_queue: Tuple[ResearchSuggestion, ...]
    recent_ai_explanations: Tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "recent_insights", tuple(self.recent_insights))
        object.__setattr__(self, "recent_trade_memory", tuple(self.recent_trade_memory))
        object.__setattr__(self, "research_queue", tuple(self.research_queue))
        object.__setattr__(self, "recent_ai_explanations", tuple(self.recent_ai_explanations))


__all__ = [
    "SCHEMA_VERSION",
    "DocumentKind",
    "ResearchCategory",
    "KnowledgeDocument",
    "EmbeddingVector",
    "SearchQuery",
    "SearchResult",
    "TradeMemoryRecord",
    "ResearchSuggestion",
    "KnowledgeDashboardSnapshot",
]
