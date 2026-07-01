"""Deterministic synthetic market data for tests and the validation suite.

Timestamps are anchored to a fixed weekday inside the New York session so the
session/ORB clock behaviour is reproducible.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List

from phantom.types import Candle, Direction, MarketSnapshot, NewsWindow

# Monday 2024-06-03 14:00 UTC. NY opens 09:30 ET = 13:30 UTC (EDT), so the NY
# opening range is 13:30–13:45 UTC and we sit 15 min into the trade window.
NOW = datetime(2024, 6, 3, 14, 0, tzinfo=timezone.utc)
BASE = 1.1000


def _gen(tf_minutes: int, count: int, end_ts: datetime, base: float, drift: float,
         pad_frac: float = 0.0003) -> List[Candle]:
    """Generate ``count`` bars ending at ``end_ts`` (inclusive), oldest first."""
    bars: List[Candle] = []
    start = end_ts - timedelta(minutes=tf_minutes * (count - 1))
    price = base
    pad = base * pad_frac
    for i in range(count):
        ts = start + timedelta(minutes=tf_minutes * i)
        o = price
        c = price + drift
        hi = max(o, c) + abs(drift) * 0.5 + pad
        lo = min(o, c) - abs(drift) * 0.5 - pad
        bars.append(Candle(ts, o, hi, lo, c))
        price = c
    return bars


def _wavy(tf_minutes: int, count: int, end_ts: datetime, base: float, unit: float,
          up_leg: int = 5, down_leg: int = 2) -> List[Candle]:
    """A net-uptrend built from alternating up/down legs. Legs of length >=3
    guarantee that turning points are strict local extrema over a 2-bar fractal
    window, so swing pivots (and therefore BOS / CHOCH / sweeps) form."""
    pattern = [unit] * up_leg + [-unit] * down_leg
    period = len(pattern)
    bars: List[Candle] = []
    start = end_ts - timedelta(minutes=tf_minutes * (count - 1))
    p = base
    for i in range(count):
        ts = start + timedelta(minutes=tf_minutes * i)
        step = pattern[i % period]
        o, c = p, p + step
        pos = i % period
        peak = pos == up_leg - 1      # last up bar -> swing high
        trough = pos == period - 1    # last down bar -> swing low
        hi = max(o, c) + unit * (0.6 if peak else 0.15)
        lo = min(o, c) - unit * (0.6 if trough else 0.15)
        bars.append(Candle(ts, o, hi, lo, c))
        p = c
    return bars


def _oscillating(tf_minutes: int, count: int, end_ts: datetime, base: float,
                 amp_frac: float = 0.0008) -> List[Candle]:
    bars: List[Candle] = []
    start = end_ts - timedelta(minutes=tf_minutes * (count - 1))
    amp = base * amp_frac
    for i in range(count):
        ts = start + timedelta(minutes=tf_minutes * i)
        phase = (i % 6) - 2.5
        o = base + amp * phase / 5
        c = base + amp * ((i + 1) % 6 - 2.5) / 5
        hi = max(o, c) + amp * 0.4
        lo = min(o, c) - amp * 0.4
        bars.append(Candle(ts, o, hi, lo, c))
    return bars


def _orb_breakout_tail(prev_close: float, end_ts: datetime, unit: float) -> List[Candle]:
    """Three M15 bars: a tight opening-range bar (13:30), then two bars that
    break and hold above it -> a clean confirmed long ORB."""
    p = prev_close
    t30 = end_ts - timedelta(minutes=30)
    t45 = end_ts - timedelta(minutes=15)
    t00 = end_ts
    c30 = Candle(t30, p - 0.1 * unit, p + 0.6 * unit, p - 0.6 * unit, p + 0.1 * unit)  # range 1.2u
    c45 = Candle(t45, p + 0.1 * unit, p + 1.1 * unit, p + 0.0 * unit, p + 1.0 * unit)  # closes above high
    c00 = Candle(t00, p + 1.0 * unit, p + 1.7 * unit, p + 0.9 * unit, p + 1.6 * unit)  # holds the break
    return [c30, c45, c00]


def uptrend_candles() -> Dict[str, List[Candle]]:
    u = BASE * 0.0005
    # Body length chosen so the final body bar lands on an up-leg peak (index
    # 74, 74 % 7 == 4 == up_leg-1); the ORB tail then breaks to genuine new
    # highs, which is what makes BOS fire and keeps RR favourable.
    m15_body = _wavy(15, 75, NOW - timedelta(minutes=45), BASE, u)
    m15 = m15_body + _orb_breakout_tail(m15_body[-1].close, NOW, u)
    return {
        "M15": m15,
        "H1": _wavy(60, 60, NOW, BASE, u),
        "H4": _wavy(240, 60, NOW.replace(minute=0), BASE, u),
        "D1": _wavy(1440, 60, NOW.replace(hour=0, minute=0), BASE, u),
    }


def approve_long_snapshot() -> MarketSnapshot:
    """A clean multi-timeframe uptrend with an NY ORB breakout -> APPROVE/LONG."""
    return MarketSnapshot(
        symbol="EURUSD",
        now=NOW,
        candles=uptrend_candles(),
        spread=0.00008,
        open_positions={},
        news_windows=[],
        account_drawdown_pct=0.0,
    )


def ranging_snapshot() -> MarketSnapshot:
    base = BASE
    return MarketSnapshot(
        symbol="EURUSD",
        now=NOW,
        candles={
            "M15": _oscillating(15, 80, NOW, base),
            "H1": _oscillating(60, 60, NOW, base),
            "H4": _oscillating(240, 60, NOW.replace(minute=0), base),
            "D1": _oscillating(1440, 60, NOW.replace(hour=0, minute=0), base),
        },
        spread=0.00008,
    )


def guard_blocked_snapshot() -> MarketSnapshot:
    """Uptrend, but spread is far too wide -> BLOCK via Spread Filter."""
    snap = approve_long_snapshot()
    snap.spread = 0.01  # absurd spread
    return snap
