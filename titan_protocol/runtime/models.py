"""Data models for the Runtime Orchestrator (Phase 3A, ADR-031).

Every type here is either configuration (a `TradingProfile`, itself
only references to the six engines' own already-existing config types
-- never a second risk/compliance/news implementation), an immutable
per-cycle record (`RuntimeContext`, `RuntimeAuditRecord`), or a plain
enum. Nothing here computes a trading decision: there is no scoring
formula, no risk formula, no compliance rule anywhere in this module
(ADR-031 Hard Rules).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple

from titan_protocol.bridge.models import ErrorCode
from titan_protocol.compliance_engine.models import AccountState, ComplianceDecision, ComplianceSnapshot
from titan_protocol.evidence_engine.models import EvidenceSnapshot, SessionName
from titan_protocol.market_intelligence.config import MarketIntelligenceConfig
from titan_protocol.market_intelligence.models import MarketIntelligenceSnapshot
from titan_protocol.risk_engine.config import RiskEngineConfig
from titan_protocol.risk_engine.models import PortfolioState, RiskSnapshot
from titan_protocol.strategy_engine.models import StrategyId, StrategySnapshot, TradeIntent

SCHEMA_VERSION = 1


# -- Trading Profiles (ADR-031 SS4-5) -----------------------------------------


@dataclass(frozen=True)
class TradingWindow:
    """A fixed UTC hour-of-day window, active on the given weekdays
    (Monday=0). No timezone/DST logic -- operator-configured, in UTC,
    like every other engine's session/news window this session built."""

    start_hour_utc: int
    end_hour_utc: int
    days_of_week: Tuple[int, ...] = (0, 1, 2, 3, 4)

    def contains(self, now: datetime) -> bool:
        return now.weekday() in self.days_of_week and self.start_hour_utc <= now.hour < self.end_hour_utc


@dataclass(frozen=True)
class TradingProfile:
    """Configuration only -- no duplicate logic (ADR-031 SS4). `risk_profile`/
    `news_policy` are references to `risk_engine`/`market_intelligence`'s
    own config types, never a second implementation. Configuration
    Versioning (ADR-031 SS5) fields are carried directly on the profile."""

    profile_id: str
    version: int
    created_at: datetime
    modified_at: datetime
    author: str
    description: str

    trading_window: TradingWindow
    allowed_pairs: Tuple[str, ...]
    allowed_strategies: Tuple[StrategyId, ...]
    session_rules: Tuple[SessionName, ...]
    news_policy: MarketIntelligenceConfig
    risk_profile: RiskEngineConfig
    compliance_rule_profile_name: str


# -- Runtime context (ADR-031 SS6) --------------------------------------------


@dataclass(frozen=True)
class RuntimeContext:
    """One immutable record per pair per cycle. No engine mutates this
    -- each stage receives only the specific fields its own `evaluate()`
    signature already required (ADR-031 SS6)."""

    pair: str
    now: datetime
    profile: TradingProfile
    evidence: EvidenceSnapshot
    market_intelligence: MarketIntelligenceSnapshot
    strategy: StrategySnapshot
    risk: RiskSnapshot
    compliance: ComplianceSnapshot
    portfolio_state: PortfolioState
    account_state: AccountState
    correlation_reservations: Tuple[str, ...] = ()


# -- Cycle outcome / audit (ADR-031 SS7, SS12) --------------------------------


class CycleStage(Enum):
    EVIDENCE = "EVIDENCE"
    MARKET_INTELLIGENCE = "MARKET_INTELLIGENCE"
    STRATEGY = "STRATEGY"
    RISK = "RISK"
    COMPLIANCE = "COMPLIANCE"
    BRIDGE = "BRIDGE"


