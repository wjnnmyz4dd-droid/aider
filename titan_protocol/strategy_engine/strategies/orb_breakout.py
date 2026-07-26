"""Opening Range Breakout (ORB) -- breakout qualification + persistent
per-range lockout (ADR-035 §4, §18.A item 2, Phase 2 Step 2B).

Consumes `EvidenceSnapshot.opening_ranges` (ADR-035 Phase 0) and its
`post_range_bars` evidence contract (ADR-024 Amendment 4, Step 2A) to
decide whether the most recent closed bar constitutes a genuine,
volatility-confirmed, ATR-distant, body-quality breakout beyond the
opening range, with a restart-safe, concurrency-safe lockout limiting
qualifications per `(pair, range_start)` (`OrbQualificationStore`).
Still absent from `build_default_registry()` -- production registration
remains no earlier than Phase 6 (ADR-035 §17).
"""

from __future__ import annotations

from titan_protocol.evidence_engine.models import EvidenceSnapshot, StructureDirection
from titan_protocol.market_intelligence.models import MarketIntelligenceSnapshot
from titan_protocol.strategy_state_store import OrbQualificationStore

from ..config import StrategyEngineConfig
from ..eligibility import check_eligibility
from ..models import MarketRegime, QualificationResult, QualificationStatus, StrategyDefinition, StrategyId, TradeIntent
from ._helpers import clamp, component
from .base import Strategy

_DEFINITION = StrategyDefinition(
    strategy_id=StrategyId.OPENING_RANGE_BREAKOUT,
    purpose="Trade a volatility-confirmed breakout beyond a fixed-width opening range, gated on ATR-relative distance and breakout-bar body quality (ADR-035 §4).",
    market_regime=MarketRegime.BREAKOUT,
    entry_conditions=(
        "Opening range is formed",
        "Opening range is valid",
        "Most recent closed post-range bar's close is beyond the opening range boundary",
        "Volatility is expanding",
        "Breakout distance is at least the configured ATR multiple",
        "Breakout bar's body is at least the configured body/range ratio",
        "Confirmation-candle count and direction consistency are satisfied",
    ),
    exit_conditions=(),
    invalidation_conditions=("Opening range invalidated by a data gap or insufficient bar count",),
    preferred_sessions=(),
    preferred_pairs=(),
    required_evidence_conditions=(
        "opening_ranges is non-empty", "opening_range.is_formed", "opening_range.is_valid",
        "post_range_bars is non-empty", "most recent post-range bar's close is beyond range_high or range_low",
        "volatility.is_expansion", "volatility.atr > 0",
    ),
    required_market_intelligence_conditions=(),
    expected_volatility="EXPANSION",
    required_support_resistance_context=(),
    required_candlestick_confirmation=(),
    required_liquidity_confirmation=(),
)


def _not_qualified(pair: str, reason: str) -> QualificationResult:
    return QualificationResult(
        strategy_id=StrategyId.OPENING_RANGE_BREAKOUT, pair=pair, status=QualificationStatus.NOT_QUALIFIED,
        score=0.0, confidence=0.0, reason=reason, strengths=(), weaknesses=(reason,),
    )


