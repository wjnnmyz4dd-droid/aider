"""Structured logging for the Prop Firm Compliance Engine.

A logging failure never propagates into or alters this package's
return value -- same discipline as every other engine's logging_sink
this session.
"""

from __future__ import annotations

import logging

from .models import ComplianceSnapshot

logger = logging.getLogger("titan_protocol.compliance_engine")


def _safe_log(level: int, message: str, extra: dict) -> None:
    try:
        logger.log(level, message, extra=extra)
    except Exception:
        pass


def log_compliance_snapshot(snapshot: ComplianceSnapshot) -> None:
    _safe_log(
        logging.INFO,
        "compliance_snapshot",
        {
            "pair": snapshot.pair,
            "generated_at": snapshot.generated_at.isoformat(),
            "decision": snapshot.decision.value,
            "approved_size_r": snapshot.approved_size_r,
            "original_size_r": snapshot.original_size_r,
            "triggered_rules": [r.value for r in snapshot.triggered_rules],
        },
    )


__all__ = ["log_compliance_snapshot"]
