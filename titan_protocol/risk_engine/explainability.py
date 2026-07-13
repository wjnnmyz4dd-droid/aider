"""RiskSnapshot assembly (ADR-027 §3): every recommendation must include
a complete explanation."""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Tuple

from .models import (
    ConfidenceTier,
    CorrelationStatus,
    DataQuality,
    ExposureSummary,
    MonteCarloResult,
    PositionSizeRecommendation,
    RejectionReason,
    RiskSnapshot,
    StatisticalMetrics,
    VolatilityAdjustment,
)


def build_risk_snapshot(
    pair: str,
    now: datetime,
    approved: bool,
    rejection_reason: Optional[RejectionReason],
    confidence_tier: Optional[ConfidenceTier],
    volatility_adjustment: Optional[VolatilityAdjustment],
    exposure_summary: Optional[ExposureSummary],
    correlation_status: Optional[CorrelationStatus],
    statistical_metrics: Optional[StatisticalMetrics],
    monte_carlo: Optional[MonteCarloResult],
    recommended_position_size: Optional[PositionSizeRecommendation],
    reservation_id: Optional[str],
    extra_warnings: Tuple[str, ...] = (),
) -> RiskSnapshot:
    reasons = []
    warnings = list(extra_warnings)

    if not approved:
        reasons.append(f"Rejected: {rejection_reason.value}" if rejection_reason else "Rejected: unspecified")
        return RiskSnapshot(
            pair=pair, generated_at=now, approved=False, approved_risk_r=0.0,
            recommended_position_size=None, confidence_tier=confidence_tier,
            exposure_summary=exposure_summary, correlation_status=correlation_status,
            statistical_metrics=statistical_metrics, monte_carlo=monte_carlo,
            reasons=tuple(reasons), warnings=tuple(warnings),
            rejection_reason=rejection_reason, reservation_id=None,
        )

    reasons.append(f"Evidence Score qualified confidence tier {confidence_tier.label} (schedule base {confidence_tier.base_r:.2f}R).")
    if volatility_adjustment is not None:
        reasons.append(f"Volatility adjustment: {volatility_adjustment.reason} (x{volatility_adjustment.sizing_multiplier:.2f}).")
    if recommended_position_size is not None:
        reasons.append(f"Approved risk: {recommended_position_size.final_r:.2f}R.")
        if recommended_position_size.capped:
            reasons.append(f"Sizing {recommended_position_size.cap_reason}.")
    if statistical_metrics is not None and not statistical_metrics.sufficient_data:
        warnings.append(
            f"Insufficient trade history ({statistical_metrics.sample_size} samples) -- "
            "statistics unavailable, sizing capped at the fail-closed tier."
        )
    if exposure_summary is not None and exposure_summary.data_quality is DataQuality.UNKNOWN:
        warnings.append("Portfolio state unknown -- exposure/heat not fully verified.")
    if correlation_status is not None and correlation_status.data_quality is DataQuality.UNKNOWN:
        warnings.append("Correlation unknown -- no portfolio state to correlate against.")

    approved_risk_r = recommended_position_size.final_r if recommended_position_size is not None else 0.0

    return RiskSnapshot(
        pair=pair, generated_at=now, approved=True, approved_risk_r=approved_risk_r,
        recommended_position_size=recommended_position_size, confidence_tier=confidence_tier,
        exposure_summary=exposure_summary, correlation_status=correlation_status,
        statistical_metrics=statistical_metrics, monte_carlo=monte_carlo,
        reasons=tuple(reasons), warnings=tuple(warnings),
        rejection_reason=None, reservation_id=reservation_id,
    )


__all__ = ["build_risk_snapshot"]
