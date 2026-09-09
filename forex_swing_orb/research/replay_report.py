"""Tier 1 replay performance report (measurement tier).

Consumes the trade list produced by the ``backtest`` replay harness and delegates
ALL performance math to :mod:`research.portfolio` (expectancy, profit factor,
drawdown, MFE/MAE, win/loss, equity curve). It re-derives no strategy/compliance/
FTMO/PM logic and owns no analytics of its own.

This lives under ``research/`` on purpose: the backtest harness must not import
``research`` (production boundary guard), so the harness returns trades and this
measurement-tier module turns them into the performance report. Results are
STRATEGY-EDGE RESEARCH only — never live expectancy (Tier 1 uses the engine's
static exits, gross costs, and does not replay historical news/compliance or the
Position Manager).
"""

from __future__ import annotations

from . import portfolio


def _subset(trades, pred):
    sub = [t for t in trades if pred(t)]
    return portfolio.summary(sub) if sub else {"trade_count": 0}


def performance_report(result):
    """Return a performance report for a Tier 1 harness result.

    ``result`` may be the runner's dict (with a ``trades`` list) or a bare list of
    trade-record dicts. Deterministic; pure.
    """
    if isinstance(result, dict):
        if result.get("status") == "PARITY_FAILURE":
            # never emit performance for a parity-failed replay
            return {"status": "PARITY_FAILURE", "parity": result.get("parity"),
                    "note": result.get("note")}
        trades = result.get("trades", [])
        labels = result.get("labels", {})
    else:
        trades, labels = list(result), {}

    report = {
        "status": "OK",
        "labels": labels,
        "performance": portfolio.summary(trades),
        "long": _subset(trades, lambda t: str(t.get("direction")).upper() == "LONG"),
        "short": _subset(trades, lambda t: str(t.get("direction")).upper() == "SHORT"),
        "equity_curve": portfolio.equity_curve(trades),
        "by_session": {},
        "by_symbol": {},
    }
    for sid in sorted({t.get("session") for t in trades if t.get("session")}):
        report["by_session"][sid] = _subset(trades, lambda t, s=sid: t.get("session") == s)
    for sym in sorted({t.get("symbol") for t in trades if t.get("symbol")}):
        report["by_symbol"][sym] = _subset(trades, lambda t, y=sym: t.get("symbol") == y)
    return report
