"""Structured logging for the Opportunity Selection Engine.

A logging failure never propagates into or alters this package's
return value -- same discipline as every other engine's logging_sink
this session.
"""

from __future__ import annotations

import logging
from datetime import datetime

from titan_protocol.strategy_engine.models import SessionName

from .models import SelectionOutcome

logger = logging.getLogger("titan_protocol.opportunity_selection_engine")


def _safe_log(level: int, message: str, extra: dict) -> None:
    try:
        logger.log(level, message, extra=extra)
    except Exception:
        pass


def log_opportunity_window_result(range_start: datetime, session_name: SessionName, outcome: SelectionOutcome) -> None:
    _safe_log(
        logging.INFO,
        "opportunity_window_result",
        {
            "range_start": range_start.isoformat(),
            "session_name": session_name.value,
            "winner": outcome.winner,
            "reason": outcome.reason,
        },
    )


__all__ = ["log_opportunity_window_result"]
