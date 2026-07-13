"""Market safety (ADR-025 §1 "Market Safety").

Holiday/early-close/broker-maintenance/halt/closure facts are supplied
externally (`MarketSafetyInputs`) -- this module never invents or
fetches them; it only classifies "is `now` inside one of these windows"
and scores the result.
"""

from __future__ import annotations

from datetime import datetime

from .config import MarketIntelligenceConfig
from .models import MarketSafetyInputs, MarketSafetyStatus

_FRIDAY = 4
_SATURDAY = 5
_SUNDAY = 6


def _is_weekend_approaching(now: datetime, config: MarketIntelligenceConfig) -> bool:
    if now.weekday() in (_SATURDAY, _SUNDAY):
        return True
    if now.weekday() == _FRIDAY and now.hour >= (24 - config.weekend_approach_hours):
        return True
    return False


def _is_early_close(now: datetime, inputs: MarketSafetyInputs) -> bool:
    for close_date, close_time in inputs.early_closes:
        if now.date() == close_date and now.time() >= close_time:
            return True
    return False


def evaluate_market_safety(
    now: datetime, inputs: MarketSafetyInputs, config: MarketIntelligenceConfig
) -> MarketSafetyStatus:
    is_holiday = now.date() in inputs.holidays
    is_early_close = _is_early_close(now, inputs)
    is_weekend_approaching = _is_weekend_approaching(now, config)

    score = 100.0
    reasons = []
    if inputs.market_closed:
        score -= config.market_closed_penalty
        reasons.append("market closed")
    if inputs.trading_halted:
        score -= config.trading_halted_penalty
        reasons.append("trading halted")
    if inputs.broker_maintenance_active:
        score -= config.broker_maintenance_penalty
        reasons.append("broker maintenance active")
    if is_holiday:
        score -= config.holiday_penalty
        reasons.append("holiday")
    if is_early_close:
        score -= config.early_close_penalty
        reasons.append("early market close")
    if is_weekend_approaching:
        score -= config.weekend_approaching_penalty
        reasons.append("weekend approaching")

    reason = "; ".join(reasons) if reasons else "no market safety concerns"

    return MarketSafetyStatus(
        is_holiday=is_holiday,
        is_early_close=is_early_close,
        is_weekend_approaching=is_weekend_approaching,
        broker_maintenance=inputs.broker_maintenance_active,
        trading_halted=inputs.trading_halted,
        market_closed=inputs.market_closed,
        safety_score=max(0.0, min(100.0, score)),
        reason=reason,
    )


__all__ = ["evaluate_market_safety"]
