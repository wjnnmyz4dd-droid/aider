"""ATR and realized-volatility-adjusted risk recommendations (`ADR-022`
§1, capability 14).

No stage in `phantom_pipeline` computes ATR as a standalone value today
(`scanner.models.VolatilityState.ratio` is a compression ratio, not True
Range) — this is a genuinely new computation, read from
`data_pipeline.models.NormalizedBar` OHLC history only (`ADR-022` Hard
Rule 7).
"""

from __future__ import annotations

from typing import List, Optional, Sequence

from ..data_pipeline.models import NormalizedBar
from ..scanner.models import VolatilityLabel
from .config import DEFAULT_CONFIG, StatisticalRiskConfig
from .models import RiskRecommendation, VolatilityState


def true_ranges(bars: Sequence[NormalizedBar]) -> List[float]:
    trs: List[float] = []
    prev_close: Optional[float] = None
    for bar in bars:
        if prev_close is None:
            tr = bar.high - bar.low
        else:
            tr = max(bar.high - bar.low, abs(bar.high - prev_close), abs(bar.low - prev_close))
        trs.append(tr)
        prev_close = bar.close
    return trs


def wilders_atr(bars: Sequence[NormalizedBar], period: int) -> Optional[float]:
    """Wilder's smoothed Average True Range — `None` when fewer than
    `period` bars are available (Hard Rule 7)."""
    trs = true_ranges(bars)
    if len(trs) < period or period <= 0:
        return None
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def realized_volatility(bars: Sequence[NormalizedBar]) -> Optional[float]:
    """Sample standard deviation of simple close-to-close returns —
    `None` when fewer than 3 bars (need at least 2 returns) are
    available."""
    closes = [b.close for b in bars]
    returns = [
        (closes[i] - closes[i - 1]) / closes[i - 1]
        for i in range(1, len(closes))
        if closes[i - 1] != 0
    ]
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return variance**0.5


def classify_label(ratio_to_average: Optional[float], config: StatisticalRiskConfig) -> VolatilityLabel:
    if ratio_to_average is None:
        return VolatilityLabel.UNKNOWN
    if ratio_to_average >= config.volatility_extreme_ratio:
        return VolatilityLabel.EXTREME
    if ratio_to_average >= config.volatility_elevated_ratio:
        return VolatilityLabel.ELEVATED
    if ratio_to_average <= config.volatility_compressed_ratio:
        return VolatilityLabel.COMPRESSED
    return VolatilityLabel.NORMAL


def build_volatility_state(
    bars: Sequence[NormalizedBar], config: StatisticalRiskConfig = DEFAULT_CONFIG
) -> VolatilityState:
    current_atr = wilders_atr(bars, config.atr_period)

    baseline_bars = (
        bars[-config.volatility_lookback_bars :]
        if len(bars) >= config.volatility_lookback_bars
        else bars
    )
    baseline_trs = true_ranges(baseline_bars)
    baseline_atr = (sum(baseline_trs) / len(baseline_trs)) if baseline_trs else None

    ratio = (
        current_atr / baseline_atr
        if current_atr is not None and baseline_atr is not None and baseline_atr > 0
        else None
    )

    return VolatilityState(
        label=classify_label(ratio, config),
        atr=current_atr,
        realized_volatility=realized_volatility(baseline_bars),
        ratio_to_average=ratio,
    )


def recommendation_for_volatility(state: VolatilityState) -> RiskRecommendation:
    if state.label == VolatilityLabel.EXTREME:
        return RiskRecommendation.SKIP_HIGH_RISK
    if state.label == VolatilityLabel.ELEVATED:
        return RiskRecommendation.REDUCE_RISK_50
    if state.label == VolatilityLabel.UNKNOWN:
        return RiskRecommendation.REDUCE_RISK_25
    return RiskRecommendation.NORMAL_RISK


__all__ = [
    "true_ranges",
    "wilders_atr",
    "realized_volatility",
    "classify_label",
    "build_volatility_state",
    "recommendation_for_volatility",
]
