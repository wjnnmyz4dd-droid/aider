"""Execution analytics (Phase 9B) — deterministic, read-only.

Summarizes execution quality from ALREADY-RECORDED fills (the ENTER-channel EA
records ``execution.slippage`` etc. in bridge result records; this module only
aggregates them). It re-derives no execution logic and talks to no broker/MT5.
A ``fill`` dict has: symbol, session (optional), slippage (price units),
spread_points, requested_price, filled_price, latency_sec (optional).
"""

from __future__ import annotations

import math


def _f(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def _mean(xs):
    return round(sum(xs) / len(xs), 6) if xs else 0.0


def slippage_stats(fills, point=None):
    """Slippage distribution (price units, and points when ``point`` given)."""
    sl = [abs(_f(x.get("slippage"))) for x in fills if _f(x.get("slippage")) is not None]
    out = {"count": len(sl), "avg": _mean(sl), "worst": (max(sl) if sl else 0.0),
           "best": (min(sl) if sl else 0.0)}
    if point and point > 0:
        out["avg_points"] = round(out["avg"] / point, 6)
        out["worst_points"] = round(out["worst"] / point, 6)
    return out


def spread_stats(fills):
    sp = [_f(x.get("spread_points")) for x in fills if _f(x.get("spread_points")) is not None]
    return {"count": len(sp), "avg_points": _mean(sp),
            "max_points": (max(sp) if sp else 0.0)}


def latency_stats(fills):
    la = [_f(x.get("latency_sec")) for x in fills if _f(x.get("latency_sec")) is not None]
    return {"count": len(la), "avg_sec": _mean(la), "max_sec": (max(la) if la else 0.0)}


def fill_quality(fills):
    """Fraction of fills at/inside the requested price (no adverse slippage)."""
    graded = 0
    good = 0
    for x in fills:
        sl = _f(x.get("slippage"))
        if sl is None:
            continue
        graded += 1
        if sl <= 0:                        # filled at or better than requested
            good += 1
    return {"graded": graded, "at_or_better": good,
            "quality_ratio": round(good / graded, 6) if graded else 0.0}


def consistency(fills):
    """Std-dev of absolute slippage (lower = more consistent execution)."""
    sl = [abs(_f(x.get("slippage"))) for x in fills if _f(x.get("slippage")) is not None]
    if len(sl) < 2:
        return {"count": len(sl), "slippage_stdev": 0.0}
    m = sum(sl) / len(sl)
    return {"count": len(sl),
            "slippage_stdev": round(math.sqrt(sum((x - m) ** 2 for x in sl) / (len(sl) - 1)), 6)}


def _group_by(fills, key):
    groups = {}
    for x in fills:
        groups.setdefault(x.get(key), []).append(x)
    return groups


def by_symbol(fills):
    return {k: summary(v) for k, v in sorted(_group_by(fills, "symbol").items(),
                                             key=lambda kv: str(kv[0]))}


def by_session(fills):
    return {k: summary(v) for k, v in sorted(_group_by(fills, "session").items(),
                                             key=lambda kv: str(kv[0]))}


def summary(fills, point=None):
    return {
        "fills": len(fills),
        "slippage": slippage_stats(fills, point),
        "spread": spread_stats(fills),
        "latency": latency_stats(fills),
        "fill_quality": fill_quality(fills),
        "consistency": consistency(fills),
    }
