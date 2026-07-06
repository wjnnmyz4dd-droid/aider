"""Per-timeframe trend facts (ADR-002 §5).

Each timeframe's trend is computed independently — no cross-timeframe bias
resolution here, since "bias" is a trading judgment reserved for the
Strategy Engine (ADR-002 §5).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from ..data_pipeline.models import NormalizedBar
from .config import ScannerConfig
from .models import Direction, TrendReading


@dataclass(frozen=True)
class TrendComputation:
    """`strength_history` is the same EMA-derived strength series sampled at
    every bar from warm-up onward, oldest→newest — exposed so
    `composite.py`'s trend acceleration/exhaustion classification can reuse
    it rather than recomputing EMAs a second time (ADR-002 §13)."""

    reading: TrendReading
    strength_history: Tuple[float, ...]


def _ema_series(values: Sequence[float], period: int) -> List[Optional[float]]:
    """Returns one EMA value per input bar, `None` before the series has
    enough bars to seed (simple-average seed, then standard EMA recursion)."""

    result: List[Optional[float]] = [None] * len(values)
    if len(values) < period:
        return result

    k = 2.0 / (period + 1)
    seed = sum(values[:period]) / period
    result[period - 1] = seed
    prev = seed
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        result[i] = prev
    return result


def compute_trend(bars: Sequence[NormalizedBar], config: ScannerConfig) -> TrendComputation:
    if len(bars) < config.min_bars_for_trend:
        return TrendComputation(reading=TrendReading(Direction.UNKNOWN, None), strength_history=())

    closes = [b.close for b in bars]
    fast = _ema_series(closes, config.ema_fast_period)
    slow = _ema_series(closes, config.ema_slow_period)

    strength_history = []
    for f, s in zip(fast, slow):
        if f is None or s is None or s == 0:
            continue
        strength_history.append((f - s) / s)

    if not strength_history:
        return TrendComputation(reading=TrendReading(Direction.UNKNOWN, None), strength_history=())

    strength = strength_history[-1]
    if strength > config.trend_strength_flat_threshold:
        direction = Direction.UP
    elif strength < -config.trend_strength_flat_threshold:
        direction = Direction.DOWN
    else:
        direction = Direction.NEUTRAL

    return TrendComputation(
        reading=TrendReading(direction, strength),
        strength_history=tuple(strength_history),
    )
