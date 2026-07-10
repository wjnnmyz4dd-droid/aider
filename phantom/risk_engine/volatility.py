"""ATR-adjusted / volatility-adjusted sizing multiplier (ADR-027 §3).

Reads `EvidenceSnapshot.volatility` (ATR, expansion/compression,
volatility score) and `MarketIntelligenceSnapshot`'s liquidity facts --
never recomputes either (ADR-027 Hard Rule 8).
"""

from __future__ import annotations

from phantom.evidence_engine.models import VolatilityState
from phantom.market_intelligence.models import LiquidityIntelligence

from .config import RiskEngineConfig
from .models import VolatilityAdjustment


def compute_volatility_adjustment(
    volatility: VolatilityState, liquidity: LiquidityIntelligence, config: RiskEngineConfig,
) -> VolatilityAdjustment:
    if volatility.volatility_score >= config.abnormal_volatility_score_threshold:
        multiplier = config.abnormal_volatility_sizing_multiplier
        label, reason = "ABNORMAL", "abnormal volatility"
    elif volatility.is_expansion:
        multiplier = config.expansion_sizing_multiplier
        label, reason = "EXPANSION", "volatility expansion"
    elif volatility.is_compression:
        multiplier = config.compression_sizing_multiplier
        label, reason = "COMPRESSION", "volatility compression"
    else:
        multiplier = config.normal_volatility_sizing_multiplier
        label, reason = "NORMAL", "normal volatility"

    if liquidity.liquidity_score < config.low_liquidity_score_threshold:
        multiplier *= config.low_liquidity_sizing_multiplier
        reason = f"{reason} + low liquidity"

    return VolatilityAdjustment(
        atr=volatility.atr, volatility_label=label, sizing_multiplier=multiplier,
        reason=reason,
    )


__all__ = ["compute_volatility_adjustment"]
