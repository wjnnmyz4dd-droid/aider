"""Structured logging (ADR-007 §10). Structured logging only — no
`print()`.

Mirrors `phantom_pipeline.compliance_engine.logging_sink`'s pattern: one
structured record per event, every field read directly off the object, a
logging failure never propagates into or alters engine behavior (logging
is observability, not a gate). Every validation step is logged, not only
the final verdict (§10) — see `log_check_evaluation`, called once per
check regardless of PASS/FAIL/UNEVALUABLE.
"""

from __future__ import annotations

import logging

from .models import CheckEvaluation, ExecutionDecision

logger = logging.getLogger("phantom_pipeline.execution_validator")


def log_execution_decision(decision: ExecutionDecision, level: int = logging.INFO) -> None:
    try:
        logger.log(
            level,
            "execution_validator.execution_decision",
            extra={
                "trace_id": decision.trace_id,
                "schema_version": decision.schema_version,
                "candidate_id": decision.candidate_id,
                "execution_validator_version": decision.execution_validator_version,
                "verdict": decision.verdict.value,
                "blocking_reasons": list(decision.blocking_reasons),
                "reason_codes": list(decision.reason_codes),
                "warnings": list(decision.warnings),
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
            "execution_validator.check_evaluation",
            extra={
                "candidate_id": candidate_id,
                "trace_id": trace_id,
                "validation_stage": evaluation.check,
                "status": evaluation.status.value,
                "detail": evaluation.detail,
            },
        )
    except Exception:
        pass


def log_rejection(
    candidate_id: str, trace_id: str, reason: str, timestamp, validation_stage: str, level: int = logging.WARNING
) -> None:
    """Every rejection includes reason, timestamp, trace_id, and the
    specific validation stage that produced it (ADR-007 §10) — a distinct
    record from the general per-check log for direct rejection
    attribution without re-running anything."""
    try:
        logger.log(
            level,
            "execution_validator.rejection",
            extra={
                "candidate_id": candidate_id,
                "trace_id": trace_id,
                "reason": reason,
                "timestamp": timestamp.isoformat() if timestamp is not None else None,
                "validation_stage": validation_stage,
            },
        )
    except Exception:
        pass
