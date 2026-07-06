"""Compliance Engine package (ADR-006) — Phase 1.

Consumes only `RiskDecision` (ADR-005), the originating `CandidateTrade`
(ADR-003, read-only) and `ScoreResult` (ADR-004, read-only), account
state, broker/market state (`MarketSnapshot`, ADR-013), and news state;
never connects to MT5; never sizes or scores; never modifies its inputs;
never discards a candidate. Produces only `ComplianceDecision` — one per
`RiskDecision`, always (ADR-006 §2, §3, §4).
"""

from __future__ import annotations

from .config import COMPLIANCE_ENGINE_VERSION, DEFAULT_CONFIG, ComplianceEngineConfig, SessionWindow
from .engine import SUPPORTED_RISK_DECISION_SCHEMA_VERSIONS, ComplianceEngine
from .metrics import ComplianceEngineMetrics
from .models import (
    SCHEMA_VERSION,
    AccountState,
    CheckEvaluation,
    CheckStatus,
    ComplianceDecision,
    NewsBlackoutWindow,
    NewsCalendarState,
    OpenPosition,
    Verdict,
)
from .state_store import ComplianceStateStore, InMemoryComplianceStateStore, SqliteComplianceStateStore

__all__ = [
    "COMPLIANCE_ENGINE_VERSION",
    "DEFAULT_CONFIG",
    "ComplianceEngineConfig",
    "SessionWindow",
    "SUPPORTED_RISK_DECISION_SCHEMA_VERSIONS",
    "ComplianceEngine",
    "ComplianceEngineMetrics",
    "SCHEMA_VERSION",
    "AccountState",
    "CheckEvaluation",
    "CheckStatus",
    "ComplianceDecision",
    "NewsBlackoutWindow",
    "NewsCalendarState",
    "OpenPosition",
    "Verdict",
    "ComplianceStateStore",
    "InMemoryComplianceStateStore",
    "SqliteComplianceStateStore",
]
