"""Structured logging (ADR-006 §16).

Mirrors `phantom_pipeline.risk_engine.logging_sink`'s pattern: one
structured record per event, every field read directly off the object, a
logging failure never propagates into or alters engine behavior (logging
is observability, not a gate).

Kill-switch and daily-lockout state transitions are logged distinctly
from per-candidate `ComplianceDecision` records, since they are
account-level events, not per-candidate ones (ADR-006 §16).
"""

from __future__ import annotations

import logging

from .models import CheckEvaluation, ComplianceDecision

logger = logging.getLogger("phantom_pipeline.compliance_engine")


def log_compliance_decision(decision: ComplianceDecision, level: int = logging.INFO) -> None:
    try:
        logger.log(
            level,
            "compliance_engine.compliance_decision",
            extra={
                "trace_id": decision.trace_id,
                "schema_version": decision.schema_version,
                "candidate_id": decision.candidate_id,
                "compliance_engine_version": decision.compliance_engine_version,
                "verdict": decision.verdict.value,
                "blocking_rules": list(decision.blocking_rules),
                "reason_codes": list(decision.reason_codes),
            },
        )
    except Exception:
        # Logging is observability, not a gate — a logging failure must
        # never propagate into or alter engine behavior.
        pass


def log_check_evaluation(
    candidate_id: str, trace_id: str, evaluation: CheckEvaluation, level: int = logging.DEBUG
) -> None:
    try:
        logger.log(
            level,
            "compliance_engine.check_evaluation",
            extra={
                "candidate_id": candidate_id,
                "trace_id": trace_id,
                "check": evaluation.check,
                "status": evaluation.status.value,
                "detail": evaluation.detail,
            },
        )
    except Exception:
        pass


def log_malformed_request(
    candidate_id: str, trace_id: str, reason: str, level: int = logging.WARNING
) -> None:
    try:
        logger.log(
            level,
            "compliance_engine.malformed_request",
            extra={"candidate_id": candidate_id, "trace_id": trace_id, "reason": reason},
        )
    except Exception:
        pass


def log_kill_switch_triggered(
    reason: str, trace_id: str, level: int = logging.CRITICAL
) -> None:
    """An account-level, permanent state transition (ADR-006 §14) —
    distinct from any single candidate's `ComplianceDecision`."""
    try:
        logger.log(
            level,
            "compliance_engine.kill_switch_triggered",
            extra={"reason": reason, "triggering_trace_id": trace_id},
        )
    except Exception:
        pass


def log_daily_lockout_triggered(
    day: str, reason: str, trace_id: str, level: int = logging.WARNING
) -> None:
    """An account-level, per-day state transition (ADR-006 §6, §16) —
    distinct from any single candidate's `ComplianceDecision`."""
    try:
        logger.log(
            level,
            "compliance_engine.daily_lockout_triggered",
            extra={"day": day, "reason": reason, "triggering_trace_id": trace_id},
        )
    except Exception:
        pass
