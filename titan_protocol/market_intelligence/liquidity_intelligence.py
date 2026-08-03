"""Liquidity quality (ADR-025 §1 "Liquidity Quality").

Spread is the one liquidity signal this phase can compute without a
speculative new data source: a widening spread is itself the market's
real-time signal of deteriorating liquidity/activity, so "liquidity
availability" and "market activity" are satisfied through this same
proxy rather than inventing volume/order-book fields with no real
source behind them yet (honest, documented scope, same posture as
Evidence Engine's placeholder indicator score).
"""

from __future__ import annotations

from .config import MarketIntelligenceConfig
from .models import LiquidityIntelligence


def evaluate_liquidity(current_spread: float, average_spread: float, config: MarketIntelligenceConfig) -> LiquidityIntelligence:
    if average_spread <= 0:
        ratio = 1.0 if current_spread <= 0 else float("inf")
    else:
        ratio = current_spread / average_spread

    widening = ratio > config.spread_widening_ratio

    if ratio <= 1.0:
        score = 100.0
    elif ratio >= config.spread_score_floor_ratio:
        score = 0.0
    else:
        span = config.spread_score_floor_ratio - 1.0
        score = 100.0 * (1.0 - (ratio - 1.0) / span)

    reason = f"current/average spread ratio={ratio:.2f} ({'widening' if widening else 'normal'})"

    return LiquidityIntelligence(
        current_spread=current_spread,
        average_spread=average_spread,
        spread_widening=widening,
        liquidity_score=max(0.0, min(100.0, score)),
        reason=reason,
    )


__all__ = ["evaluate_liquidity"]
