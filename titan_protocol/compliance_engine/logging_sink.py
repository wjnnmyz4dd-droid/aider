"""Structured logging for the Prop Firm Compliance Engine.

A logging failure never propagates into or alters this package's
return value -- same discipline as every other engine's logging_sink
this session.
"""

from __future__ import annotations

import logging
from typing import Optional

from .models import ComplianceRuleId, ComplianceSnapshot

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
            "reason": snapshot.reason,
            "approved_size_r": snapshot.approved_size_r,
            "original_size_r": snapshot.original_size_r,
            "triggered_rules": [r.value for r in snapshot.triggered_rules],
        },
    )


def log_position_limit_check(
    pair: str, positions_for_pair: int, max_positions_per_pair: int, violation: Optional[ComplianceRuleId],
) -> None:
    """Fires every cycle `check_position_limits()` runs, regardless of
    outcome -- the one place `positions_for_pair` vs the configured
    `max_positions_per_pair` is directly visible, independent of whatever
    else the overall compliance decision ends up being."""
    _safe_log(
        logging.INFO,
        "position_limit_check",
        {
            "pair": pair,
            "positions_for_pair": positions_for_pair,
            "max_positions_per_pair": max_positions_per_pair,
            "rejected": violation is not None,
            "violation": violation.value if violation is not None else None,
        },
    )


__all__ = ["log_compliance_snapshot", "log_position_limit_check"]
