"""Evidence scoring (ADR-024 §1 "Evidence Scoring").

Every `ComponentScore` here is a pure function of one already-computed
analysis result -- no component recomputes another's inputs, and no
component's value depends on any other component's value (ADR-024 Hard
Rule 2: no duplicate scoring). The composite `EvidenceScore` is a
plain weighted sum -- `sum(component.value * component.weight)` -- with
no additional hidden transform, and is bounded [0, 100] because every
component value is bounded [0, 100] and the configured weights are
validated to sum to 1.0 (`EvidenceEngineConfig.__post_init__`).
"""

from __future__ import annotations

from typing import Sequence, Tuple

from .config import EvidenceEngineConfig
from .models import (
    CandlestickMatch,
    ComponentScore,
    EvidenceScore,
    LiquidityResult,
    MarketStructureResult,
    SessionState,
    TrendClassification,
    VolatilityState,
)

_TREND_SCORE_MAP = {
    TrendClassification.TRENDING_UP: 80.0,
    TrendClassification.TRENDING_DOWN: 80.0,
    TrendClassification.EXPANSION: 70.0,
    TrendClassification.REVERSAL: 60.0,
    TrendClassification.RANGE: 30.0,
    TrendClassification.COMPRESSION: 20.0,
}


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def score_structure(result: MarketStructureResult, config: EvidenceEngineConfig) -> ComponentScore:
    value = _clamp(
        25.0 * (1.0 if result.events else 0.0)
        + 25.0 * (1.0 if result.trend in (TrendClassification.TRENDING_UP, TrendClassification.TRENDING_DOWN) else 0.0)
        + 25.0 * min(1.0, len(result.support_levels) / 2.0)
        + 25.0 * min(1.0, len(result.resistance_levels) / 2.0)
    )
    confidence = 0.9 if result.events else 0.5
    reason = (
        f"{len(result.events)} structure event(s), trend={result.trend.value}, "
        f"{len(result.support_levels)} support / {len(result.resistance_levels)} resistance level(s)"
    )
    return ComponentScore(name="structure", value=value, weight=config.structure_weight, confidence=confidence, reason=reason)


def score_liquidity(result: LiquidityResult, config: EvidenceEngineConfig) -> ComponentScore:
    genuine_hunts = [s for s in result.sweeps if s.is_stop_hunt and not s.is_trap]
    value = _clamp(
        30.0 * min(1.0, len(result.pools) / 3.0)
        + (40.0 if genuine_hunts else (20.0 if result.sweeps else 0.0))
        + (30.0 if any(s.displacement_follow_through for s in result.sweeps) else 0.0)
    )
    confidence = 0.8 if result.sweeps else 0.4
    reason = (
        f"{len(result.pools)} liquidity pool(s), {len(result.sweeps)} sweep(s), "
        f"{len(genuine_hunts)} confirmed (non-trap) stop hunt(s)"
    )
    return ComponentScore(name="liquidity", value=value, weight=config.liquidity_weight, confidence=confidence, reason=reason)


def score_candlesticks(matches: Sequence[CandlestickMatch], config: EvidenceEngineConfig) -> ComponentScore:
    if not matches:
        return ComponentScore(
            name="candlestick", value=0.0, weight=config.candlestick_weight, confidence=0.3,
            reason="No candlestick pattern recognized in the evaluated window",
        )
    strongest = max(matches, key=lambda m: m.confidence)
    value = _clamp(strongest.confidence * 100.0)
    confidence = strongest.confidence
    reason = (
        f"Strongest pattern: {strongest.pattern.value} at index {strongest.index} "
        f"(quality={strongest.quality:.2f}, context={strongest.context.value})"
    )
    return ComponentScore(name="candlestick", value=value, weight=config.candlestick_weight, confidence=confidence, reason=reason)


def score_trend(trend: TrendClassification, config: EvidenceEngineConfig) -> ComponentScore:
    value = _TREND_SCORE_MAP[trend]
    confidence = 0.8 if trend in (TrendClassification.TRENDING_UP, TrendClassification.TRENDING_DOWN) else 0.6
    reason = f"Trend classified as {trend.value}"
    return ComponentScore(name="trend", value=value, weight=config.trend_weight, confidence=confidence, reason=reason)


def score_volatility(state: VolatilityState, config: EvidenceEngineConfig) -> ComponentScore:
    reason = f"ATR={state.atr:.5f}, expansion={state.is_expansion}, compression={state.is_compression}"
    return ComponentScore(
        name="volatility", value=_clamp(state.volatility_score), weight=config.volatility_weight, confidence=0.9, reason=reason
    )


def score_session(state: SessionState, config: EvidenceEngineConfig) -> ComponentScore:
    reason = f"Session={state.session.value}"
    return ComponentScore(
        name="session", value=_clamp(state.quality_score), weight=config.session_weight, confidence=1.0, reason=reason
    )


def score_indicators(config: EvidenceEngineConfig) -> ComponentScore:
    """No concrete indicator is implemented in Phase 2A (ADR-024 Hard
    Rule 7) -- this is an honest, documented neutral placeholder, not a
    hidden assumption of bullish/bearish evidence. Confidence is
    deliberately low to reflect that this component currently carries
    no real information."""
    return ComponentScore(
        name="indicator", value=50.0, weight=config.indicator_weight, confidence=0.1,
        reason="No concrete indicators implemented yet (ADR-024 Phase 2A scope) -- neutral placeholder",
    )


def compute_component_scores(
    structure_result: MarketStructureResult,
    liquidity_result: LiquidityResult,
    candlestick_matches: Sequence[CandlestickMatch],
    trend: TrendClassification,
    volatility_state: VolatilityState,
    session_state: SessionState,
    config: EvidenceEngineConfig,
) -> Tuple[ComponentScore, ...]:
    return (
        score_structure(structure_result, config),
        score_liquidity(liquidity_result, config),
        score_candlesticks(candlestick_matches, config),
        score_trend(trend, config),
        score_volatility(volatility_state, config),
        score_session(session_state, config),
        score_indicators(config),
    )


def compute_evidence_score(components: Sequence[ComponentScore]) -> EvidenceScore:
    composite = _clamp(sum(c.value * c.weight for c in components))
    return EvidenceScore(composite=composite, components=tuple(components))


__all__ = [
    "score_structure",
    "score_liquidity",
    "score_candlesticks",
    "score_trend",
    "score_volatility",
    "score_session",
    "score_indicators",
    "compute_component_scores",
    "compute_evidence_score",
]
