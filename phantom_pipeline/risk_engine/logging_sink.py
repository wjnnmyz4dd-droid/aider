"""Structured logging (ADR-005 §16).

Mirrors `phantom_pipeline.scoring_engine.logging_sink`'s pattern: one
structured record per event, every field read directly off the object, a
logging failure never propagates into or alters engine behavior (logging
is observability, not a gate).

Every `RiskDecision`'s `trace_id`/`candidate_id` are the propagated
`ScoreResult` values verbatim, extending the chain established at Scanner
through Strategy Engine and Scoring Engine into risk budgeting.
"""

from __future__ import annotations

import logging

from .models import ConstraintEvaluation, RiskDecision

logger = logging.getLogger("phantom_pipeline.risk_engine")


def log_risk_decision(decision: RiskDecision, level: int = logging.INFO) -> None:
    try:
        logger.log(
            level,
            "risk_engine.risk_decision",
            extra={
                "trace_id": decision.trace_id,
                "schema_version": decision.schema_version,
                "candidate_id": decision.candidate_id,
                "risk_engine_version": decision.risk_engine_version,
                "approved_risk_amount": decision.approved_risk_amount,
                "approved_risk_percent": decision.approved_risk_percent,
                "limiting_constraint": decision.limiting_constraint,
                "reason_codes": list(decision.reason_codes),
            },
        )
    except Exception:
        # Logging is observability, not a gate (the same discipline every
        # prior stage established) — a logging failure must never
        # propagate into or alter engine behavior.
        pass


def log_constraint_evaluation(
    candidate_id: str,
    trace_id: str,
    evaluation: ConstraintEvaluation,
    level: int = logging.DEBUG,
) -> None:
    """Per-constraint record — a distinct granularity from the
    per-candidate `RiskDecision` record (ADR-005 §16: "which
    constraint(s) were binding")."""
    try:
        logger.log(
            level,
            "risk_engine.constraint_evaluation",
            extra={
                "candidate_id": candidate_id,
                "trace_id": trace_id,
                "constraint": evaluation.constraint,
                "allowed_risk_percent": evaluation.allowed_risk_percent,
                "binding": evaluation.binding,
                "detail": evaluation.detail,
            },
        )
    except Exception:
        pass


def log_fail_closed(
    candidate_id: str, trace_id: str, reason: str, level: int = logging.WARNING
) -> None:
    """Any fail-closed trigger (§15) logged with enough detail to
    diagnose without blocking the pipeline."""
    try:
        logger.log(
            level,
            "risk_engine.fail_closed",
            extra={"candidate_id": candidate_id, "trace_id": trace_id, "reason": reason},
        )
    except Exception:
        pass
