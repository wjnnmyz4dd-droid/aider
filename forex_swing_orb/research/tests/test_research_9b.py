"""Phase 9B — Research & Analytics framework tests.

Determinism, analytics correctness, walk-forward, Monte Carlo reproducibility,
reporting, and the isolation/ownership/authority acceptance guarantees.
"""

from __future__ import annotations

import inspect
import math
from pathlib import Path

import pytest

from forex_swing_orb.research import (portfolio, execution_analytics, reporting,
                                     walk_forward, montecarlo)
from forex_swing_orb.research.experiments import (ExperimentManager, Experiment,
                                                 parameter_study, historical_replay)
from forex_swing_orb.research.provenance import ExperimentRecord, git_head, ProvenanceError

REPO = Path(__file__).resolve().parents[3]
PKG = REPO / "forex_swing_orb"

TRADES = [
    {"r_multiple": 2.0, "pnl": 200, "mae": -0.4, "mfe": 2.2, "session": "LONDON",
     "symbol": "EURUSD.FX", "close_time": "2026-01-05T12:00:00Z", "bars_held": 8},
    {"r_multiple": -1.0, "pnl": -100, "mae": -1.0, "mfe": 0.3, "session": "LONDON",
     "symbol": "EURUSD.FX", "close_time": "2026-01-06T12:00:00Z", "bars_held": 3},
    {"r_multiple": 1.5, "pnl": 150, "mae": -0.3, "mfe": 1.6, "session": "NEW_YORK",
     "symbol": "GBPUSD.FX", "close_time": "2026-02-06T12:00:00Z", "bars_held": 10},
    {"r_multiple": -1.0, "pnl": -100, "mae": -1.1, "mfe": 0.1, "session": "NEW_YORK",
     "symbol": "GBPUSD.FX", "close_time": "2026-02-07T12:00:00Z", "bars_held": 2},
]


# --------------------------------------------------------------------------- #
# portfolio analytics correctness
# --------------------------------------------------------------------------- #
def test_expectancy_and_profit_factor():
    assert portfolio.expectancy(TRADES) == pytest.approx((2.0 - 1.0 + 1.5 - 1.0) / 4)
    assert portfolio.profit_factor(TRADES) == pytest.approx((2.0 + 1.5) / (1.0 + 1.0))


def test_equity_and_drawdown():
    eq = portfolio.equity_curve(TRADES)
    assert eq == [2.0, 1.0, 2.5, 1.5]
    assert portfolio.max_drawdown(eq) == pytest.approx(1.0)   # 2.5 -> 1.5


def test_recovery_and_risk_adjusted_and_winloss():
    assert portfolio.recovery_factor(TRADES) == pytest.approx(1.5 / 1.0)
    assert isinstance(portfolio.risk_adjusted(TRADES), float)
    wl = portfolio.win_loss(TRADES)
    assert wl["wins"] == 2 and wl["losses"] == 2 and wl["win_rate"] == 0.5


def test_mae_mfe_and_summary_deterministic():
    mm = portfolio.mae_mfe(TRADES)
    assert mm["worst_mae"] == -1.1 and mm["best_mfe"] == 2.2
    assert portfolio.summary(TRADES) == portfolio.summary(TRADES)   # deterministic


def test_profit_factor_no_losses_is_inf():
    assert portfolio.profit_factor([{"r_multiple": 1.0}]) == math.inf


# --------------------------------------------------------------------------- #
# execution analytics
# --------------------------------------------------------------------------- #
FILLS = [
    {"symbol": "EURUSD.FX", "session": "LONDON", "slippage": 0.00003, "spread_points": 8, "latency_sec": 0.2},
    {"symbol": "EURUSD.FX", "session": "LONDON", "slippage": -0.00001, "spread_points": 9, "latency_sec": 0.3},
    {"symbol": "GBPUSD.FX", "session": "NEW_YORK", "slippage": 0.00010, "spread_points": 15, "latency_sec": 0.5},
]


def test_execution_summary():
    s = execution_analytics.summary(FILLS, point=0.00001)
    assert s["fills"] == 3
    assert s["slippage"]["worst"] == pytest.approx(0.00010)
    assert s["slippage"]["worst_points"] == pytest.approx(10.0)
    assert s["fill_quality"]["at_or_better"] == 1        # the -0.00001 fill
    assert s["spread"]["max_points"] == 15


