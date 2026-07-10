"""Data models for the Strategy Engine (Phase 2C).

Every type here describes a strategy's self-declared shape or a scored
evaluation of it. Nothing here is a trade decision: there is no
`BUY`/`SELL` enum, no position size, no order, anywhere in this module,
by design (see `docs/adr/ADR-026-strategy-engine.md` Hard Rule 1).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple

from phantom.evidence_engine.models import SessionName

SCHEMA_VERSION = 1


class StrategyId(Enum):
    LIQUIDITY_SWEEP_MSS = "LIQUIDITY_SWEEP_MSS"
    BOS_FVG = "BOS_FVG"
    TREND_CONTINUATION = "TREND_CONTINUATION"
    SESSION_BREAKOUT = "SESSION_BREAKOUT"
    RANGE_REVERSAL = "RANGE_REVERSAL"


class MarketRegime(Enum):
    """The regime a strategy is designed for -- distinct from Evidence
    Engine's `TrendClassification`, which describes what was
    *observed*; this describes what a strategy *targets*."""

    TRENDING = "TRENDING"
    RANGING = "RANGING"
    BREAKOUT = "BREAKOUT"
    REVERSAL = "REVERSAL"


class QualificationStatus(Enum):
    QUALIFIED = "QUALIFIED"
    NOT_QUALIFIED = "NOT_QUALIFIED"  # self-check (regime/conditions) failed
    NOT_ELIGIBLE = "NOT_ELIGIBLE"  # pair outside the strategy's approved universe (hard gate)


@dataclass(frozen=True)
class QualificationResult:
    """Every strategy produces exactly one of these per pair. `score`
    and `confidence` are `0.0` whenever `status` is not `QUALIFIED` --
    ineligibility and self-disqualification are never partially
    scored (ADR-026 Hard Rules 3-4)."""

    strategy_id: StrategyId
    pair: str
    status: QualificationStatus
    score: float  # 0-100
    confidence: float  # 0-1
    reason: str
    strengths: Tuple[str, ...]
    weaknesses: Tuple[str, ...]


@dataclass(frozen=True)
class StrategyDefinition:
    """The 13 fields every strategy must declare (ADR-026 §1)."""

    strategy_id: StrategyId
    purpose: str
    market_regime: MarketRegime
    entry_conditions: Tuple[str, ...]
    exit_conditions: Tuple[str, ...]
    invalidation_conditions: Tuple[str, ...]
    preferred_sessions: Tuple[SessionName, ...]
    preferred_pairs: Tuple[str, ...]
    required_evidence_conditions: Tuple[str, ...]
    required_market_intelligence_conditions: Tuple[str, ...]
    expected_volatility: str
    required_support_resistance_context: Tuple[str, ...]
    required_candlestick_confirmation: Tuple[str, ...]
    required_liquidity_confirmation: Tuple[str, ...]


@dataclass(frozen=True)
class WinningStrategy:
    strategy_id: StrategyId
    qualification: QualificationResult


@dataclass(frozen=True)
class StrategySnapshot:
    """No trade direction, no execution, no sizing -- ever (ADR-026
    Hard Rule 1)."""

    pair: str
    generated_at: datetime
    winning_strategy: Optional[WinningStrategy]
    all_qualifications: Tuple[QualificationResult, ...]
    rejected: bool
    rejection_reason: Optional[str]
    supporting_evidence_summary: str
    supporting_market_intelligence_summary: str


__all__ = [
    "SCHEMA_VERSION",
    "StrategyId",
    "MarketRegime",
    "QualificationStatus",
    "QualificationResult",
    "StrategyDefinition",
    "WinningStrategy",
    "StrategySnapshot",
]