class OrbBreakoutStrategy(Strategy):
    def __init__(self, store: OrbQualificationStore) -> None:
        self._store = store

    @property
    def definition(self) -> StrategyDefinition:
        return _DEFINITION

    def qualify(
        self,
        pair: str,
        evidence: EvidenceSnapshot,
        market_intelligence: MarketIntelligenceSnapshot,
        config: StrategyEngineConfig,
    ) -> QualificationResult:
        ineligible = check_eligibility(StrategyId.OPENING_RANGE_BREAKOUT, pair, config)
        if ineligible is not None:
            return ineligible

        opening_ranges = evidence.opening_ranges
        if not opening_ranges:
            return _not_qualified(pair, "No opening range configured for this evaluation cycle")
        if len(opening_ranges) > 1:
            return _not_qualified(pair, "Multiple opening ranges configured, cannot disambiguate before Phase 4")

        opening_range = opening_ranges[0]
        if not opening_range.is_formed:
            return _not_qualified(pair, "Opening range not yet formed")
        if not opening_range.is_valid:
            return _not_qualified(pair, "Opening range invalidated by a data gap or insufficient bar count")

        post_range_bars = opening_range.post_range_bars
        if not post_range_bars:
            return _not_qualified(pair, "No post-range evidence available yet")

        candidate = post_range_bars[-1]
        if candidate.high <= candidate.low:
            return _not_qualified(pair, "Degenerate candle geometry")

        if candidate.close > opening_range.range_high:
            trade_intent = TradeIntent.BUY
            range_boundary = opening_range.range_high
        elif candidate.close < opening_range.range_low:
            trade_intent = TradeIntent.SELL
            range_boundary = opening_range.range_low
        else:
            return _not_qualified(pair, "No breakout: close within range")

        if not evidence.volatility.is_expansion:
            return _not_qualified(pair, "No volatility expansion")

        if evidence.volatility.atr <= 0:
            return _not_qualified(pair, "Insufficient volatility evidence (non-positive ATR)")
        if abs(candidate.close - range_boundary) < config.orb_min_breakout_distance_atr_multiple * evidence.volatility.atr:
            return _not_qualified(pair, "Breakout distance below ATR-relative threshold")

        if abs(candidate.close - candidate.open) < config.orb_min_body_to_range_ratio * (candidate.high - candidate.low):
            return _not_qualified(pair, "Body/wick ratio below threshold")

        if len(post_range_bars) < config.orb_min_confirmation_candles:
            return _not_qualified(pair, "Insufficient confirmation candles")

        confirmation_window = post_range_bars[-config.orb_min_confirmation_candles:]
        if trade_intent is TradeIntent.BUY:
            direction_consistent = all(bar.close > opening_range.range_high for bar in confirmation_window)
        else:
            direction_consistent = all(bar.close < opening_range.range_low for bar in confirmation_window)
        if not direction_consistent:
            return _not_qualified(pair, "Confirmation candles inconsistent with breakout direction")

        session_component = component(evidence.report, "session")
        session_value = session_component.value if session_component else 0.0
        mi_session_score = market_intelligence.pair_safety.session.session_score

        required_direction = StructureDirection.BULLISH if trade_intent is TradeIntent.BUY else StructureDirection.BEARISH
        zone_low = min(range_boundary, candidate.close)
        zone_high = max(range_boundary, candidate.close)

        qualifying_fvg = None
        for gap in evidence.fair_value_gaps:
            if gap.direction != required_direction:
                continue
            if gap.filled:
                continue
            if gap.start_index < opening_range.range_start_index:
                continue
            age_bars = candidate.index - gap.end_index
            if age_bars < 0 or age_bars > config.orb_fvg_max_age_bars:
                continue
            if (gap.gap_high - gap.gap_low) < config.orb_fvg_min_size_atr_multiple * evidence.volatility.atr:
                continue
            if gap.gap_high < zone_low or gap.gap_low > zone_high:
                continue
            qualifying_fvg = gap
            break

        fvg_bonus = 100.0 if qualifying_fvg is not None else 0.0
        score = clamp(0.4 * session_value + 0.3 * mi_session_score + 0.3 * evidence.volatility.volatility_score + config.orb_fvg_score_weight * fvg_bonus)
        confidence = session_component.confidence if session_component else 0.5

        boundary_name = "range_high" if trade_intent is TradeIntent.BUY else "range_low"
        strengths = [
            f"breakout beyond {boundary_name}", "volatility expanding",
            f"{len(confirmation_window)} confirmation candles",
        ]
        if qualifying_fvg is not None:
            strengths.append(
                f"unfilled {qualifying_fvg.direction.value.lower()} FVG confirmation "
                f"[{qualifying_fvg.start_index}-{qualifying_fvg.end_index}]"
            )

        qualified_result = QualificationResult(
            strategy_id=StrategyId.OPENING_RANGE_BREAKOUT, pair=pair, status=QualificationStatus.QUALIFIED,
            score=score, confidence=confidence,
            reason=f"Breakout beyond {boundary_name} with volatility expansion",
            strengths=tuple(strengths),
            weaknesses=(), trade_intent=trade_intent,
        )

        if not self._store.try_consume(pair, opening_range.range_start, config.orb_max_qualifications_per_range):
            return _not_qualified(pair, "Already qualified for this opening range")
        return qualified_result


__all__ = ["OrbBreakoutStrategy"]
