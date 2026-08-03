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


def log_superseded_opportunity_window(range_start: datetime, session_name: SessionName, latest_seen: datetime) -> None:
    """ADR-037 §12's "stale winner" signal, corrected: fires only when a
    genuinely older `range_start` for this session is queried after a
    newer one has already been current -- never on elapsed formation
    duration alone (Amendment 1 §2)."""
    _safe_log(
        logging.WARNING,
        "superseded_opportunity_window_encountered",
        {
            "range_start": range_start.isoformat(),
            "session_name": session_name.value,
            "latest_seen_range_start": latest_seen.isoformat(),
        },
    )


__all__ = ["log_opportunity_window_result", "log_superseded_opportunity_window"]
