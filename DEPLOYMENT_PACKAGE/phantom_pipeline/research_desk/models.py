"""Phantom AI Research Desk input/output objects (`ADR-021` §3).

Every type here is a plain, immutable record — no logic lives in this
file, matching every other package's own `models.py` convention.
`ResearchSuggestion`/`KnowledgeDashboardSnapshot` are imported from
`phantom_pipeline.knowledge` and reused verbatim (`ADR-021` Hard Rule 3)
— this module never redefines them.

`DebateThesis` is structurally incapable of representing a trading
signal (`ADR-021` Hard Rule 6): no field anywhere on it or its nested
`ThesisCase` is named `direction`/`lot_size`/`entry_price`/`stop_loss`/
`take_profit`, and no pipeline-stage package may import this module
(enforced by `scripts/check_architecture.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Mapping, Optional, Tuple

from ..knowledge import KnowledgeDashboardSnapshot, ResearchSuggestion

SCHEMA_VERSION = 1


class DebateStance(Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


@dataclass(frozen=True)
class ThesisCase:
    stance: DebateStance
    summary: str
    supporting_evidence: Tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "supporting_evidence", tuple(self.supporting_evidence))


@dataclass(frozen=True)
class DebateThesis:
    """Research only — never a trading signal (`ADR-021` Hard Rule 6)."""

    schema_version: int
    report_id: str
    symbol: str
    generated_at: datetime
    bullish_case: ThesisCase
    bearish_case: ThesisCase
    neutral_case: ThesisCase
    confidence_score: float
    final_summary: str


@dataclass(frozen=True)
class MarketStructureFinding:
    symbol: str
    structure_summary: str
    volatility_summary: str
    liquidity_summary: str
    active_sessions: Tuple[str, ...]
    regime: Optional[str]

    # ADR-022 Amendment 1 §A1.2 item 5 — additive, defaulted so every
    # pre-existing construction of this type is unaffected. Plain quoted
    # text built from an already-produced `StatisticalRiskAssessment`;
    # never a new statistical value computed here.
    statistical_risk_summary: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "active_sessions", tuple(self.active_sessions))


@dataclass(frozen=True)
class MarketResearchReport:
    schema_version: int
    report_id: str
    period_kind: str  # "DAILY" | "WEEKLY"
    window_start: datetime
    window_end: datetime
    generated_at: datetime
    findings: Tuple[MarketStructureFinding, ...]
    macro_news_summary: str
    economic_calendar_summary: str
    active_blackout_currencies: Tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "findings", tuple(self.findings))
        object.__setattr__(self, "active_blackout_currencies", tuple(self.active_blackout_currencies))


@dataclass(frozen=True)
class TradeThesis:
    """Extends `knowledge.TradeMemoryRecord`'s own why-happened/why-
    skipped narrative with institutional framing (`ADR-021` §3, item 3)
    — every field is read from the same already-produced
    `TradeProvenanceRecord` this trade's `TradeMemoryRecord` was built
    from, never a second, independent derivation."""

    schema_version: int
    trace_id: str
    why_setup_existed: str
    why_it_qualified: str
    why_it_failed_or_succeeded: str
    institutional_context: str
    expected_continuation: str
    risk_factors: Tuple[str, ...]
    lessons_learned: Tuple[str, ...]
    generated_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "risk_factors", tuple(self.risk_factors))
        object.__setattr__(self, "lessons_learned", tuple(self.lessons_learned))


@dataclass(frozen=True)
class JournalEntry:
    """Read-only after creation (`ADR-021` Hard Rule 7) — frozen, and
    `trade_journal.py` defines no update method anywhere for this type."""

    schema_version: int
    trace_id: str
    entry_reason: str
    risk_reason: str
    compliance_decision: str
    execution_quality: str
    exit_reason: Optional[str]
    profit_or_loss: Optional[float]
    lessons_learned: Tuple[str, ...]
    suggested_improvements: Tuple[str, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "lessons_learned", tuple(self.lessons_learned))
        object.__setattr__(self, "suggested_improvements", tuple(self.suggested_improvements))


@dataclass(frozen=True)
class RuleCombinationFinding:
    rule_codes: Tuple[str, ...]
    occurrence_count: int
    average_pnl: Optional[float]
    classification: str  # "STRONGEST" | "WEAKEST"

    def __post_init__(self) -> None:
        object.__setattr__(self, "rule_codes", tuple(self.rule_codes))


@dataclass(frozen=True)
class ParameterSensitivityResult:
    """`available=False` always, for now (`ADR-021` §6, Hard Rule 5) —
    no backtest/parameter-sweep module exists anywhere in
    `phantom_pipeline` today; this is a real, flagged gap, never a
    fabricated result."""

    parameter_name: str
    available: bool
    detail: str


@dataclass(frozen=True)
class RecurringMistake:
    description: str
    occurrence_count: int
    example_trace_ids: Tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "example_trace_ids", tuple(self.example_trace_ids))


@dataclass(frozen=True)
class InstitutionalReviewReport:
    schema_version: int
    report_id: str
    period_kind: str
    window_start: datetime
    window_end: datetime
    generated_at: datetime
    executive_summary: str
    performance_review: str
    risk_review: str
    compliance_review: str
    execution_review: str
    market_review: str
    best_pair: Optional[str]
    worst_pair: Optional[str]
    best_session: Optional[str]
    worst_session: Optional[str]
    best_regime: Optional[str]
    worst_regime: Optional[str]
    recurring_mistakes: Tuple[RecurringMistake, ...]
    improvement_opportunities: Tuple[str, ...]
    research_recommendations: Tuple[ResearchSuggestion, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "recurring_mistakes", tuple(self.recurring_mistakes))
        object.__setattr__(self, "improvement_opportunities", tuple(self.improvement_opportunities))
        object.__setattr__(self, "research_recommendations", tuple(self.research_recommendations))


@dataclass(frozen=True)
class ComparisonReport:
    report_id: str
    generated_at: datetime
    period_a_label: str
    period_b_label: str
    metric_deltas: Mapping[str, float]
    narrative: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "metric_deltas", dict(self.metric_deltas))


@dataclass(frozen=True)
class ResearchDeskDashboardSnapshot:
    """Wraps `knowledge.KnowledgeDashboardSnapshot` verbatim (`ADR-021`
    Hard Rule 3) — never a re-implementation of it. `dashboard/`
    (`ADR-012`) is untouched (Hard Rule 4)."""

    schema_version: int
    generated_at: datetime
    knowledge_snapshot: KnowledgeDashboardSnapshot
    research_summaries: Tuple[str, ...]
    learning_trends: Tuple[str, ...]
    strategy_evolution: Tuple[str, ...]
    optimization_history: Tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "research_summaries", tuple(self.research_summaries))
        object.__setattr__(self, "learning_trends", tuple(self.learning_trends))
        object.__setattr__(self, "strategy_evolution", tuple(self.strategy_evolution))
        object.__setattr__(self, "optimization_history", tuple(self.optimization_history))


__all__ = [
    "SCHEMA_VERSION",
    "DebateStance",
    "ThesisCase",
    "DebateThesis",
    "MarketStructureFinding",
    "MarketResearchReport",
    "TradeThesis",
    "JournalEntry",
    "RuleCombinationFinding",
    "ParameterSensitivityResult",
    "RecurringMistake",
    "InstitutionalReviewReport",
    "ComparisonReport",
    "ResearchDeskDashboardSnapshot",
]
