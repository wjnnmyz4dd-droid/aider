"""Structured logging for Market Data Ingestion. A logging failure
never propagates into or alters this package's return value (same
discipline as every other engine's logging_sink this session)."""

from __future__ import annotations

import logging

from .models import IngestionResult, RawBar

logger = logging.getLogger("titan_protocol.market_data_ingestion")


def _safe_log(level: int, message: str, extra: dict) -> None:
    try:
        logger.log(level, message, extra=extra)
    except Exception:
        pass


def log_ingestion_result(raw: RawBar, result: IngestionResult) -> None:
    level = logging.INFO if result.accepted else logging.WARNING
    _safe_log(
        level, "bar_ingestion_result",
        {
            "symbol": raw.symbol, "timeframe": raw.timeframe.value, "accepted": result.accepted,
            "rejection_reason": result.rejection_reason.value if result.rejection_reason else None,
            "gap_detected": result.gap_detected,
        },
    )


__all__ = ["log_ingestion_result"]