class CycleOutcome(Enum):
    SUBMITTED = "SUBMITTED"
    OUTSIDE_TRADING_WINDOW = "OUTSIDE_TRADING_WINDOW"
    SESSION_NOT_ALLOWED = "SESSION_NOT_ALLOWED"
    NO_STRATEGY = "NO_STRATEGY"
    RISK_REJECTED = "RISK_REJECTED"
    COMPLIANCE_REJECTED = "COMPLIANCE_REJECTED"
    BRIDGE_ERROR = "BRIDGE_ERROR"
    FAILED = "FAILED"


@dataclass(frozen=True)
class StageTiming:
    stage: CycleStage
    duration_ms: float


@dataclass(frozen=True)
class RuntimeAuditRecord:
    """No trade instruction beyond what the pipeline already approved
    -- pure record (ADR-031 SS12).

    Final Release Hardening (requirement 4, audit-record completeness)
    added the fields below `engine_versions`. Every one of them records
    an already-computed value from another engine's own snapshot (or a
    hash/ID derived purely from values already on this same record) --
    none of them duplicate a calculation (CLAUDE.md SS1.4). In
    particular, `market_intelligence_summary` records Market
    Intelligence's own computed trade-readiness explanation, never
    which news provider produced its events -- Market Intelligence
    itself is never told the provider (Phase 3E), so this record can't
    be either; provider identity stays recorded only in the deployment
    layer's health.json."""

    cycle_id: str
    pair: str
    profile_id: str
    configuration_version: int
    started_at: datetime
    ended_at: datetime
    duration_ms: float
    outcome: CycleOutcome
    stage_reached: Optional[CycleStage]
    evidence_id: Optional[str]
    selected_strategy: Optional[StrategyId]
    trade_intent: TradeIntent
    risk_approved: Optional[bool]
    compliance_decision: Optional[ComplianceDecision]
    bridge_error: Optional[ErrorCode]
    reasons: Tuple[str, ...]
    stage_timings: Tuple[StageTiming, ...]
    engine_versions: Tuple[Tuple[str, str], ...]

    # -- Final Release Hardening additions (all defaulted -- additive only) --
    decision_id: str = ""
    config_schema_version: int = 0
    timeframe: str = ""
    evidence_summary: str = ""
    market_intelligence_summary: str = ""
    risk_reasons: Tuple[str, ...] = ()
    compliance_triggered_rules: Tuple[str, ...] = ()
    compliance_lock_trigger: Optional[bool] = None
    compliance_lock_reason: Optional[str] = None
    bridge_correlation_id: Optional[str] = None
    snapshot_hash: str = ""
    decision_fingerprint: str = ""


@dataclass(frozen=True)
class CycleReport:
    """One full multi-pair cycle's outcome."""

    cycle_id: str
    started_at: datetime
    ended_at: datetime
    duration_ms: float
    records: Tuple[RuntimeAuditRecord, ...]


# -- Startup configuration validation (ADR-031 SS11) --------------------------


@dataclass(frozen=True)
class ConfigValidationIssue:
    field: str
    message: str


@dataclass(frozen=True)
class ConfigValidationResult:
    valid: bool
    issues: Tuple[ConfigValidationIssue, ...] = ()


# -- Watchdog integration (ADR-031 SS9, fresh -- never phantom_pipeline) ------


class WatchdogTimeoutKind(Enum):
    ENGINE = "ENGINE"
    RUNTIME = "RUNTIME"
    SNAPSHOT = "SNAPSHOT"
    BRIDGE = "BRIDGE"


@dataclass(frozen=True)
class WatchdogSignal:
    kind: WatchdogTimeoutKind
    component: str
    duration_ms: float
    threshold_ms: float


__all__ = [
    "SCHEMA_VERSION",
    "TradingWindow",
    "TradingProfile",
    "RuntimeContext",
    "CycleStage",
    "CycleOutcome",
    "StageTiming",
    "RuntimeAuditRecord",
    "CycleReport",
    "ConfigValidationIssue",
    "ConfigValidationResult",
    "WatchdogTimeoutKind",
    "WatchdogSignal",
]
