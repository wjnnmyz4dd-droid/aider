"""Risk Engine package (ADR-005) — Phase 1.

Consumes only `ScoreResult` (ADR-004), the originating `CandidateTrade`
(ADR-003, read-only), the originating `ScannerObservation` (ADR-002,
read-only), and account/risk state; never connects to MT5; never
performs compliance; never modifies its inputs; never discards a
candidate. Produces only `RiskDecision` — one per `ScoreResult`, always
(ADR-005 §2, §3, §4).
"""

from __future__ import annotations

from .config import DEFAULT_CONFIG, RISK_ENGINE_VERSION, RiskEngineConfig
from .engine import SUPPORTED_SCORE_RESULT_SCHEMA_VERSIONS, RiskEngine
from .metrics import RiskEngineMetrics
from .models import (
    SCHEMA_VERSION,
    AccountState,
    ConstraintEvaluation,
    OpenPosition,
    RiskDecision,
    RiskTier,
)

__all__ = [
    "DEFAULT_CONFIG",
    "RISK_ENGINE_VERSION",
    "RiskEngineConfig",
    "SUPPORTED_SCORE_RESULT_SCHEMA_VERSIONS",
    "RiskEngine",
    "RiskEngineMetrics",
    "SCHEMA_VERSION",
    "AccountState",
    "ConstraintEvaluation",
    "OpenPosition",
    "RiskDecision",
    "RiskTier",
]
