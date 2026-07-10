"""Structured logging for the Portfolio Statistical Risk Engine.

A logging failure never propagates into or alters this package's
return value -- same discipline as every other engine's logging_sink
this session.
"""

from __future__ import annotations

import logging

from .models import RiskSnapshot

logger = logging.getLogger("phantom.risk_engine")


def _safe_log(level: int, message: str, extra: dict) -> None:
    try:
        logger.log(level, message, extra=extra)
    except Exception:
        pass


def log_risk_snapshot(snapshot: RiskSnapshot) -> None:
    _safe_log(
        logging.INFO,
        "risk_snapshot",
        {
            "pair": snapshot.pair,
            "generated_at": snapshot.generated_at.isoformat(),
            "approved": snapshot.approved,
            "approved_risk_r": snapshot.approved_risk_r,
            "rejection_reason": snapshot.rejection_reason.value if snapshot.rejection_reason else None,
        },
    )


__all__ = ["log_risk_snapshot"]
