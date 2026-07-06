"""Structured logging (ADR-010). Structured logging only — no `print()`.

Every collection event and every produced record carries `trace_id`,
extending the trace chain established at every prior stage. A logging
failure never propagates into or alters engine behavior.
"""

from __future__ import annotations

import logging

from .models import MissingEventReport, PerformanceStatistics, ReplayInputSet, TradeProvenanceRecord

logger = logging.getLogger("phantom_pipeline.analytics")


def _safe_log(level: int, msg: str, extra: dict) -> None:
    try:
        logger.log(level, msg, extra=extra)
    except Exception:
        pass


def log_collected(trace_id: str, kind: str, level: int = logging.DEBUG) -> None:
    _safe_log(level, "analytics.collected", {"trace_id": trace_id, "kind": kind})


def log_provenance_record(record: TradeProvenanceRecord, level: int = logging.INFO) -> None:
    _safe_log(
        level,
        "analytics.provenance_record",
        {
            "trace_id": record.trace_id,
            "schema_version": record.schema_version,
            "analytics_version": record.analytics_version,
            "outcome_kind": record.final_outcome.outcome_kind.value if record.final_outcome else None,
        },
    )


def log_missing_event(report: MissingEventReport, level: int = logging.WARNING) -> None:
    _safe_log(
        level,
        "analytics.missing_event",
        {"trace_id": report.trace_id, "missing_fields": list(report.missing_fields), "detail": report.detail},
    )


def log_performance_statistics(stats: PerformanceStatistics, level: int = logging.INFO) -> None:
    _safe_log(
        level,
        "analytics.performance_statistics",
        {"trade_count": stats.trade_count, "win_rate": stats.win_rate, "expectancy": stats.expectancy},
    )


def log_replay_input_set(replay_set: ReplayInputSet, level: int = logging.INFO) -> None:
    _safe_log(level, "analytics.replay_input_set", {"trace_id": replay_set.trace_id})
