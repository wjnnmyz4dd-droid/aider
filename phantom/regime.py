"""Regime engine — classifies the current market regime per symbol.

Output is one of the :class:`~phantom.types.Regime` values plus a volatility
state. The classification is deliberately simple and deterministic: EMA
structure gives trend, ATR-vs-baseline gives volatility, and the combination
gives RANGING / BREAKOUT / HIGH_VOLATILITY.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import indicators as ind
from .config import Config, DEFAULT_CONFIG
from .types import MarketSnapshot, Regime


@dataclass
class RegimeReading:
    regime: Regime
    volatility_ratio: float  # current ATR / baseline ATR
    trend_strength: float    # normalised EMA separation


class RegimeEngine:
    def __init__(self, config: Config = DEFAULT_CONFIG):
        self.config = config

    def classify(self, snap: MarketSnapshot, timeframe: str = "H1") -> RegimeReading:
        candles = snap.tf(timeframe)
        ip = self.config.indicators
        if len(candles) < ip.atr_baseline_period + 1:
            # FIX 7 — warmup is its own state, not a tradeable NEUTRAL regime.
            return RegimeReading(Regime.INSUFFICIENT_DATA, 1.0, 0.0)

        closes = [c.close for c in candles]
        ema_fast = ind.ema(closes, 20) or closes[-1]
        ema_slow = ind.ema(closes, 50) or closes[-1]
        price = closes[-1]

        atr_now = ind.atr(candles, ip.atr_period) or 0.0
        atr_base = ind.atr(candles, ip.atr_baseline_period) or atr_now or 1e-9
        vol_ratio = atr_now / atr_base if atr_base else 1.0

        trend_strength = (ema_fast - ema_slow) / price if price else 0.0

        # Volatility blow-off dominates everything.
        if vol_ratio >= 2.0:
            return RegimeReading(Regime.HIGH_VOLATILITY, vol_ratio, trend_strength)

        # Breakout: strong expansion with price pushing beyond the recent range.
        recent_high = max(c.high for c in candles[-20:])
        recent_low = min(c.low for c in candles[-20:])
        if vol_ratio >= 1.4 and (price >= recent_high * 0.999 or price <= recent_low * 1.001):
            return RegimeReading(Regime.BREAKOUT, vol_ratio, trend_strength)

        # Clear directional trend.
        if ema_fast > ema_slow and trend_strength > 0.0005:
            return RegimeReading(Regime.TRENDING_UP, vol_ratio, trend_strength)
        if ema_fast < ema_slow and trend_strength < -0.0005:
            return RegimeReading(Regime.TRENDING_DOWN, vol_ratio, trend_strength)

        # Otherwise the market is going sideways.
        return RegimeReading(Regime.RANGING, vol_ratio, trend_strength)
