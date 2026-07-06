"""Volatility facts (ADR-002 §5).

`atr()` is computed once per scan and its result is reused by both the
volatility classification below and `swing.py`'s major/minor swing
classification (ADR-002 §13) — never recomputed a second time for the same
purpose.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from ..data_pipeline.models import NormalizedBar
from .config import ScannerConfig
from .models import VolatilityLabel, VolatilityState


@dataclass(frozen=True)
class VolatilityComputation:
    """`atr_current` is exposed so `swing.py`'s major/minor classification
    and `structure.py`'s order-block detection can reuse the same ATR
    reading this module already computed — never a second `atr()` call
    for the same current-period value (ADR-002 §13)."""

    state: VolatilityState
    atr_current: Optional[float]


def atr(bars: Sequence[NormalizedBar], period: int) -> Optional[float]:
    """Wilder-style true range, simple average over `period` bars (an idea
    from `phantom/indicators.py`, not authoritative — the exact formula is
    an implementation default, not architecture). Returns `None` when there
    are fewer than `period + 1` bars (not enough true-range samples)."""

    if len(bars) < period + 1:
        return None

    true_ranges = []
    for i in range(1, len(bars)):
        bar = bars[i]
        prev_close = bars[i - 1].close
        true_range = max(
            bar.high - bar.low,
            abs(bar.high - prev_close),
            abs(bar.low - prev_close),
        )
        true_ranges.append(true_range)

    recent = true_ranges[-period:]
    return sum(recent) / len(recent)


def compute_volatility(
    bars: Sequence[NormalizedBar], config: ScannerConfig
) -> VolatilityComputation:
    """Classifies current-vs-baseline ATR ratio. `None` ratio (insufficient
    bars for either ATR window) fails closed to `UNKNOWN` — never a guessed
    label."""

    current = atr(bars, config.atr_period)
    baseline = atr(bars, config.atr_baseline_period)

    if current is None or baseline is None or baseline <= 0:
        return VolatilityComputation(
            state=VolatilityState(label=VolatilityLabel.UNKNOWN, ratio=None),
            atr_current=current,
        )

    ratio = current / baseline

    if ratio >= config.volatility_extreme_ratio:
        label = VolatilityLabel.EXTREME
    elif ratio >= config.volatility_elevated_ratio:
        label = VolatilityLabel.ELEVATED
    elif ratio <= config.volatility_compressed_ratio:
        label = VolatilityLabel.COMPRESSED
    else:
        label = VolatilityLabel.NORMAL

    return VolatilityComputation(state=VolatilityState(label=label, ratio=ratio), atr_current=current)
