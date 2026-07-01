"""Market-structure detection: BOS, CHOCH, liquidity sweep, FVG, order block.

These are intentionally compact, rule-based detectors operating on swing
pivots and raw candles. Each returns a small dataclass with a boolean ``found``
and the direction it implies, so the scorer can both award points and align
direction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from . import indicators as ind
from .config import Config, DEFAULT_CONFIG
from .types import Candle, Direction


@dataclass
class StructureSignal:
    found: bool = False
    direction: Direction = Direction.NONE
    detail: str = ""


class StructureAnalyzer:
    def __init__(self, config: Config = DEFAULT_CONFIG):
        self.config = config
        self.lookback = config.indicators.swing_lookback

    # --- Break of Structure: price takes out the most recent swing in the
    #     direction of the prevailing trend. ----------------------------------
    def bos(self, candles: List[Candle]) -> StructureSignal:
        highs, lows = ind.swing_points(candles, self.lookback)
        if len(highs) < 2 and len(lows) < 2:
            return StructureSignal()
        last = candles[-1].close
        if highs:
            _, last_swing_high = highs[-1]
            if last > last_swing_high:
                return StructureSignal(True, Direction.LONG, "close above prior swing high")
        if lows:
            _, last_swing_low = lows[-1]
            if last < last_swing_low:
                return StructureSignal(True, Direction.SHORT, "close below prior swing low")
        return StructureSignal()

    # --- Change of Character: the first swing break *against* the previous
    #     sequence of higher-highs / lower-lows. ------------------------------
    def choch(self, candles: List[Candle]) -> StructureSignal:
        highs, lows = ind.swing_points(candles, self.lookback)
        if len(highs) < 2 or len(lows) < 2:
            return StructureSignal()
        # Was making higher lows (uptrend) then broke the last higher low -> bearish CHOCH.
        if lows[-1][1] > lows[-2][1] and candles[-1].close < lows[-1][1]:
            return StructureSignal(True, Direction.SHORT, "broke ascending structure")
        # Was making lower highs (downtrend) then broke the last lower high -> bullish CHOCH.
        if highs[-1][1] < highs[-2][1] and candles[-1].close > highs[-1][1]:
            return StructureSignal(True, Direction.LONG, "broke descending structure")
        return StructureSignal()

    # --- Liquidity sweep: wick beyond a prior swing that closes back inside. --
    def liquidity_sweep(self, candles: List[Candle]) -> StructureSignal:
        highs, lows = ind.swing_points(candles, self.lookback)
        c = candles[-1]
        if highs:
            _, sh = highs[-1]
            if c.high > sh and c.close < sh:
                return StructureSignal(True, Direction.SHORT, "swept buy-side liquidity")
        if lows:
            _, sl = lows[-1]
            if c.low < sl and c.close > sl:
                return StructureSignal(True, Direction.LONG, "swept sell-side liquidity")
        return StructureSignal()

    # --- Fair Value Gap: 3-bar imbalance. ------------------------------------
    def fvg(self, candles: List[Candle]) -> StructureSignal:
        if len(candles) < 3:
            return StructureSignal()
        a, _b, c = candles[-3], candles[-2], candles[-1]
        # Bullish FVG: gap between bar a high and bar c low.
        if c.low > a.high:
            return StructureSignal(True, Direction.LONG, "bullish fair value gap")
        if c.high < a.low:
            return StructureSignal(True, Direction.SHORT, "bearish fair value gap")
        return StructureSignal()

    # --- Order block: last opposing candle before an impulsive move. ---------
    def order_block(self, candles: List[Candle]) -> StructureSignal:
        if len(candles) < 4:
            return StructureSignal()
        atr = ind.atr(candles, self.config.indicators.atr_period) or 0.0
        impulse = candles[-1]
        body = abs(impulse.close - impulse.open)
        if atr and body > atr:  # impulsive bar
            prior = candles[-2]
            up = impulse.close > impulse.open
            if up and prior.close < prior.open:
                return StructureSignal(True, Direction.LONG, "bullish order block")
            if not up and prior.close > prior.open:
                return StructureSignal(True, Direction.SHORT, "bearish order block")
        return StructureSignal()
