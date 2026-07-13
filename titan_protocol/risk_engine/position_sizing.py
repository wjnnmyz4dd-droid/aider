"""Position sizing: fixed fractional, confidence scaling, volatility
scaling, fractional-capped Kelly, min/max clamp, lot normalization
(ADR-027 §3, Hard Rule 4).

`final_r` is always the **smallest** of every method that produced a
value -- no sizing method here is ever allowed to push the
recommendation above what the confidence-tier schedule and every
configured limit would otherwise allow (ADR-027 §1: capital
preservation is the tiebreaker).
"""

from __future__ import annotations

from typing import Optional

from .config import RiskEngineConfig
from .models import ConfidenceTier, PositionSizeRecommendation, StatisticalMetrics, VolatilityAdjustment


def compute_position_size(
    confidence_tier: ConfidenceTier,
    volatility_adjustment: VolatilityAdjustment,
    statistical_metrics: StatisticalMetrics,
    config: RiskEngineConfig,
) -> PositionSizeRecommendation:
    # Fail-closed (ADR-027 §0a): insufficient trade history caps sizing at
    # the lowest confidence tier regardless of the Evidence Score's own band.
    effective_base_r = (
        confidence_tier.base_r if statistical_metrics.sufficient_data
        else min(confidence_tier.base_r, config.fail_closed_tier.base_r)
    )

    fixed_fractional_r = config.fail_closed_tier.base_r
    confidence_scaled_r = effective_base_r
    volatility_scaled_r = confidence_scaled_r * volatility_adjustment.sizing_multiplier

    kelly_r: Optional[float] = None
    if statistical_metrics.sufficient_data and statistical_metrics.kelly_fraction is not None:
        fractional_kelly = max(0.0, statistical_metrics.kelly_fraction) * config.kelly_fraction_cap
        kelly_r = min(fractional_kelly, config.kelly_max_r)

    candidates = [volatility_scaled_r]
    if kelly_r is not None:
        candidates.append(kelly_r)
    final_r = min(candidates)

    capped = False
    cap_reason: Optional[str] = None
    if final_r > config.max_position_r:
        final_r = config.max_position_r
        capped, cap_reason = True, f"clamped to max_position_r={config.max_position_r:.2f}"
    elif 0.0 < final_r < config.min_position_r:
        final_r = config.min_position_r
        capped, cap_reason = True, f"raised to min_position_r={config.min_position_r:.2f}"

    lot_size = round(final_r * config.r_to_lot_multiplier / config.lot_step) * config.lot_step

    return PositionSizeRecommendation(
        fixed_fractional_r=fixed_fractional_r,
        confidence_scaled_r=confidence_scaled_r,
        volatility_scaled_r=volatility_scaled_r,
        kelly_r=kelly_r,
        final_r=final_r,
        lot_size=lot_size,
        capped=capped,
        cap_reason=cap_reason,
    )


__all__ = ["compute_position_size"]
