"""Structured logging (ADR-003 §12).

Mirrors `phantom_pipeline.scanner.logging_sink`'s pattern: one structured
record per event, every field read directly off the object, a logging
failure never propagates into or alters engine behavior (logging is
observability, not a gate).

Every `CandidateTrade` record's `trace_id` is the propagated Scanner
`trace_id` (§12: "every record shares the trace_id established at the
Scanner stage"), so a single market observation's journey through the
Strategy Engine stays correlated with its Scanner log lines.
"""

from __future__ import annotations

import logging
from typing import Sequence

from .models import CandidateTrade

logger = logging.getLogger("phantom_pipeline.strategy_engine")


def log_candidate_trade(candidate: CandidateTrade, level: int = logging.INFO) -> None:
    try:
        logger.log(
            level,
            "strategy_engine.candidate_trade",
            extra={
                "trace_id": candidate.trace_id,
                "schema_version": candidate.schema_version,
                "strategy_id": candidate.strategy_id,
                "symbol": candidate.symbol,
                "timeframe": candidate.timeframe,
                "candidate_id": candidate.candidate_id,
                "timestamp": candidate.timestamp.isoformat(),
                "scanner_observation_trace_id": candidate.trace_id,
                "direction": candidate.direction.value,
            },
        )
    except Exception:
        # Logging is observability, not a gate (ADR-002 §11's discipline,
        # extended here per ADR-003 §12) — a logging failure must never
        # propagate into or alter engine behavior.
        pass


def log_playbook_abstention(
    strategy_id: str, reason: str, observation_trace_id: str, level: int = logging.DEBUG
) -> None:
    try:
        logger.log(
            level,
            "strategy_engine.playbook_abstention",
            extra={
                "strategy_id": strategy_id,
                "reason": reason,
                "trace_id": observation_trace_id,
            },
        )
    except Exception:
        pass


def log_playbook_failure(
    strategy_id: str,
    version: str,
    observation_trace_id: str,
    error: BaseException,
    level: int = logging.ERROR,
) -> None:
    try:
        logger.log(
            level,
            "strategy_engine.playbook_failure",
            extra={
                "strategy_id": strategy_id,
                "version": version,
                "trace_id": observation_trace_id,
                "error": repr(error),
            },
        )
    except Exception:
        pass


def log_registry_initialized(registered_ids: Sequence[str], level: int = logging.INFO) -> None:
    """A registry lifecycle event, logged distinctly from per-call
    hypothesis records (ADR-003 §12)."""
    try:
        logger.log(
            level,
            "strategy_engine.registry_initialized",
            extra={"registered_ids": list(registered_ids)},
        )
    except Exception:
        pass


def log_duplicate_strategy_id(conflicts: Sequence[dict], level: int = logging.ERROR) -> None:
    try:
        logger.log(
            level,
            "strategy_engine.duplicate_strategy_id",
            extra={"conflicts": list(conflicts)},
        )
    except Exception:
        pass