def test_execution_by_symbol_session_deterministic():
    a = execution_analytics.by_symbol(FILLS)
    assert set(a.keys()) == {"EURUSD.FX", "GBPUSD.FX"}
    assert execution_analytics.by_session(FILLS) == execution_analytics.by_session(FILLS)


# --------------------------------------------------------------------------- #
# reporting (consumes compliance owner for FTMO)
# --------------------------------------------------------------------------- #
def test_reporting_groups_and_tearsheet():
    sess = reporting.session_performance(TRADES)
    assert set(sess.keys()) == {"LONDON", "NEW_YORK"}
    assert set(reporting.monthly_report(TRADES).keys()) == {"2026-01", "2026-02"}
    sheet = reporting.tear_sheet(TRADES, fills=FILLS)
    assert sheet["overall"]["trade_count"] == 4 and "execution" in sheet
    assert reporting.holding_time(TRADES)["max_bars"] == 10


def test_ftmo_report_consumes_compliance_owner():
    from forex_swing_orb.compliance.contract import FtmoProfile, FtmoConfig
    prof = FtmoProfile(initial_balance=100000.0, account_currency="USD",
                       rule_source="x", rule_source_verified_at="y", profile_verified=True)
    acct = {"day_start_balance": 100000.0, "equity": 100000.0}
    rep = reporting.ftmo_report(acct, prof, FtmoConfig())
    assert rep["available"] and rep["official_daily_level"] == 95000.0
    assert rep["source"] == "compliance.ftmo_levels"      # authoritative owner


