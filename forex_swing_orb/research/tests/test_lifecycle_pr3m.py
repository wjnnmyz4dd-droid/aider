"""PR-3M — observational analytics foundation: non-duplication + lifecycle ingest.

Proves (a) the new reader ingests the CANONICAL per-signal outcome fact and delegates
ALL math to research.portfolio (no second calculator), (b) idempotent one-trade-per-
signal semantics, (c) score-cohort readiness with NO fabricated score, (d) UNAVAILABLE
facts are surfaced not invented, and (e) the analytics layer holds zero trading
authority and introduces no import into trading-critical paths. Deterministic.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from forex_swing_orb.agents.memory import MemoryStore
from forex_swing_orb.research import lifecycle, portfolio

REPO = Path(__file__).resolve().parents[3]
PKG = REPO / "forex_swing_orb"
TRADING_PKGS = ("bridge", "compliance", "ea_mt5", "manage", "position",
                "producer", "runtime", "session", "live")


def _mem(tmp_path):
    return MemoryStore(tmp_path / "memory")


def _outcome(sid, r_multiple=1.0, symbol="EURUSD.FX", direction="LONG",
             taken=True, status="CLOSED", **over):
    won = (r_multiple > 0) if isinstance(r_multiple, (int, float)) else None
    c = {"schema_version": 1, "signal_id": sid, "status": status, "won": won,
         "taken": taken, "r_multiple": r_multiple, "direction": direction,
         "symbol": symbol, "ticket": 1, "broker_order_id": 1, "entry": 1.10000,
         "initial_stop": 1.09800, "weighted_close": 1.10400, "closed_volume": 0.10,
         "deal_count": 1, "realized_r_source": "mt5_deal_history"}
    c.update(over)
    return c


def _write(mem, content, ts="2026-01-05T12:00:00Z"):
    mem.write_raw(lifecycle.OUTCOME_KIND, content["symbol"], content,
                  source="outcome_reconciler", timestamp=ts,
                  correlation_id=content["signal_id"])


SID_A = "a1b2c3d4e5f60718"
SID_B = "b1b2c3d4e5f60718"
SID_C = "c1b2c3d4e5f60718"


# --------------------------------------------------------------------------- #
# 2 / 3 / 11 — canonical IDs reused; one executed signal counts once; R verbatim
# --------------------------------------------------------------------------- #
def test_one_executed_signal_counts_once(tmp_path):
    m = _mem(tmp_path); _write(m, _outcome(SID_A, r_multiple=2.0))
    trades = lifecycle.load_closed_trades(m)
    assert len(trades) == 1
    assert trades[0]["signal_id"] == SID_A          # canonical signal_id reused
    assert trades[0]["r_multiple"] == 2.0           # R verbatim from outcome fact


# --------------------------------------------------------------------------- #
# 4 / 5 — replay + restart do not double-count
# --------------------------------------------------------------------------- #
def test_replay_does_not_double_count(tmp_path):
    m = _mem(tmp_path)
    _write(m, _outcome(SID_A)); _write(m, _outcome(SID_A))   # identical replay
    assert len(lifecycle.load_closed_trades(m)) == 1


def test_restart_does_not_double_count(tmp_path):
    m = _mem(tmp_path); _write(m, _outcome(SID_A))
    m2 = MemoryStore(tmp_path / "memory")            # fresh store over same dir (restart)
    assert len(lifecycle.load_closed_trades(m2)) == 1


# --------------------------------------------------------------------------- #
# 6 / 7 / 8 — HELD/rejected excluded; reconciliation->EXECUTED is one trade
# --------------------------------------------------------------------------- #
def test_held_and_rejected_signals_not_counted(tmp_path):
    m = _mem(tmp_path)
    _write(m, _outcome(SID_A))                       # executed+closed -> counts
    _write(m, _outcome(SID_B, taken=False))          # not taken -> excluded
    trades = lifecycle.load_closed_trades(m)
    assert [t["signal_id"] for t in trades] == [SID_A]   # HELD/rejected never phantom


def test_reconciled_execution_is_one_trade(tmp_path):
    m = _mem(tmp_path); _write(m, _outcome(SID_A, status="CLOSED"))
    assert len(lifecycle.load_closed_trades(m)) == 1


# --------------------------------------------------------------------------- #
# 9 / 10 / 12 / 13 / 14 — classification + formulas via the SINGLE calculator
# --------------------------------------------------------------------------- #
def test_win_loss_breakeven_classification_deterministic(tmp_path):
    m = _mem(tmp_path)
    _write(m, _outcome(SID_A, r_multiple=2.0))       # win
    _write(m, _outcome(SID_B, r_multiple=-1.0))      # loss
    _write(m, _outcome(SID_C, r_multiple=0.0))       # scratch / break-even
    wl = portfolio.win_loss(lifecycle.load_closed_trades(m))
    assert wl["wins"] == 1 and wl["losses"] == 1 and wl["scratches"] == 1


def test_profit_factor_expectancy_drawdown_formulas(tmp_path):
    m = _mem(tmp_path)
    _write(m, _outcome(SID_A, r_multiple=2.0))
    _write(m, _outcome(SID_B, r_multiple=-1.0))
    trades = lifecycle.load_closed_trades(m)
    assert portfolio.profit_factor(trades) == 2.0            # 2.0 / 1.0
    assert portfolio.expectancy(trades) == pytest.approx(0.5)  # (2-1)/2
    # equity [2.0, 1.0] -> peak 2.0, trough 1.0 -> drawdown 1.0
    assert portfolio.max_drawdown(portfolio.equity_curve(trades)) == 1.0


# --------------------------------------------------------------------------- #
# 15-21 — score cohorts (bands + sub-70 separated) via cohort_of
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("score,cohort", [
    (70, "70-74"), (74, "70-74"), (75, "75-79"), (79, "75-79"),
    (80, "80-84"), (84, "80-84"), (85, "85-89"), (89, "85-89"),
    (90, "90-94"), (94, "90-94"), (95, "95-100"), (100, "95-100"),
])
def test_score_cohort_bands(score, cohort):
    assert lifecycle.cohort_of(score) == cohort


def test_sub_70_kept_separate_not_mixed():
    assert lifecycle.cohort_of(69) == lifecycle.SCORE_BELOW_MIN
    assert lifecycle.cohort_of(0) == lifecycle.SCORE_BELOW_MIN
    assert lifecycle.SCORE_BELOW_MIN not in lifecycle.SCORE_COHORTS


def test_score_unavailable_when_absent_or_invalid():
    for bad in (None, "72", float("nan"), True, 101):
        assert lifecycle.cohort_of(bad) == lifecycle.SCORE_UNAVAILABLE


def test_cohort_breakdown_all_unavailable_no_fabricated_score(tmp_path):
    # no trade carries a score today -> every trade lands in UNAVAILABLE (evidence
    # layer READY, score NOT fabricated).
    m = _mem(tmp_path); _write(m, _outcome(SID_A)); _write(m, _outcome(SID_B))
    bd = lifecycle.cohort_breakdown(lifecycle.load_closed_trades(m))
    assert set(bd) == {lifecycle.SCORE_UNAVAILABLE}
    assert bd[lifecycle.SCORE_UNAVAILABLE]["trade_count"] == 2


# --------------------------------------------------------------------------- #
# 22 / 23 — session/symbol breakdown does not duplicate trades
# --------------------------------------------------------------------------- #
def test_symbol_and_session_breakdown_no_duplication(tmp_path):
    from forex_swing_orb.research import reporting
    m = _mem(tmp_path)
    _write(m, _outcome(SID_A, symbol="EURUSD.FX"))
    _write(m, _outcome(SID_B, symbol="GBPUSD.FX"))
    _write(m, _outcome(SID_C, symbol="EURUSD.FX"))
    trades = lifecycle.load_closed_trades(m)
    by_sym = reporting.pair_performance(trades)
    assert sum(v["trade_count"] for v in by_sym.values()) == len(trades) == 3
    by_sess = reporting.session_performance(trades)      # session UNAVAILABLE -> one bucket
    assert sum(v["trade_count"] for v in by_sess.values()) == len(trades)


# --------------------------------------------------------------------------- #
# 24 / 25 — UNAVAILABLE facts surfaced not fabricated; provenance distinguishable
# --------------------------------------------------------------------------- #
def test_unavailable_facts_not_fabricated(tmp_path):
    m = _mem(tmp_path); _write(m, _outcome(SID_A))
    t = lifecycle.load_closed_trades(m)[0]
    for k in ("realized_pnl", "mae", "mfe", "session", "trade_score"):
        assert t[k] is None                             # surfaced as absent, never invented


def test_fact_provenance_distinguishable():
    fa = lifecycle.FACT_AVAILABILITY
    assert fa["weighted_close"] == lifecycle.REALIZED_BROKER_FACT
    assert fa["r_multiple"] == lifecycle.DERIVED_METRIC
    for u in ("realized_pnl", "mae", "mfe", "trade_score", "session"):
        assert fa[u] == lifecycle.UNAVAILABLE


# --------------------------------------------------------------------------- #
# 1 / Q — no duplicate calculator; lifecycle recomputes nothing
# --------------------------------------------------------------------------- #
def test_single_calculator_authority_no_duplicates():
    # each core metric is defined in EXACTLY ONE production module (research/portfolio)
    import re
    for fn in ("def expectancy", "def profit_factor", "def max_drawdown", "def win_loss"):
        hits = [p for p in PKG.rglob("*.py")
                if "/tests/" not in str(p) and re.search(rf"^{fn}\(", p.read_text(), re.M)]
        assert hits == [PKG / "research" / "portfolio.py"], f"{fn}: {hits}"


def test_lifecycle_defines_no_metric_math():
    src = (PKG / "research" / "lifecycle.py").read_text()
    for banned in ("def expectancy", "def profit_factor", "def max_drawdown",
                   "def win_loss", "def equity_curve"):
        assert banned not in src                         # delegates to portfolio; recomputes nothing


# --------------------------------------------------------------------------- #
# 26-32 — zero trading authority; no analytics import in trading-critical paths
# --------------------------------------------------------------------------- #
def test_lifecycle_imports_no_trading_authority():
    src = (PKG / "research" / "lifecycle.py").read_text()
    for banned in ("execution_consumer", "order_send", "position_manager",
                   "compliance.engine", "compliance.gates", "compliance.sizing",
                   "mock_mt5", "modify_stop"):
        assert banned not in src


def test_no_trading_module_imports_research():
    import re
    offenders = []
    for pkg in TRADING_PKGS:
        for p in (PKG / pkg).rglob("*.py"):
            if "/tests/" in str(p):
                continue
            if re.search(r"import\s+.*\bresearch\b|from\s+.*research", p.read_text()):
                offenders.append(str(p.relative_to(PKG)))
    assert offenders == []                               # research never enters trading paths


def test_lifecycle_defines_no_new_reason_or_health_vocabulary():
    src = (PKG / "research" / "lifecycle.py").read_text()
    assert "class ReasonCode" not in src and "class PMReason" not in src
    assert "write_health" not in src and "def status(" not in src


# --------------------------------------------------------------------------- #
# composed report reuses canonical calculators
# --------------------------------------------------------------------------- #
def test_lifecycle_report_composes_canonical_calculators(tmp_path):
    m = _mem(tmp_path)
    _write(m, _outcome(SID_A, r_multiple=2.0))
    _write(m, _outcome(SID_B, r_multiple=-1.0))
    rep = lifecycle.lifecycle_report(m)
    assert rep["trade_count"] == 2
    assert rep["overall"] == portfolio.summary(lifecycle.load_closed_trades(m))
    assert rep["score_status"] == lifecycle.SCORE_UNAVAILABLE
    assert rep["source_kind"] == "execution_outcome"
