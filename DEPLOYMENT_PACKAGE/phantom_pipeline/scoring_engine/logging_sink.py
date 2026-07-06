"""Structured logging (ADR-004 §10).

Mirrors `phantom_pipeline.strategy_engine.logging_sink`'s pattern: one
structured record per event, every field read directly off the object, a
logging failure never propagates into or alters engine behavior (logging
is observability, not a gate).

Every `ScoreResult`/`ScoringFailureRecord`'s `trace_id` and `candidate_id`
are the propagated Strategy Engine values verbatim, extending the chain
`ADR-002` §11 established through `ADR-003` §12 into scoring.
"""

from __future__ import annotations

import logging
from typing import Sequence

from .models import RuleContribution, ScoreResult, ScoringFailureRecord

logger = logging.getLogger("phantom_pipeline.scoring_engine")


def log_score_result(result: ScoreResult, level: int = logging.INFO) -> None:
    try:
        logger.log(
            level,
            "scoring_engine.score_result",
            extra={
                "trace_id": result.trace_id,
                "schema_version": result.schema_version,
                "candidate_id": result.candidate_id,
                "strategy_id": result.strategy_id,
                "symbol": result.symbol,
                "timeframe": result.timeframe,
                "overall_score": result.overall_score,
                "scoring_version": result.scoring_version,
                "factor_summary": {fb.factor: fb.subtotal for fb in result.factor_breakdown},
            },
        )
    except Exception:
        # Logging is observability, not a gate (ADR-002 §11's discipline,
        # extended through ADR-003 §12 into ADR-004 §10) — a logging
        # failure must never propagate into or alter engine behavior.
        pass


def log_scoring_failure_record(record: ScoringFailureRecord, level: int = logging.ERROR) -> None:
    try:
        logger.log(
            level,
            "scoring_engine.scoring_failure_record",
            extra={
                "trace_id": record.trace_id,
                "schema_version": record.schema_version,
                "candidate_id": record.candidate_id,
                "strategy_id": record.strategy_id,
                "reason": record.reason,
                "scoring_version": record.scoring_version,
            },
        )
    except Exception:
        pass


def log_rule_execution(
    candidate_id: str,
    trace_id: str,
    contribution: RuleContribution,
    level: int = logging.DEBUG,
) -> None:
    """Per-rule fired/abstained/failed record — a distinct granularity
    from the per-candidate `ScoreResult` record (ADR-004 §10)."""
    try:
        logger.log(
            level,
            "scoring_engine.rule_execution",
            extra={
                "candidate_id": candidate_id,
                "trace_id": trace_id,
                "rule_id": contribution.rule_id,
                "rule_version": contribution.rule_version,
                "outcome": contribution.outcome.value,
                "points": contribution.points,
                "weight": contribution.weight,
                "detail": contribution.detail,
            },
        )
    except Exception:
        pass


def log_registry_initialized(registered_ids: Sequence[str], level: int = logging.INFO) -> None:
    """A registry lifecycle event, logged distinctly from per-call
    scoring records (ADR-004 §10)."""
    try:
        logger.log(
            level,
            "scoring_engine.registry_initialized",
            extra={"registered_ids": list(registered_ids)},
        )
    except Exception:
        pass


def log_duplicate_rule_id(conflicts: Sequence[dict], level: int = logging.ERROR) -> None:
    try:
        logger.log(
            level,
            "scoring_engine.duplicate_rule_id",
            extra={"conflicts": list(conflicts)},
        )
    except Exception:
        pass