# --------------------------------------------------------------------------- #
# walk-forward
# --------------------------------------------------------------------------- #
class _StubEngine:
    """Minimal engine with the SignalEngine interface (generate/instructions)."""
    def __init__(self):
        self.instructions = {}
    def generate(self, data_map):
        out = {}
        for sym, df in data_map.items():
            self.instructions[sym] = [{"i": i} for i in range(len(df) // 5)]
            out[sym] = df["close"]
        return out


def _df(n):
    import pandas as pd
    idx = pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({"open": range(n), "high": range(n), "low": range(n),
                         "close": range(n)}, index=idx)


def test_rolling_windows_deterministic():
    assert walk_forward.rolling_windows(10, 4, 2) == [(0, 4), (2, 6), (4, 8), (6, 10)]
    assert walk_forward.rolling_windows(3, 4, 2) == []       # fail closed
    assert walk_forward.rolling_windows(10, 0, 2) == []


def test_walk_forward_and_stability():
    df = _df(30)
    res = walk_forward.walk_forward(_StubEngine(), df, "EURUSD.FX", window=10, step=5)
    assert [r["window_index"] for r in res] == [0, 1, 2, 3, 4]
    assert all(r["instruction_count"] == 2 for r in res)     # 10//5
    st = walk_forward.stability([r["instruction_count"] for r in res])
    assert st["mean"] == 2.0 and st["stdev"] == 0.0 and st["consistency"] == 1.0


def test_walk_forward_deterministic_repeat():
    df = _df(30)
    a = walk_forward.walk_forward(_StubEngine(), df, "EURUSD.FX", window=10, step=5)
    b = walk_forward.walk_forward(_StubEngine(), df, "EURUSD.FX", window=10, step=5)
    assert a == b


def test_regime_validation():
    df = _df(40)
    res = walk_forward.walk_forward(_StubEngine(), df, "EURUSD.FX", window=10, step=10)
    rv = walk_forward.regime_validation(res, lambda r: "even" if r["start"] % 20 == 0 else "odd")
    assert set(rv.keys()) == {"even", "odd"}


def test_walk_forward_loads_real_frozen_engine():
    eng = walk_forward.load_frozen_engine({"min_history_bars": 60})
    assert hasattr(eng, "generate") and hasattr(eng, "instructions")
    assert type(eng).__name__ == "SignalEngine"             # the real frozen engine


# --------------------------------------------------------------------------- #
# Monte Carlo (seeded, reproducible)
# --------------------------------------------------------------------------- #
def test_montecarlo_reproducible_with_seed():
    rs = [2.0, -1.0, 1.5, -1.0, 3.0, -1.0]
    a = montecarlo.bootstrap(rs, sims=500, seed=42)
    b = montecarlo.bootstrap(rs, sims=500, seed=42)
    assert a == b                                            # identical seed -> identical
    c = montecarlo.bootstrap(rs, sims=500, seed=43)
    assert a["terminal"] != c["terminal"]                   # different seed -> different


def test_montecarlo_requires_seed_and_data():
    with pytest.raises(montecarlo.MonteCarloError):
        montecarlo.bootstrap([1.0], sims=10, seed=None)      # unseeded rejected
    with pytest.raises(montecarlo.MonteCarloError):
        montecarlo.bootstrap([], sims=10, seed=1)            # no data


# --------------------------------------------------------------------------- #
# experiments + provenance
# --------------------------------------------------------------------------- #
def _exp():
    return Experiment("expect", lambda p, c: ({"expectancy": portfolio.expectancy(TRADES)},
                                              {"pf": portfolio.profit_factor(TRADES)}),
                      dataset_id="ds1", parameters={"key": "r_multiple"}, config={"v": 1})


def test_experiment_records_provenance(tmp_path):
    mgr = ExperimentManager(tmp_path / "exp.jsonl")
    rec = mgr.run(_exp(), timestamp="2026-01-07T10:00:00Z")
    assert rec["git_commit"] and rec["strategy_version"]
    assert rec["dataset_id"] == "ds1" and rec["record_id"]
    assert rec["results"]["expectancy"] == portfolio.expectancy(TRADES)
    assert mgr.read_all()[-1]["record_id"] == rec["record_id"]


def test_experiment_reproducible_record_id():
    a = _exp().run("2026-01-07T10:00:00Z")
    b = _exp().run("2026-01-07T10:00:00Z")
    assert a.record_id() == b.record_id()                   # deterministic


def test_provenance_requires_injected_timestamp():
    with pytest.raises(ProvenanceError):
        ExperimentRecord.build("x", dataset_id="d", parameters={}, config={}, timestamp=None)


def test_git_head_readable():
    assert git_head() is not None and len(git_head()) >= 7


def test_parameter_study_and_replay():
    df = _df(30)
    grid = [{"a": 1}, {"a": 2}]
    ps = parameter_study(lambda params: _StubEngine(), df, "EURUSD.FX", grid, window=10, step=10)
    assert len(ps) == 2
    assert historical_replay(_StubEngine(), df, "EURUSD.FX")["bars"] == 30


# --------------------------------------------------------------------------- #
# ACCEPTANCE: isolation / ownership / authority / no networking / no duplication
# --------------------------------------------------------------------------- #
def test_production_does_not_import_research():
    offenders = []
    for py in PKG.rglob("*.py"):
        if "/research/" in str(py).replace("\\", "/") or "__pycache__" in str(py):
            continue
        src = py.read_text(encoding="utf-8")
        if "import research" in src or "from ..research" in src or "from .research" in src \
                or "forex_swing_orb.research" in src:
            offenders.append(str(py.relative_to(PKG)))
    assert offenders == [], f"production imports research: {offenders}"


def test_production_entrypoints_import_without_research():
    # deleting research would not break production: its entry points import cleanly
    import importlib
    for mod in ("forex_swing_orb.producer.service", "forex_swing_orb.manage.service",
                "forex_swing_orb.compliance", "forex_swing_orb.bridge"):
        assert importlib.import_module(mod) is not None


def test_research_has_zero_trade_authority():
    import forex_swing_orb.research as R
    forbidden = ("write_instruction(", "order_send(", "position_close(", "modify_stop(",
                 "import socket", "import urllib", "import requests", "http.client",
                 "import subprocess", "subprocess.", "MetaTrader5", "create_real_client",
                 "os.system(")
    for name in ("portfolio", "execution_analytics", "reporting", "walk_forward",
                 "montecarlo", "experiments", "provenance"):
        mod = getattr(__import__(f"forex_swing_orb.research.{name}", fromlist=[name]), "__name__")
        src = inspect.getsource(__import__(f"forex_swing_orb.research.{name}", fromlist=[name]))
        for tok in forbidden:
            assert tok not in src, f"{name}: forbidden token {tok}"


def test_no_duplicated_ownership():
    # research must not redefine strategy/compliance/FTMO/PM ownership functions
    import forex_swing_orb.research as R
    for name in ("portfolio", "execution_analytics", "reporting", "walk_forward",
                 "montecarlo", "experiments", "provenance"):
        src = inspect.getsource(__import__(f"forex_swing_orb.research.{name}", fromlist=[name]))
        for tok in ("def confirmed_pivots", "def gate_ftmo", "def ftmo_levels(",
                    "def gate_session", "class SignalEngine", "def initial_risk"):
            assert tok not in src, f"{name} re-defines owner: {tok}"
