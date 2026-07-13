"""Volatility analysis: ATR, expansion/compression, volatility score
(ADR-024 §1 "Volatility Analysis").
"""

from __future__ import annotations

from typing import List, Sequence

from .config import EvidenceEngineConfig
from .models import Bar, VolatilityState


def true_ranges(bars: Sequence[Bar]) -> List[float]:
    """True range per bar: the first bar uses its own high-low (no
    prior close to gap against); every later bar is
    `max(high-low, |high-prev_close|, |low-prev_close|)`."""
    ranges: List[float] = []
    prev_close = None
    for bar in bars:
        if prev_close is None:
            ranges.append(bar.high - bar.low)
        else:
            ranges.append(max(bar.high - bar.low, abs(bar.high - prev_close), abs(bar.low - prev_close)))
        prev_close = bar.close
    return ranges


def atr_series(bars: Sequence[Bar], period: int) -> List[float]:
    """Simple moving average of true range over `period` bars -- a
    plain, deterministic ATR, not Wilder's smoothed variant, so every
    value is reproducible from the raw bars alone with no seeded state."""
    ranges = true_ranges(bars)
    result: List[float] = []
    for i in range(len(ranges)):
        window = ranges[max(0, i - period + 1) : i + 1]
        result.append(sum(window) / len(window))
    return result


def atr(bars: Sequence[Bar], period: int) -> float:
    """Current (most recent bar's) ATR value. Returns 0.0 for an empty
    series -- there is no volatility to measure with zero bars."""
    if not bars:
        return 0.0
    return atr_series(bars, period)[-1]


def analyze_volatility(bars: Sequence[Bar], config: EvidenceEngineConfig) -> VolatilityState:
    if not bars:
        return VolatilityState(atr=0.0, is_expansion=False, is_compression=False, volatility_score=0.0)

    series = atr_series(bars, config.atr_period)
    current_atr = series[-1]
    average_atr = sum(series) / len(series)

    if average_atr == 0:
        ratio = 1.0
    else:
        ratio = current_atr / average_atr

    is_expansion = ratio >= config.volatility_expansion_ratio
    is_compression = ratio <= config.volatility_compression_ratio

    # Score: 50 is "typical" (ratio == 1.0); scales linearly with the
    # ratio, clamped to [0, 100]. Deterministic, no hidden curve fitting.
    score = max(0.0, min(100.0, 50.0 * ratio))

    return VolatilityState(
        atr=current_atr,
        is_expansion=is_expansion,
        is_compression=is_compression,
        volatility_score=score,
    )


__all__ = ["true_ranges", "atr_series", "atr", "analyze_volatility"]
