"""Data models for the Market Intelligence Engine (Phase 2B).

Every type here describes an observed external-market fact or a scored
evaluation of one. Nothing here is a trade decision: there is no
`BUY`/`SELL` enum, no position size, no strategy identifier anywhere in
this module, by design (see
`docs/adr/ADR-025-market-intelligence-engine.md` Hard Rule 1).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from enum import Enum
from typing import Optional, Tuple

from titan_protocol.evidence_engine.models import SessionName

SCHEMA_VERSION = 1


# -- News -----------------------------------------------------------------


class NewsImpact(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class NewsCategory(Enum):
    CENTRAL_BANK = "CENTRAL_BANK"
    INTEREST_RATE_DECISION = "INTEREST_RATE_DECISION"
    CPI = "CPI"
    PPI = "PPI"
    NFP = "NFP"
    GDP = "GDP"
    PMI = "PMI"
    EMPLOYMENT = "EMPLOYMENT"
    RETAIL_SALES = "RETAIL_SALES"
    INFLATION = "INFLATION"
    FOMC = "FOMC"
    ECB = "ECB"
    BOE = "BOE"
    BOJ = "BOJ"
    RBA = "RBA"
    RBNZ = "RBNZ"
    BOC = "BOC"
    SNB = "SNB"
    OTHER = "OTHER"


#: Categories that always require a blackout regardless of the event's
#: own labeled impact -- central-bank-flavored categories carry outsized
#: surprise risk even when pre-labeled MEDIUM. A single named set, not a
#: scattered set of magic checks.
CENTRAL_BANK_CATEGORIES = frozenset({
    NewsCategory.CENTRAL_BANK, NewsCategory.INTEREST_RATE_DECISION, NewsCategory.FOMC,
    NewsCategory.ECB, NewsCategory.BOE, NewsCategory.BOJ, NewsCategory.RBA,
    NewsCategory.RBNZ, NewsCategory.BOC, NewsCategory.SNB,
})


@dataclass(frozen=True)
class NewsEvent:
    event_id: str
    currency: str  # 3-letter ISO code, e.g. "USD"
    category: NewsCategory
    impact: NewsImpact
    scheduled_at: datetime
    released: bool
    released_at: Optional[datetime] = None


@dataclass(frozen=True)
class PairNewsIntelligence:
    pair: str
    upcoming_events: Tuple[NewsEvent, ...]
    active_events: Tuple[NewsEvent, ...]
    recent_events: Tuple[NewsEvent, ...]
    news_score: float  # 0-100
    blackout_active: bool
    blackout_reason: Optional[str]


# -- Peg / policy events ---------------------------------------------------


class PegPolicyEventType(Enum):
    CURRENCY_PEG = "CURRENCY_PEG"
    EMERGENCY_INTERVENTION = "EMERGENCY_INTERVENTION"
    POLICY_ANNOUNCEMENT = "POLICY_ANNOUNCEMENT"
    EXCHANGE_CONTROL = "EXCHANGE_CONTROL"
    UNEXPECTED_INTERVENTION = "UNEXPECTED_INTERVENTION"


@dataclass(frozen=True)
class PegPolicyStatus:
    active: bool
    event_type: Optional[PegPolicyEventType] = None
    reason: Optional[str] = None
    detected_at: Optional[datetime] = None
    cleared_at: Optional[datetime] = None


# -- Session ----------------------------------------------------------------


@dataclass(frozen=True)
class SessionIntelligence:
    session: SessionName
    session_score: float  # 0-100, MI-specific preference weighting
    preferred: bool
    reason: str


# -- Liquidity --------------------------------------------------------------


@dataclass(frozen=True)
class LiquidityIntelligence:
    current_spread: float
    average_spread: float
    spread_widening: bool
    liquidity_score: float  # 0-100
    reason: str


# -- Market safety ------------------------------------------------------------


@dataclass(frozen=True)
class MarketSafetyInputs:
    """Externally-supplied facts this engine never derives itself --
    holiday calendars, maintenance windows, and halt/closure flags come
    from an operator-maintained schedule or broker feed, not computed
    here."""

    holidays: Tuple[date, ...] = ()
    early_closes: Tuple[Tuple[date, time], ...] = ()
    broker_maintenance_active: bool = False
    trading_halted: bool = False
    market_closed: bool = False


@dataclass(frozen=True)
class MarketSafetyStatus:
    is_holiday: bool
    is_early_close: bool
    is_weekend_approaching: bool
    broker_maintenance: bool
    trading_halted: bool
    market_closed: bool
    safety_score: float  # 0-100
    reason: str


# -- Composite pair scoring ---------------------------------------------------


@dataclass(frozen=True)
class PairSafety:
    pair: str
    news: PairNewsIntelligence
    liquidity: LiquidityIntelligence
    session: SessionIntelligence
    market_safety: MarketSafetyStatus
    peg_policy: PegPolicyStatus
    pair_safety_score: float  # 0-100


@dataclass(frozen=True)
class TradeReadiness:
    """Advisory only -- never consulted by anything with authority to
    place, size, or approve a trade in this phase (ADR-025 Hard Rule 6)."""

    pair: str
    readiness_score: float  # 0-100
    reasons: Tuple[str, ...]


@dataclass(frozen=True)
class MarketIntelligenceExplanation:
    why_score_changed: str
    upcoming_events: Tuple[str, ...]
    current_restrictions: Tuple[str, ...]
    blackout_reason: Optional[str]
    session_reason: str
    liquidity_reason: str
    trade_readiness_explanation: str


@dataclass(frozen=True)
class MarketIntelligenceSnapshot:
    pair: str
    generated_at: datetime
    pair_safety: PairSafety
    trade_readiness: TradeReadiness
    explanation: MarketIntelligenceExplanation


__all__ = [
    "SCHEMA_VERSION",
    "NewsImpact",
    "NewsCategory",
    "CENTRAL_BANK_CATEGORIES",
    "NewsEvent",
    "PairNewsIntelligence",
    "PegPolicyEventType",
    "PegPolicyStatus",
    "SessionIntelligence",
    "LiquidityIntelligence",
    "MarketSafetyInputs",
    "MarketSafetyStatus",
    "PairSafety",
    "TradeReadiness",
    "MarketIntelligenceExplanation",
    "MarketIntelligenceSnapshot",
]
