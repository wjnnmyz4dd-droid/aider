"""Structured logging for the Market Intelligence Engine.

A logging failure never propagates into or alters this package's
return value -- same discipline as `phantom/bridge/logging_sink.py` and
`phantom/evidence_engine/logging_sink.py`.
"""

from __future__ import annotations

import logging

from .models import MarketIntelligenceSnapshot

logger = logging.getLogger("phantom.market_intelligence")


def _safe_log(level: int, message: str, extra: dict) -> None:
    try:
        logger.log(level, message, extra=extra)
    except Exception:
        pass


def log_market_intelligence_snapshot(snapshot: MarketIntelligenceSnapshot) -> None:
    _safe_log(
        logging.INFO,
        "market_intelligence_snapshot",
        {
            "pair": snapshot.pair,
            "generated_at": snapshot.generated_at.isoformat(),
            "pair_safety_score": snapshot.pair_safety.pair_safety_score,
            "trade_readiness_score": snapshot.trade_readiness.readiness_score,
            "blackout_active": snapshot.pair_safety.news.blackout_active,
            "peg_policy_active": snapshot.pair_safety.peg_policy.active,
        },
    )


__all__ = ["log_market_intelligence_snapshot"]
