"""Deterministic synthetic OHLC generators for Swing-ORB tests.

All builders are pure functions of their arguments (no clock, no RNG unless a
fixed seed is passed) so tests are fully reproducible.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


TF = 15  # execution timeframe (minutes)
BARS_PER_DAY = 24 * 60 // TF  # 96


def _index(start, n):
    return pd.date_range(start=start, periods=n, freq=f"{TF}min", tz="UTC")


def uptrend_frame(start="2024-01-01 00:00", days=39, drift=0.0012, slow_amp=0.010,
                  slow_period=8.0, fast_amp=0.0035, fast_period=1.0, base=1.10):
    """A rising two-sine series with ascending swing highs/lows on H4 AND D1.

    mid = base + drift*day + slow_amp*sin(2pi*day/slow_P) + fast_amp*sin(2pi*day/fast_P).
    The slow component gives D1 swings; the fast (intraday) component gives H4
    swings; the net drift makes each successive swing high/low higher -> BULLISH.
    Returns an OHLC(+volume) DataFrame with a UTC DatetimeIndex.
    """
    n = days * BARS_PER_DAY
    idx = _index(start, n)
    d = np.arange(n) / BARS_PER_DAY
    mid = (base + drift * d
           + slow_amp * np.sin(2.0 * math.pi * d / slow_period)
           + fast_amp * np.sin(2.0 * math.pi * d / fast_period))
    wig = 0.0003
    close = mid
    open_ = np.concatenate([[mid[0]], mid[:-1]])
    high = np.maximum(open_, close) + wig
    low = np.minimum(open_, close) - wig
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": 0.0},
        index=idx,
    )


def inject_bullish_orb(df, day_ts):
    """Inject a clean bullish OR-breakout-retest-confirmation into one UTC day.

    Winter date (London==UTC): OR window 08:00-09:00 = slots 32..35. Breakout
    at slot 40, retest touch at slot 42, minor swing high at slot 43, confirming
    close above it at slot 45. Returns (df2, ref) with key levels for assertions.
    """
    day = pd.Timestamp(day_ts, tz="UTC").normalize()
    base_close = float(df.loc[day + pd.Timedelta(minutes=TF * 31), "close"])
    orh = base_close + 0.0010
    orl = base_close - 0.0010
    u = {}
    # opening range slots 32..35 oscillate within [orl, orh]
    u[32] = {"open": base_close, "high": orh, "low": base_close - 0.0004, "close": base_close + 0.0004}
    u[33] = {"open": base_close + 0.0004, "high": orh, "low": orl, "close": base_close - 0.0002}
    u[34] = {"open": base_close - 0.0002, "high": base_close + 0.0006, "low": orl, "close": base_close + 0.0002}
    u[35] = {"open": base_close + 0.0002, "high": base_close + 0.0007, "low": base_close - 0.0006, "close": base_close}
    # slots 36..39 inside range (no breakout yet)
    for s in (36, 37, 38, 39):
        u[s] = {"open": base_close, "high": base_close + 0.0005, "low": base_close - 0.0005, "close": base_close}
    # breakout bar (slot 40): completed close well above orh + buffer
    bo = orh + 0.0008
    u[40] = {"open": base_close, "high": bo + 0.0002, "low": base_close - 0.0002, "close": bo}
    u[41] = {"open": bo, "high": bo + 0.0001, "low": orh + 0.0004, "close": orh + 0.0006}
    # retest bar (slot 42): low touches orh, holds (close above orh)
    u[42] = {"open": orh + 0.0006, "high": orh + 0.0007, "low": orh - 0.0001, "close": orh + 0.0003}
    # minor swing high (slot 43): local high above neighbours
    msh = orh + 0.0009
    u[43] = {"open": orh + 0.0003, "high": msh, "low": orh + 0.0002, "close": orh + 0.0007}
    # slot 44: small pullback so slot 43 is a confirmed 3-bar fractal high
    u[44] = {"open": orh + 0.0007, "high": orh + 0.0008, "low": orh + 0.0003, "close": orh + 0.0006}
    # confirming bar (slot 45): completed close above the minor swing high msh
    u[45] = {"open": orh + 0.0006, "high": msh + 0.0006, "low": orh + 0.0005, "close": msh + 0.0004}
    # continuation up so the trade can run to target
    run = msh + 0.0004
    for k, s in enumerate((46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56)):
        run = run + 0.0006
        u[s] = {"open": run - 0.0004, "high": run + 0.0002, "low": run - 0.0006, "close": run}
    df2 = set_day_bars(df, day_ts, u)
    ref = {"orh": orh, "orl": orl, "breakout_close": bo, "minor_swing_high": msh,
           "day": day, "confirm_slot": 45, "breakout_slot": 40}
    return df2, ref


def inject_bearish_orb(df, day_ts):
    """Mirror of inject_bullish_orb: breakout below OR low, retest from below,
    minor swing low, confirming close below it -> a SHORT setup."""
    day = pd.Timestamp(day_ts, tz="UTC").normalize()
    base_close = float(df.loc[day + pd.Timedelta(minutes=TF * 31), "close"])
    orh = base_close + 0.0010
    orl = base_close - 0.0010
    u = {}
    u[32] = {"open": base_close, "high": base_close + 0.0004, "low": orl, "close": base_close - 0.0004}
    u[33] = {"open": base_close - 0.0004, "high": orh, "low": orl, "close": base_close + 0.0002}
    u[34] = {"open": base_close + 0.0002, "high": orh, "low": base_close - 0.0006, "close": base_close - 0.0002}
    u[35] = {"open": base_close - 0.0002, "high": base_close + 0.0006, "low": base_close - 0.0007, "close": base_close}
    for s in (36, 37, 38, 39):
        u[s] = {"open": base_close, "high": base_close + 0.0005, "low": base_close - 0.0005, "close": base_close}
    bo = orl - 0.0008
    u[40] = {"open": base_close, "high": base_close + 0.0002, "low": bo - 0.0002, "close": bo}
    u[41] = {"open": bo, "high": orl - 0.0004, "low": bo - 0.0001, "close": orl - 0.0006}
    u[42] = {"open": orl - 0.0006, "high": orl + 0.0001, "low": orl - 0.0007, "close": orl - 0.0003}
    msl = orl - 0.0009
    u[43] = {"open": orl - 0.0003, "high": orl - 0.0002, "low": msl, "close": orl - 0.0007}
    u[44] = {"open": orl - 0.0007, "high": orl - 0.0003, "low": orl - 0.0008, "close": orl - 0.0006}
    u[45] = {"open": orl - 0.0006, "high": orl - 0.0005, "low": msl - 0.0006, "close": msl - 0.0004}
    run = msl - 0.0004
    for s in (46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56):
        run = run - 0.0006
        u[s] = {"open": run + 0.0004, "high": run + 0.0006, "low": run - 0.0002, "close": run}
    df2 = set_day_bars(df, day_ts, u)
    ref = {"orh": orh, "orl": orl, "breakout_close": bo, "minor_swing_low": msl,
           "day": day, "confirm_slot": 45, "breakout_slot": 40}
    return df2, ref


def downtrend_frame(**kw):
    """Mirror of uptrend_frame -> BEARISH structure."""
    df = uptrend_frame(**{k: v for k, v in kw.items() if k != "invert"})
    top = df["high"].max() + df["low"].min()
    out = pd.DataFrame(index=df.index)
    out["open"] = top - df["open"]
    out["close"] = top - df["close"]
    out["high"] = top - df["low"]
    out["low"] = top - df["high"]
    out["volume"] = 0.0
    return out


def set_day_bars(df, day_ts, updates):
    """Return a copy of df with specific 15m bars on a given UTC date replaced.

    `updates` maps an integer bar-of-day slot (0..95, i.e. UTC 00:00 + slot*15m)
    to a dict of {open,high,low,close}. Used to inject a precise ORB setup.
    """
    out = df.copy()
    day = pd.Timestamp(day_ts, tz="UTC").normalize()
    for slot, ohlc in updates.items():
        ts = day + pd.Timedelta(minutes=TF * slot)
        for col, val in ohlc.items():
            out.loc[ts, col] = val
    return out


def slot_ts(day_ts, slot):
    return pd.Timestamp(day_ts, tz="UTC").normalize() + pd.Timedelta(minutes=TF * slot)
