"""Structured logging for the Strategy Engine.

A logging failure never propagates into or alters this package's
return value -- same discipline as every other engine's logging_sink
this session.
"""

from __future__ import annotations

import logging

from .models import StrategySnapshot

logger = logging.getLogger("titan_protocol.strategy_engine")


def _safe_log(level: int, message: str, extra: dict) -> None:
    try:
        logger.log(level, message, extra=extra)
    except Exception:
        pass


def log_strategy_snapshot(snapshot: StrategySnapshot) -> None:
    _safe_log(
        logging.INFO,
        "strategy_snapshot",
        {
            "pair": snapshot.pair,
            "generated_at": snapshot.generated_at.isoformat(),
            "rejected": snapshot.rejected,
            "winning_strategy": snapshot.winning_strategy.strategy_id.value if snapshot.winning_strategy else None,
            "qualified_count": sum(1 for q in snapshot.all_qualifications if q.status.value == "QUALIFIED"),
        },
    )


__all__ = ["log_strategy_snapshot"]
