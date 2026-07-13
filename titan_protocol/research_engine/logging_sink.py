"""Structured logging for the Research & Learning Engine.

A logging failure never propagates into or alters this package's
return value -- same discipline as every other engine's logging_sink
this session.
"""

from __future__ import annotations

import logging

from .models import ResearchSnapshot

logger = logging.getLogger("titan_protocol.research_engine")


def _safe_log(level: int, message: str, extra: dict) -> None:
    try:
        logger.log(level, message, extra=extra)
    except Exception:
        pass


def log_research_snapshot(snapshot: ResearchSnapshot) -> None:
    _safe_log(
        logging.INFO,
        "research_snapshot",
        {
            "generated_at": snapshot.generated_at.isoformat(),
            "period": snapshot.period.value,
            "sample_size": snapshot.sample_size,
            "recommendation_count": len(snapshot.recommendations),
        },
    )


__all__ = ["log_research_snapshot"]
