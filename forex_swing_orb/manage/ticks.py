"""Broker tick-normalization utilities (Phase 7B-B).

NOT Position-Management arithmetic — these are broker-grid normalization helpers
(NormalizeDouble analog), mirroring the accepted PM's F2 approach so the manage
channel quantizes/compares stops on the same grid. Never-widen/never-loosen and
all PM triggers come from the frozen position/ modules, not here.
"""

from __future__ import annotations

import math

_FALLBACK_DIGITS = 5
_TICK_TOLERANCE = 0


def point(mt5, symbol):
    try:
        info = mt5.symbol_info(symbol)
        if info is not None and getattr(info, "point", None):
            return float(info.point)
    except Exception:
        pass
    return 10.0 ** (-_FALLBACK_DIGITS)


def digits(mt5, symbol):
    p = point(mt5, symbol)
    return max(0, int(round(-math.log10(p)))) if p > 0 else _FALLBACK_DIGITS


def quantize(value, mt5, symbol):
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return value
    return round(value, digits(mt5, symbol))


def ticks(value, mt5, symbol):
    return int(round(value / point(mt5, symbol)))


def eq_stop(a, b, mt5, symbol):
    if a is None or b is None:
        return a is b
    if not (math.isfinite(a) and math.isfinite(b)):
        return False
    return abs(ticks(a, mt5, symbol) - ticks(b, mt5, symbol)) <= _TICK_TOLERANCE
