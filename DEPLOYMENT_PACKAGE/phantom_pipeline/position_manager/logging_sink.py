"""Structured logging (ADR-009 §12). Structured logging only — no
`print()`.

Every position action carries `trace_id`, `position_id`,
`decision_reason`, and `timestamp` (§12) — attributable to a specific
position and rule without re-running anything, the same explainability
discipline established at every prior stage. A logging failure never
propagates into or alters engine behavior.
"""

from __future__ import annotations

import logging

from .models import PositionManagementDecision, PositionSynchronizationResult, PositionUpdate, RuleEvaluation

logger = logging.getLogger("phantom_pipeline.position_manager")


def _safe_log(level: int, msg: str, extra: dict) -> None:
    try:
        logger.log(level, msg, extra=extra)
    except Exception:
        pass


def log_management_decision(decision: PositionManagementDecision, level: int = logging.INFO) -> None:
    _safe_log(
        level,
        "position_manager.management_decision",
        {
            "trace_id": decision.trace_id,
            "position_id": decision.position_id,
            "action": decision.action.value,
            "decision_reason": decision.decision_reason,
            "timestamp": decision.timestamp.isoformat(),
        },
    )


def log_rule_evaluation(position_id: str, trace_id: str, evaluation: RuleEvaluation, level: int = logging.DEBUG) -> None:
    _safe_log(
        level,
        "position_manager.rule_evaluation",
        {
            "position_id": position_id,
            "trace_id": trace_id,
            "rule": evaluation.rule,
            "status": evaluation.status.value,
            "detail": evaluation.detail,
        },
    )


def log_position_update(update: PositionUpdate, level: int = logging.DEBUG) -> None:
    _safe_log(
        level,
        "position_manager.position_update",
        {
            "position_id": update.position_id,
            "trace_id": update.trace_id,
            "lifecycle_state": update.lifecycle_state.value,
            "unrealized_pnl": update.unrealized_pnl,
        },
    )


def log_synchronization_result(result: PositionSynchronizationResult, level: int = logging.WARNING) -> None:
    _safe_log(
        level,
        "position_manager.synchronization_result",
        {
            "position_id": result.position_id,
            "trace_id": result.trace_id,
            "lifecycle_state": result.lifecycle_state.value,
            "broker_position_found": result.broker_position_found,
            "detail": result.detail,
        },
    )
