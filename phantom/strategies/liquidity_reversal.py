"""Strategy 2 — Liquidity Sweep Reversal.

Captures stop-hunt reversals: price sweeps liquidity beyond a swing, prints a
rejection wick, and confirms with a change of character (CHOCH). Signal only.

LONG : sweep below swing low + rejection wick + bullish CHOCH
SHORT: sweep above swing high + rejection wick + bearish CHOCH
Blocked when regime == HIGH_VOLATILITY or news is unsafe.

Scoring: Sweep+CHOCH +10, Sweep+OB +5, Sweep+FVG +5.
"""

from __future__ import annotations

from ..config import Config, DEFAULT_CONFIG
from ..types import Candle, Direction, MarketSnapshot, Regime
from .base import Strategy, StrategyContext, StrategySignal


def _rejection_wick(candle: Candle, direction: Direction, min_ratio: float) -> bool:
    rng = candle.high - candle.low
    if rng <= 0:
        return False
    body_hi = max(candle.open, candle.close)
    body_lo = min(candle.open, candle.close)
    if direction == Direction.LONG:      # long lower wick = rejection of lows
        return (body_lo - candle.low) / rng >= min_ratio
    if direction == Direction.SHORT:     # long upper wick = rejection of highs
        return (candle.high - body_hi) / rng >= min_ratio
    return False


class LiquiditySweepReversal(Strategy):
    name = "Liquidity Reversal"

    def __init__(self, config: Config = DEFAULT_CONFIG):
        self.config = config

    def evaluate(self, snap: MarketSnapshot, ctx: StrategyContext) -> StrategySignal:
        sp = self.config.strategies
        if ctx.regime == Regime.HIGH_VOLATILITY:
            return StrategySignal(self.name, blocked=True, reason="blocked: HIGH_VOLATILITY")
        if not ctx.news_safe:
            return StrategySignal(self.name, blocked=True, reason="blocked: news")

        sweep = ctx.sweep
        choch = ctx.choch
        if not (sweep.found and sweep.direction != Direction.NONE):
            return StrategySignal(self.name, reason="no liquidity sweep")

        direction = sweep.direction  # sweep of sell-side -> LONG, buy-side -> SHORT
        if not ctx.exec_candles or not _rejection_wick(ctx.exec_candles[-1], direction, sp.rejection_wick_ratio):
            return StrategySignal(self.name, reason="sweep without rejection wick")
        if not (choch.found and choch.direction == direction):
            return StrategySignal(self.name, reason="sweep without confirming CHOCH")

        score = sp.sweep_choch
        bits = ["Sweep+CHOCH +%g" % sp.sweep_choch]
        if ctx.ob.found and ctx.ob.direction == direction:
            score += sp.sweep_ob
            bits.append("OB +%g" % sp.sweep_ob)
        if ctx.fvg.found and ctx.fvg.direction == direction:
            score += sp.sweep_fvg
            bits.append("FVG +%g" % sp.sweep_fvg)
        return StrategySignal(self.name, direction, score=score, confirmed=True,
                              reason="; ".join(bits))
