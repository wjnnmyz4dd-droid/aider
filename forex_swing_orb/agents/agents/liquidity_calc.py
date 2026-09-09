"""Deterministic liquidity calculations (agent-local helper; closed bars only).

Pure stdlib, no lookahead, deterministic tolerances. These compute
liquidity-domain features the strategy does NOT own (equal highs/lows, prior-
session extremes, sweeps, failed breakouts, distances). Strategy swing points are
CONSUMED (passed in), never recomputed here. Every function is a pure function of
its inputs.
"""

from __future__ import annotations


def norm_bar(b):
    """Accept {t,o,h,l,c}/{time,open,high,low,close} OR an already-normalized
    5-sequence (t,o,h,l,c). Returns a 5-tuple or None. Idempotent."""
    if isinstance(b, (tuple, list)) and len(b) == 5:
        t, o, h, low, c = b
        return (t, o, h, low, c) if None not in (h, low, c) else None
    if not isinstance(b, dict):
        return None

    def g(*names):
        for n in names:
            if n in b and b[n] is not None:
                return b[n]
        return None
    t = g("t", "time", "timestamp")
    o = g("o", "open"); h = g("h", "high"); low = g("l", "low"); c = g("c", "close")
    if None in (h, low, c):
        return None
    return (t, o, h, low, c)


def norm_bars(bars):
    out = []
    for b in bars or []:
        nb = norm_bar(b)
        if nb is not None:
            out.append(nb)
    return out


def local_peaks(bars):
    """Highs that are strict local maxima over interior closed bars. A simple
    1-bar extrema test — NOT the strategy's configurable fractal pivots."""
    nb = norm_bars(bars)
    return [nb[i][2] for i in range(1, len(nb) - 1)
            if nb[i][2] > nb[i - 1][2] and nb[i][2] > nb[i + 1][2]]


def local_troughs(bars):
    nb = norm_bars(bars)
    return [nb[i][3] for i in range(1, len(nb) - 1)
            if nb[i][3] < nb[i - 1][3] and nb[i][3] < nb[i + 1][3]]


def equal_levels(prices, tol):
    """Cluster near-equal price levels (within absolute tolerance ``tol``).
    Returns [(level, count)] sorted by level; only clusters with count >= 2."""
    if not prices:
        return []
    pts = sorted(prices)
    clusters = []
    group = [pts[0]]
    for p in pts[1:]:
        if abs(p - group[-1]) <= tol:
            group.append(p)
        else:
            clusters.append(group); group = [p]
    clusters.append(group)
    out = []
    for g in clusters:
        if len(g) >= 2:
            out.append((round(sum(g) / len(g), 10), len(g)))
    return out


def prior_session_extremes(prior_bars):
    nb = norm_bars(prior_bars)
    if not nb:
        return None, None
    return max(h for _, _, h, _, _ in nb), min(l for _, _, _, l, _ in nb)


def detect_sweep(bars, level, side, tol):
    """Detect a liquidity sweep of ``level`` on closed bars.

    side='above': a bar's HIGH pierces above ``level`` (by > tol). CONFIRMED if a
    later-or-same closed bar closes back below ``level`` (wick/failure); else
    UNCONFIRMED (broke and held). Mirror for 'below'. Returns
    'CONFIRMED'/'UNCONFIRMED'/'NONE'. No future info: only the given closed bars.
    """
    nb = norm_bars(bars)
    pierced = False
    for _, _, h, l, c in nb:
        if side == "above":
            if h > level + tol:
                pierced = True
                if c < level:
                    return "CONFIRMED"
            elif pierced and c < level:
                return "CONFIRMED"
        else:  # below
            if l < level - tol:
                pierced = True
                if c > level:
                    return "CONFIRMED"
            elif pierced and c > level:
                return "CONFIRMED"
    return "UNCONFIRMED" if pierced else "NONE"


def failed_breakout(bars, level, side, tol):
    """A true failed breakout: a bar CLOSES beyond ``level`` and a later bar
    CLOSES back on the original side (distinct from a single-bar wick sweep)."""
    nb = norm_bars(bars)
    broke = False
    for _, _, h, l, c in nb:
        if side == "above":
            if c > level + tol:
                broke = True
            elif broke and c < level:
                return True
        else:
            if c < level - tol:
                broke = True
            elif broke and c > level:
                return True
    return False


def nearest(levels, price):
    """(nearest_level, distance) over a list of price levels; (None, None) empty."""
    best, bd = None, None
    for lv in levels:
        d = abs(lv - price)
        if bd is None or d < bd:
            best, bd = lv, d
    return best, bd


def split_above_below(levels, price):
    above = sorted(l for l in levels if l > price)
    below = sorted((l for l in levels if l < price), reverse=True)
    return (above[0] if above else None), (below[0] if below else None)
