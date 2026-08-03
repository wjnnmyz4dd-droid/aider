"""Execution Validator package (ADR-007) — Phase 1.

Consumes only `ComplianceDecision` (ADR-006), the originating
`RiskDecision` (ADR-005), `ScoreResult` (ADR-004), and `CandidateTrade`
(ADR-003) — all read-only — plus a fresh market/broker/account state
read; never connects to MT5 for order placement; never sizes, scores, or
performs policy compliance; never modifies its inputs; never discards a
candidate. Produces only `ExecutionDecision` — one per
`ComplianceDecision`, always (ADR-007 §2, §3, §4).
"""

from __future__ import annotations

from .config import DEFAULT_CONFIG, EXECUTION_VALIDATOR_VERSION, ExecutionValidatorConfig
from .engine import ExecutionValidator
from .idempotency_store import IdempotencyStore, InMemoryIdempotencyStore
from .metrics import ExecutionValidatorMetrics
from .models import (
    SCHEMA_VERSION,
    AccountState,
    BrokerState,
    CheckEvaluation,
    CheckStatus,
    ExecutionDecision,
    Verdict,
)

__all__ = [
    "DEFAULT_CONFIG",
    "EXECUTION_VALIDATOR_VERSION",
    "ExecutionValidatorConfig",
    "ExecutionValidator",
    "IdempotencyStore",
    "InMemoryIdempotencyStore",
    "ExecutionValidatorMetrics",
    "SCHEMA_VERSION",
    "AccountState",
    "BrokerState",
    "CheckEvaluation",
    "CheckStatus",
    "ExecutionDecision",
    "Verdict",
]
