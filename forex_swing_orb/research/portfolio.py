"""Portfolio analytics (Phase 9B) — deterministic pure functions.

Computes NEW portfolio statistics (expectancy, R-multiples, MAE/MFE, drawdown,
equity curve, profit factor, recovery factor, win/loss distribution, risk-adjusted
returns) from a list of already-closed trades. It owns none of the production
subsystems and re-derives no strategy/compliance/FTMO/PM logic. No randomness, no
wall clock. A ``trade`` is a dict with at least ``r_multiple`` and/or ``pnl``;
optional ``mae``/``mfe`` (in R), ``session``, ``symbol``.
"""

from __future__ import annotations

import math


def _nums(trades, key):
    out = []
    for t in trades:
        v = t.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
            out.append(float(v))
    return out


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _stdev(xs):
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def win_loss(trades, key="r_multiple"):
    xs = _nums(trades, key)
    wins = [x for x in xs if x > 0]
    losses = [x for x in xs if x < 0]
    scratches = [x for x in xs if x == 0]
    n = len(xs)
    return {
        "count": n, "wins": len(wins), "losses": len(losses), "scratches": len(scratches),
        "win_rate": round(len(wins) / n, 6) if n else 0.0,
        "avg_win": round(_mean(wins), 6), "avg_loss": round(_mean(losses), 6),
        "largest_win": max(wins) if wins else 0.0,
        "largest_loss": min(losses) if losses else 0.0,
    }


def expectancy(trades, key="r_multiple"):
    """Mean outcome per trade (in R when key=r_multiple). Deterministic."""
    xs = _nums(trades, key)
    return round(_mean(xs), 6)


def profit_factor(trades, key="r_multiple"):
    xs = _nums(trades, key)
    gains = sum(x for x in xs if x > 0)
    losses = -sum(x for x in xs if x < 0)
    if losses == 0:
        return math.inf if gains > 0 else 0.0
    return round(gains / losses, 6)


def equity_curve(trades, key="r_multiple", starting=0.0):
    """Cumulative equity after each trade (deterministic order = input order)."""
    eq, cur = [], starting
    for t in trades:
        v = t.get(key)
        cur += float(v) if (isinstance(v, (int, float)) and not isinstance(v, bool)
                            and math.isfinite(v)) else 0.0     # NaN/Inf never poison equity
        eq.append(round(cur, 10))
    return eq


def max_drawdown(equity):
    """Max peak-to-trough drawdown of an equity series (absolute units)."""
    peak = -math.inf
    mdd = 0.0
    for e in equity:
        peak = max(peak, e)
        mdd = max(mdd, peak - e)
    return round(mdd, 10) if equity else 0.0


def recovery_factor(trades, key="r_multiple"):
    xs = _nums(trades, key)
    net = sum(xs)
    mdd = max_drawdown(equity_curve(trades, key))
    if mdd == 0:
        return math.inf if net > 0 else 0.0
    return round(net / mdd, 6)


def risk_adjusted(trades, key="r_multiple"):
    """Per-trade Sharpe-like ratio (mean/stdev of R). No annualization assumed."""
    xs = _nums(trades, key)
    sd = _stdev(xs)
    return round(_mean(xs) / sd, 6) if sd > 0 else 0.0


def mae_mfe(trades):
    """Aggregate Maximum Adverse / Favorable Excursion stats (expects R units)."""
    mae = _nums(trades, "mae")
    mfe = _nums(trades, "mfe")
    return {
        "avg_mae": round(_mean(mae), 6), "worst_mae": (min(mae) if mae else 0.0),
        "avg_mfe": round(_mean(mfe), 6), "best_mfe": (max(mfe) if mfe else 0.0),
        "count_mae": len(mae), "count_mfe": len(mfe),
    }


def summary(trades, key="r_multiple"):
    """One deterministic portfolio summary dict."""
    eq = equity_curve(trades, key)
    return {
        "trade_count": len(_nums(trades, key)),
        "expectancy": expectancy(trades, key),
        "profit_factor": profit_factor(trades, key),
        "recovery_factor": recovery_factor(trades, key),
        "risk_adjusted": risk_adjusted(trades, key),
        "net": round(sum(_nums(trades, key)), 10),
        "max_drawdown": max_drawdown(eq),
        "win_loss": win_loss(trades, key),
        "mae_mfe": mae_mfe(trades),
        "final_equity": eq[-1] if eq else 0.0,
    }
