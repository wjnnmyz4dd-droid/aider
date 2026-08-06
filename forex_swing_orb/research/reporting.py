"""Institutional performance reporting (Phase 9B) — deterministic, read-only.

Builds session/pair/monthly/weekly/news/holding-time reports and an institutional
tear sheet from closed trades, and an FTMO report that CONSUMES the authoritative
``compliance.ftmo_levels`` (never re-derives FTMO math). No randomness, no wall
clock (all timestamps come from the trade records).
"""

from __future__ import annotations

from . import portfolio


def _group(trades, key):
    g = {}
    for t in trades:
        g.setdefault(t.get(key), []).append(t)
    return g


def _by(trades, key, metric_key="r_multiple"):
    return {str(k): portfolio.summary(v, metric_key)
            for k, v in sorted(_group(trades, key).items(), key=lambda kv: str(kv[0]))}


def session_performance(trades):
    return _by(trades, "session")


def pair_performance(trades):
    return _by(trades, "symbol")


def _period(trades, fmt):
    from ..bridge import serialize
    g = {}
    for t in trades:
        dt = serialize.parse_iso(t.get("close_time"))
        bucket = dt.strftime(fmt) if dt is not None else "UNKNOWN"
        g.setdefault(bucket, []).append(t)
    return {k: portfolio.summary(v) for k, v in sorted(g.items())}


def monthly_report(trades):
    return _period(trades, "%Y-%m")


def weekly_report(trades):
    return _period(trades, "%G-W%V")


def news_impact(trades):
    """Split performance by whether the trade was flagged news-adjacent."""
    tagged = {"news_adjacent": [], "clear": []}
    for t in trades:
        tagged["news_adjacent" if t.get("news_adjacent") else "clear"].append(t)
    return {k: portfolio.summary(v) for k, v in tagged.items()}


def holding_time(trades):
    """Holding-time stats in ``bars_held`` (deterministic; from trade records)."""
    held = [float(t["bars_held"]) for t in trades
            if isinstance(t.get("bars_held"), (int, float)) and not isinstance(t.get("bars_held"), bool)]
    if not held:
        return {"count": 0, "avg_bars": 0.0, "max_bars": 0.0, "min_bars": 0.0}
    return {"count": len(held), "avg_bars": round(sum(held) / len(held), 4),
            "max_bars": max(held), "min_bars": min(held)}


def ftmo_report(account_state, profile, ftmo_cfg):
    """FTMO statistics that CONSUME the authoritative compliance owner. Returns the
    canonical levels/budgets — never re-derives FTMO formulas."""
    from ..compliance.contract import ftmo_levels, finite
    levels = ftmo_levels(account_state or {}, profile, ftmo_cfg)
    equity = finite((account_state or {}).get("equity"))
    if levels is None:
        return {"available": False}
    return {
        "available": True,
        "official_daily_level": levels["official_daily_level"],
        "official_max_level": levels["official_max_level"],
        "internal_daily_level": levels["internal_daily_level"],
        "internal_max_level": levels["internal_max_level"],
        "remaining_daily_to_internal": (None if equity is None
                                        else round(equity - levels["internal_daily_level"], 6)),
        "remaining_max_to_internal": (None if equity is None
                                      else round(equity - levels["internal_max_level"], 6)),
        "source": "compliance.ftmo_levels",     # authoritative owner (not re-derived)
    }


def tear_sheet(trades, *, account_state=None, profile=None, ftmo_cfg=None, fills=None):
    """One deterministic institutional tear sheet aggregating the above."""
    sheet = {
        "kind": "tear_sheet",
        "overall": portfolio.summary(trades),
        "by_session": session_performance(trades),
        "by_pair": pair_performance(trades),
        "monthly": monthly_report(trades),
        "weekly": weekly_report(trades),
        "news_impact": news_impact(trades),
        "holding_time": holding_time(trades),
    }
    if account_state is not None and profile is not None and ftmo_cfg is not None:
        sheet["ftmo"] = ftmo_report(account_state, profile, ftmo_cfg)
    if fills is not None:
        from . import execution_analytics
        sheet["execution"] = execution_analytics.summary(fills)
    return sheet
