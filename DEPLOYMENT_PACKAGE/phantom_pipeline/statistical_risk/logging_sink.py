"""Structured logging (`ADR-022` §4).

Mirrors `risk_engine.logging_sink`'s pattern: one structured record per
assessment, every field read directly off the object, a logging failure
never propagates into or alters this package's return value (logging is
observability, not a gate).
"""

from __future__ import annotations

import logging

from .models import StatisticalRiskAssessment

logger = logging.getLogger("phantom_pipeline.statistical_risk")


def log_assessment(assessment: StatisticalRiskAssessment, level: int = logging.INFO) -> None:
    try:
        logger.log(
            level,
            "statistical_risk.assessment",
            extra={
                "trace_id": assessment.trace_id,
                "schema_version": assessment.schema_version,
                "confidence_score": assessment.confidence_score,
                "risk_of_ruin": assessment.risk_of_ruin,
                "probability_of_drawdown": assessment.probability_of_drawdown,
                "portfolio_heat": assessment.portfolio_heat,
                "statistical_recommendation": assessment.statistical_recommendation.value,
            },
        )
    except Exception:
        # Logging is observability, not a gate (the same discipline every
        # prior stage established) — a logging failure must never
        # propagate into or alter this package's return value.
        pass


__all__ = ["log_assessment"]
