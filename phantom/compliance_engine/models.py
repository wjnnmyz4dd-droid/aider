"""Data models for the Prop Firm Compliance Engine (Phase 2E).

Every type here is either a plain, immutable record of operational
account state supplied by a caller (`AccountState`, `ComplianceLockState`)
or a computed compliance evaluation of one. Nothing here is a trade
decision: there is no `BUY`/`SELL` enum, no direction, no order type,
anywhere in this module, by design (see
`docs/adr/ADR-028-compliance-engine.md` Hard Rule 1).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple

from phantom.evidence_engine.models import SessionName

SCHEMA_VERSION = 1


class ComplianceDecision(Enum):
    APPROVE = "APPROVE"
    REDUCE = "REDUCE"
    REJECT = "REJECT"


class ComplianceRuleId(Enum):
    EMERGENCY_STOP_ACTIVE = "EMERGENCY_STOP_ACTIVE"
    COMPLIANCE_LOCK_ACTIVE = "COMPLIANCE_LOCK_ACTIVE"
    RISK_NOT_APPROVED = "RISK_NOT_APPROVED"
    NO_QUALIFIED_STRATEGY = "NO_QUALIFIED_STRATEGY"
    TRADING_HALTED = "TRADING_HALTED"
    MARKET_CLOSED = "MARKET_CLOSED"
    BROKER_MAINTENANCE = "BROKER_MAINTENANCE"
    HOLIDAY = "HOLIDAY"
    PAIR_DISABLED = "PAIR_DISABLED"
    SESSION_NOT_APPROVED = "SESSION_NOT_APPROVED"
    NEWS_BLACKOUT = "NEWS_BLACKOUT"
    PEG_POLICY_ACTIVE = "PEG_POLICY_ACTIVE"
    SPREAD_TOO_HIGH = "SPREAD_TOO_HIGH"
    WEEKEND_RESTRICTION = "WEEKEND_RESTRICTION"
    STOP_LOSS_MISSING = "STOP_LOSS_MISSING"
    DAILY_LOSS_LIMIT_EXCEEDED = "DAILY_LOSS_LIMIT_EXCEEDED"
    TOTAL_DRAWDOWN_EXCEEDED = "TOTAL_DRAWDOWN_EXCEEDED"
    CONSECUTIVE_LOSS_PAUSE = "CONSECUTIVE_LOSS_PAUSE"
    MAX_OPEN_POSITIONS_EXCEEDED = "MAX_OPEN_POSITIONS_EXCEEDED"
    MAX_POSITIONS_PER_PAIR_EXCEEDED = "MAX_POSITIONS_PER_PAIR_EXCEEDED"
    MAX_CURRENCY_EXPOSURE_EXCEEDED = "MAX_CURRENCY_EXPOSURE_EXCEEDED"
    MAX_SYMBOL_EXPOSURE_EXCEEDED = "MAX_SYMBOL_EXPOSURE_EXCEEDED"
    MAX_PENDING_ORDERS_EXCEEDED = "MAX_PENDING_ORDERS_EXCEEDED"
    MAX_SIMULTANEOUS_RISK_EXCEEDED = "MAX_SIMULTANEOUS_RISK_EXCEEDED"
    MAX_TRADES_PER_DAY_EXCEEDED = "MAX_TRADES_PER_DAY_EXCEEDED"
    CONSISTENCY_RULE_VIOLATED = "CONSISTENCY_RULE_VIOLATED"
    INSUFFICIENT_CONFIDENCE_FOR_ELEVATED_LOSS_BAND = "INSUFFICIENT_CONFIDENCE_FOR_ELEVATED_LOSS_BAND"
    INSUFFICIENT_QUALITY_FOR_ELEVATED_LOSS_BAND = "INSUFFICIENT_QUALITY_FOR_ELEVATED_LOSS_BAND"
    DAILY_LOSS_REDUCTION = "DAILY_LOSS_REDUCTION"
    DRAWDOWN_REDUCTION = "DRAWDOWN_REDUCTION"
    PROFIT_PROTECTION_REDUCTION = "PROFIT_PROTECTION_REDUCTION"
    PROFIT_PROTECTION_STOP = "PROFIT_PROTECTION_STOP"


@dataclass(frozen=True)
class GraduatedBand:
    """One band of a graduated risk-reduction curve (ADR-028 §5.1-5.3).
    Shared by the daily-loss, total-drawdown, and daily-profit-protection
    curves -- one type, three configurations, per CLAUDE.md §6 (three
    similar structures collapse into one, never three near-duplicates)."""

    min_pct: float
    max_pct: float
    multiplier: float  # applied to the original size; 1.0 = no reduction
    hard_reject: bool = False
    min_evidence_score: Optional[float] = None  # below this, reject instead of reduce
    min_strategy_score: Optional[float] = None  # below this, reject instead of reduce
    label: str = ""


@dataclass(frozen=True)
class ComplianceRuleProfile:
    """A fully generic, config-driven bundle of prop-firm-style
    thresholds (ADR-028 Hard Rule 9 -- never hard-coded to one firm).
    The shipped default is an illustrative example, not a literal
    "FTMO" profile."""

    name: str = "example_generic_profile"
    max_daily_loss_pct: float = 5.0
    max_total_drawdown_pct: float = 10.0
    profit_target_pct: Optional[float] = 10.0  # informational only, never blocks a trade
    min_trading_days: Optional[int] = 4  # informational only
    max_open_positions: int = 10
    max_positions_per_pair: int = 2
    max_currency_exposure_r: float = 4.0
    max_symbol_exposure_r: float = 2.0
    max_pending_orders: int = 5
    max_simultaneous_risk_r: float = 4.0
    max_trades_per_day: int = 10
    weekend_holding_allowed: bool = True
    required_stop_loss: bool = True
    max_spread: float = 3.0
    news_restriction_enabled: bool = True
    approved_sessions: Tuple[SessionName, ...] = (
        SessionName.LONDON, SessionName.LONDON_NEW_YORK_OVERLAP, SessionName.EARLY_NEW_YORK,
    )
    consistency_max_single_day_share: float = 0.3  # no single day > 30% of total profit


@dataclass(frozen=True)
class ComplianceLockState:
    """Current lock status going INTO an `evaluate()` call -- caller-
    owned, never mutated by this engine (ADR-028 §3)."""

    active: bool = False
    reason: Optional[str] = None
    locked_at: Optional[datetime] = None
    resets_at: Optional[datetime] = None


@dataclass(frozen=True)
class LockRecommendation:
    """Advisory only: whether the caller should persist a new lock into
    the *next* `AccountState` it supplies. This engine never applies the
    lock itself (ADR-028 §3)."""

    trigger: bool
    reason: Optional[str] = None


@dataclass(frozen=True)
class AccountState:
    """Every operational account fact this engine's rules need that no
    upstream snapshot carries (ADR-028 §3) -- pre-aggregated only, never
    raw trade history."""

    account_balance: float
    daily_starting_balance: float
    peak_balance: float
    compliance_lock: ComplianceLockState
    consecutive_losses: int = 0
    trading_days_count: int = 0
    trades_today_count: int = 0
    pending_orders_count: int = 0
    best_single_day_profit_pct: Optional[float] = None
    cumulative_profit_pct: Optional[float] = None
    emergency_stop_active: bool = False
    rule_profile_name: str = "example_generic_profile"


@dataclass(frozen=True)
class AuditEntry:
    pair: str
    decision: ComplianceDecision
    triggered_rules: Tuple[ComplianceRuleId, ...]
    original_size_r: float
    final_size_r: float
    timestamp: datetime
    reason: str


@dataclass(frozen=True)
class ComplianceSnapshot:
    """No execution, no direction, ever (ADR-028 Hard Rule 1)."""

    pair: str
    generated_at: datetime
    decision: ComplianceDecision
    approved_size_r: float
    original_size_r: float
    reduction_pct: float
    reason: str
    triggered_rules: Tuple[ComplianceRuleId, ...]
    warnings: Tuple[str, ...]
    audit_entry: AuditEntry
    compliance_score: float
    lock_recommendation: Optional[LockRecommendation]
    ready_for_bridge: bool


__all__ = [
    "SCHEMA_VERSION",
    "ComplianceDecision",
    "ComplianceRuleId",
    "GraduatedBand",
    "ComplianceRuleProfile",
    "ComplianceLockState",
    "LockRecommendation",
    "AccountState",
    "AuditEntry",
    "ComplianceSnapshot",
]
