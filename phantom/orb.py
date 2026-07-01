"""Opening Range Breakout — confirmation layer.

This module DOES NOT create trades. It tracks the opening range for the London
and New York sessions, detects breakouts and false breakouts, and returns an
:class:`ORBDecision` whose ``score_impact`` is fed into the existing scorer.
The scorer adds that impact to the composite score; the scanner alone decides
whether anything is actionable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from . import indicators as ind
from .config import Config, DEFAULT_CONFIG
from .types import Candle, Direction, MarketSnapshot, Regime


@dataclass
class ORBContext:
    """Facts the scorer has already computed, handed to the ORB layer so it
    does not recompute them."""

    regime: Regime
    h4d1_aligned: Dict[Direction, bool]  # H4 AND D1 both aligned with this direction
    bos: Dict[Direction, bool]
    news_safe: bool
    spread_safe: bool
    exposure_safe: Dict[Direction, bool]
    correlation_safe: bool
    atr: float


@dataclass
class ORBRange:
    symbol: str
    session: str
    date: str           # local session date, ISO
    high: float
    low: float
    start: datetime     # UTC
    end: datetime       # UTC, exclusive
    complete: bool

    @property
    def size(self) -> float:
        return self.high - self.low


@dataclass
class ORBDecision:
    symbol: str
    session: str
    orb_high: Optional[float]
    orb_low: Optional[float]
    breakout_direction: Direction
    false_breakout: bool
    confirmed: bool
    blocked: bool
    score_impact: float
    reason: str
    ts: datetime

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "session": self.session,
            "orb_high": self.orb_high,
            "orb_low": self.orb_low,
            "breakout_direction": self.breakout_direction.value,
            "false_breakout": self.false_breakout,
            "confirmed": self.confirmed,
            "blocked": self.blocked,
            "score_impact": round(self.score_impact, 2),
            "reason": self.reason,
            "ts": self.ts.isoformat(),
        }


_SESSION_TZ = "tz"
_SESSION_OPEN = "open"


class ORBEngine:
    def __init__(self, config: Config = DEFAULT_CONFIG):
        self.config = config
        o = config.orb
        self._sessions = {
            "LONDON": {_SESSION_TZ: o.london_tz, _SESSION_OPEN: o.london_open},
            "NEWYORK": {_SESSION_TZ: o.newyork_tz, _SESSION_OPEN: o.newyork_open},
        }
        self._ranges: Dict[str, ORBRange] = {}
        self._last_decision: Dict[str, ORBDecision] = {}

    # ---- session clock ----------------------------------------------------
    def _window(self, session: str, now: datetime):
        cfg = self._sessions[session]
        tz = ZoneInfo(cfg[_SESSION_TZ])
        open_t: time = cfg[_SESSION_OPEN]
        local = now.astimezone(tz)
        start_local = datetime.combine(local.date(), open_t, tzinfo=tz)
        start = start_local.astimezone(now.tzinfo)
        end = (start_local + timedelta(minutes=self.config.orb.range_minutes)).astimezone(now.tzinfo)
        trade_end = (start_local + timedelta(minutes=self.config.orb.trade_window_minutes)).astimezone(now.tzinfo)
        return start, end, trade_end, local.date().isoformat()

    def active_sessions(self, now: datetime) -> List[str]:
        active = []
        for name in self._sessions:
            start, _end, trade_end, _date = self._window(name, now)
            if start <= now <= trade_end:
                active.append(name)
        return active

    def _key(self, symbol: str, session: str, date: str) -> str:
        return f"{symbol.upper()}:{session}:{date}"

    # ---- range construction ----------------------------------------------
    def update_ranges(self, snap: MarketSnapshot) -> None:
        tf = self.config.orb.execution_tf
        candles = snap.tf(tf)
        if not candles:
            return
        for session in self._sessions:
            start, end, trade_end, date = self._window(session, snap.now)
            if snap.now < start or snap.now > trade_end:
                continue
            window = [c for c in candles if start <= c.ts < end]
            key = self._key(snap.symbol, session, date)
            if window:
                hi = max(c.high for c in window)
                lo = min(c.low for c in window)
                self._ranges[key] = ORBRange(
                    symbol=snap.symbol.upper(),
                    session=session,
                    date=date,
                    high=hi,
                    low=lo,
                    start=start,
                    end=end,
                    complete=snap.now >= end,
                )

    def _current_range(self, snap: MarketSnapshot) -> Optional[ORBRange]:
        """The most recently opened completed range still inside its trade window."""
        candidate: Optional[ORBRange] = None
        for session in self._sessions:
            start, end, trade_end, date = self._window(session, snap.now)
            key = self._key(snap.symbol, session, date)
            rng = self._ranges.get(key)
            if rng and rng.complete and end <= snap.now <= trade_end:
                if candidate is None or rng.start > candidate.start:
                    candidate = rng
        return candidate

    # ---- evaluation -------------------------------------------------------
    def evaluate(self, snap: MarketSnapshot, ctx: ORBContext) -> ORBDecision:
        self.update_ranges(snap)
        rng = self._current_range(snap)
        now = snap.now

        if rng is None:
            dec = ORBDecision(
                symbol=snap.symbol.upper(), session="-", orb_high=None, orb_low=None,
                breakout_direction=Direction.NONE, false_breakout=False, confirmed=False,
                blocked=False, score_impact=0.0, reason="no active ORB range", ts=now,
            )
            self._last_decision[snap.symbol.upper()] = dec
            return dec

        tf = self.config.orb.execution_tf
        post = [c for c in snap.tf(tf) if c.ts >= rng.end]
        last_close = post[-1].close if post else snap.tf(tf)[-1].close

        broke_long = any(c.close > rng.high for c in post)
        broke_short = any(c.close < rng.low for c in post)
        long_break = last_close > rng.high
        short_break = last_close < rng.low
        inside = rng.low <= last_close <= rng.high
        false_breakout = inside and (broke_long or broke_short)

        o = self.config.orb

        def finish(direction, confirmed, blocked, impact, reason):
            dec = ORBDecision(
                symbol=snap.symbol.upper(), session=rng.session, orb_high=rng.high,
                orb_low=rng.low, breakout_direction=direction, false_breakout=false_breakout,
                confirmed=confirmed, blocked=blocked, score_impact=impact, reason=reason, ts=now,
            )
            self._last_decision[snap.symbol.upper()] = dec
            return dec

        # --- block conditions (Part 2 spec) --------------------------------
        if false_breakout:
            return finish(Direction.NONE, False, True, o.score_false_breakout, "false breakout")
        if ctx.regime == Regime.HIGH_VOLATILITY:
            return finish(Direction.NONE, False, True, 0.0, "blocked: HIGH_VOLATILITY")
        if ctx.regime == Regime.RANGING and not (long_break or short_break):
            return finish(Direction.NONE, False, True, 0.0, "blocked: RANGING without breakout")
        if not ctx.news_safe:
            return finish(Direction.NONE, False, True, 0.0, "blocked: news danger window")
        if not ctx.correlation_safe:
            return finish(Direction.NONE, False, True, 0.0, "blocked: correlation conflict")
        if ctx.atr > 0:
            if rng.size < o.min_range_atr_mult * ctx.atr:
                return finish(Direction.NONE, False, True, 0.0, "blocked: range too small")
            if rng.size > o.max_range_atr_mult * ctx.atr:
                return finish(Direction.NONE, False, True, 0.0, "blocked: range too large")

        if not (long_break or short_break):
            return finish(Direction.NONE, False, False, 0.0, "no breakout close yet")

        direction = Direction.LONG if long_break else Direction.SHORT

        regime_ok = (
            ctx.regime in (Regime.TRENDING_UP, Regime.BREAKOUT)
            if direction == Direction.LONG
            else ctx.regime in (Regime.TRENDING_DOWN, Regime.BREAKOUT)
        )
        core_ok = (
            regime_ok
            and ctx.news_safe
            and ctx.spread_safe
            and ctx.exposure_safe.get(direction, False)
        )
        if not core_ok:
            why = []
            if not regime_ok:
                why.append(f"regime {ctx.regime.value} not aligned")
            if not ctx.spread_safe:
                why.append("spread")
            if not ctx.exposure_safe.get(direction, False):
                why.append("exposure")
            return finish(direction, False, True, 0.0, "blocked: " + ", ".join(why))

        # --- confirmed: award score ---------------------------------------
        impact = o.score_confirmed
        bits = ["ORB confirmed +%g" % o.score_confirmed]
        if ctx.h4d1_aligned.get(direction, False):
            impact += o.score_trend_align
            bits.append("trend +%g" % o.score_trend_align)
        if ctx.bos.get(direction, False):
            impact += o.score_bos
            bits.append("BOS +%g" % o.score_bos)
        return finish(direction, True, False, impact, "; ".join(bits))

    # ---- introspection for the API ---------------------------------------
    def status(self, now: datetime) -> dict:
        active = self.active_sessions(now)
        ranges = []
        for key, rng in self._ranges.items():
            _s, _e, trade_end, _d = self._window(rng.session, now)
            if now <= trade_end:  # still relevant today
                ranges.append({
                    "symbol": rng.symbol,
                    "session": rng.session,
                    "date": rng.date,
                    "orb_high": rng.high,
                    "orb_low": rng.low,
                    "complete": rng.complete,
                })
        return {
            "now": now.isoformat(),
            "active_sessions": active,
            "ranges": ranges,
            "last_decisions": {s: d.as_dict() for s, d in self._last_decision.items()},
        }
