"""Tier 1 replay performance report (measurement tier) tests.

Proves research.replay_report turns a harness trade list into a performance report
by delegating verbatim to research.portfolio — no new analytics, no duplication.
Pure over hand-built trade records in the harness schema (no engine run needed).
"""

from __future__ import annotations

from forex_swing_orb.research import portfolio, replay_report


def _trade(direction, r, session="LONDON", symbol="EURUSD.FX", mae=0.0, mfe=1.0):
    return {"direction": direction, "r_multiple": r, "pnl": r * 10.0,
            "session": session, "symbol": symbol, "mae": mae, "mfe": mfe,
            "exit_reason": "EXIT_TAKE_PROFIT" if r > 0 else "EXIT_STOP_LOSS"}


def _sample():
    return [
        _trade("LONG", 2.0), _trade("LONG", -1.0), _trade("SHORT", 2.0),
        _trade("SHORT", -1.0), _trade("LONG", 2.0),
    ]


def test_performance_delegates_to_portfolio():
    trades = _sample()
    rep = replay_report.performance_report({"status": "OK", "labels": {"x": "y"},
                                            "trades": trades})
    assert rep["status"] == "OK"
    assert rep["performance"] == portfolio.summary(trades)     # verbatim delegation
    for k in ("expectancy", "profit_factor", "win_loss", "mae_mfe", "max_drawdown"):
        assert k in rep["performance"]


def test_long_short_and_session_breakdown():
    rep = replay_report.performance_report(_sample())
    assert rep["long"]["win_loss"]["count"] == 3
    assert rep["short"]["win_loss"]["count"] == 2
    assert "LONDON" in rep["by_session"]
    assert "EURUSD.FX" in rep["by_symbol"]
    # equity curve length == number of finite-R trades
    assert len(rep["equity_curve"]) == 5


def test_accepts_bare_trade_list():
    rep = replay_report.performance_report(_sample())
    assert rep["performance"]["trade_count"] == 5


def test_empty_trades():
    rep = replay_report.performance_report({"status": "OK", "trades": []})
    assert rep["performance"]["trade_count"] == 0
    assert rep["equity_curve"] == []


def test_parity_failure_withholds_performance():
    rep = replay_report.performance_report(
        {"status": "PARITY_FAILURE", "parity": {"passed": False}, "note": "diverged"})
    assert rep["status"] == "PARITY_FAILURE"
    assert "performance" not in rep
