"""Pure-Python technical indicators (no numpy dependency).

All functions take a list of :class:`~phantom.types.Candle` ordered
oldest→newest and return either a single latest value or a list aligned to the
input. Functions return ``None`` when there is insufficient data.
"""

from __future__ import annotations

from typing import List, Optional

from .types import Candle


def _closes(candles: List[Candle]) -> List[float]:
    return [c.close for c in candles]


def sma(values: List[float], period: int) -> Optional[float]:
    if len(values) < period or period <= 0:
        return None
    return sum(values[-period:]) / period


def ema_series(values: List[float], period: int) -> List[float]:
    if not values or period <= 0:
        return []
    k = 2.0 / (period + 1.0)
    out: List[float] = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1.0 - k))
    return out


def ema(values: List[float], period: int) -> Optional[float]:
    series = ema_series(values, period)
    return series[-1] if series else None


def true_ranges(candles: List[Candle]) -> List[float]:
    trs: List[float] = []
    prev_close: Optional[float] = None
    for c in candles:
        if prev_close is None:
            trs.append(c.high - c.low)
        else:
            trs.append(
                max(
                    c.high - c.low,
                    abs(c.high - prev_close),
                    abs(c.low - prev_close),
                )
            )
        prev_close = c.close
    return trs


def atr(candles: List[Candle], period: int = 14) -> Optional[float]:
    """Wilder-style ATR (simple average of the last ``period`` true ranges)."""
    if len(candles) < period + 1:
        return None
    trs = true_ranges(candles)
    return sum(trs[-period:]) / period


def rsi(candles: List[Candle], period: int = 14) -> Optional[float]:
    closes = _closes(candles)
    if len(closes) < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(-period, 0):
        delta = closes[i] - closes[i - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def slope(values: List[float], lookback: int) -> Optional[float]:
    """Normalised slope of the last ``lookback`` values (per-bar % change)."""
    if len(values) < lookback + 1 or lookback <= 0:
        return None
    start = values[-lookback - 1]
    end = values[-1]
    if start == 0:
        return None
    return (end - start) / abs(start) / lookback


def swing_points(candles: List[Candle], lookback: int = 2):
    """Return (highs, lows) as lists of (index, price) fractal pivots.

    A swing high is a bar whose high exceeds the ``lookback`` bars on each side;
    a swing low is the mirror image.
    """
    highs = []
    lows = []
    n = len(candles)
    for i in range(lookback, n - lookback):
        window = candles[i - lookback : i + lookback + 1]
        pivot = candles[i]
        if pivot.high == max(c.high for c in window) and all(
            pivot.high >= w.high for w in window
        ) and pivot.high > max(window[j].high for j in range(len(window)) if j != lookback):
            highs.append((i, pivot.high))
        if pivot.low == min(c.low for c in window) and all(
            pivot.low <= w.low for w in window
        ) and pivot.low < min(window[j].low for j in range(len(window)) if j != lookback):
            lows.append((i, pivot.low))
    return highs, lows
