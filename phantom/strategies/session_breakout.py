"""Strategy 3 — Session Breakout Continuation.

Captures London/NY continuation of the Asia range. The Asia range is the
high/low of the execution-timeframe candles inside the Asia window (UTC). A
close beyond that range during the London/NY window, in the direction of the
higher-timeframe trend and regime, is a continuation signal. Signal only.

LONG : close above Asia high + BOS + H4 trend up + regime TRENDING_UP
SHORT: close below Asia low  + BOS + H4 trend down + regime TRENDING_DOWN

Scoring: Session Breakout +8, +Trend +5, +BOS +5.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..config import Config, DEFAULT_CONFIG
from ..types import Direction, MarketSnapshot, Regime
from .base import Strategy, StrategyContext, StrategySignal


@dataclass
class AsiaRange:
    symbol: str
    date: str
    high: float
    low: float
    complete: bool


class SessionBreakoutContinuation(Strategy):
    name = "Session Breakout"

    def __init__(self, config: Config = DEFAULT_CONFIG):
        self.config = config
        self._ranges = {}  # keyed by symbol:date -> AsiaRange (for introspection)
        self._lock = threading.Lock()  # FIX 9

    def asia_range(self, snap: MarketSnapshot) -> Optional[AsiaRange]:
        sp = self.config.strategies
        now = snap.now.astimezone(timezone.utc)
        day = now.date()
        start = datetime(day.year, day.month, day.day, sp.asia_start_hour, tzinfo=timezone.utc)
        end = datetime(day.year, day.month, day.day, sp.asia_end_hour, tzinfo=timezone.utc)
        candles = [c for c in snap.tf(self.config.orb.execution_tf)
                   if start <= c.ts.astimezone(timezone.utc) < end]
        if not candles:
            return None
        rng = AsiaRange(snap.symbol.upper(), day.isoformat(),
                        max(c.high for c in candles), min(c.low for c in candles),
                        complete=now >= end)
        cutoff = (day - timedelta(days=self.config.state_ttl_days)).isoformat()  # FIX 8
        with self._lock:  # FIX 9
            self._ranges[f"{snap.symbol.upper()}:{day.isoformat()}"] = rng
            self._ranges = {k: v for k, v in self._ranges.items() if v.date >= cutoff}
        return rng

    def evaluate(self, snap: MarketSnapshot, ctx: StrategyContext) -> StrategySignal:
        sp = self.config.strategies
        now = snap.now.astimezone(timezone.utc)
        rng = self.asia_range(snap)
        if rng is None or not rng.complete:
            return StrategySignal(self.name, reason="no Asia range yet")
        if now.hour >= sp.asia_trade_until_hour:
            return StrategySignal(self.name, reason="outside continuation window")

        last_close = ctx.exec_candles[-1].close if ctx.exec_candles else None
        if last_close is None:
            return StrategySignal(self.name, reason="no price")

        long_break = last_close > rng.high
        short_break = last_close < rng.low
        if not (long_break or short_break):
            return StrategySignal(self.name, reason="no Asia breakout")
        direction = Direction.LONG if long_break else Direction.SHORT

        regime_ok = (
            direction == Direction.LONG and ctx.regime == Regime.TRENDING_UP
        ) or (
            direction == Direction.SHORT and ctx.regime == Regime.TRENDING_DOWN
        )
        h4_ok = ctx.h4_dir == direction
        bos_ok = ctx.bos.found and ctx.bos.direction == direction
        if not (regime_ok and h4_ok and bos_ok):
            missing = [n for n, ok in (("regime", regime_ok), ("H4", h4_ok), ("BOS", bos_ok)) if not ok]
            return StrategySignal(self.name, direction, blocked=True,
                                  reason="unconfirmed: " + ",".join(missing))

        score = sp.session_breakout + sp.session_trend + sp.session_bos
        return StrategySignal(self.name, direction, score=score, confirmed=True,
                              reason=f"Asia {direction.value} +{sp.session_breakout:g}; "
                                     f"trend +{sp.session_trend:g}; BOS +{sp.session_bos:g}")
