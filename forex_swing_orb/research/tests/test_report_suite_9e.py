"""PR-9E — reproducible research REPORT SUITE (orchestration only).

Proves the suite (a) emits every named Section-Z artifact, (b) degrades HONESTLY to an
explicit status on an empty / insufficient dataset (never fabricates edge), (c) is
deterministic and reproducible (same inputs -> same dataset hash + output), (d) stamps
every report with reproducibility metadata, (e) delegates to the existing single owners
(introduces no new metric math), and (f) has ZERO trading authority. Deterministic.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from forex_swing_orb.agents.memory import MemoryStore
from forex_swing_orb.research import report_suite, lifecycle, portfolio

REPO = Path(__file__).resolve().parents[3]
PKG = REPO / "forex_swing_orb"
TS = "2026-08-19T00:00:00Z"

NAMED_REPORTS = ("research_dataset", "baseline_report", "feature_report",
                 "session_report", "symbol_report", "walk_forward_report",
                 "robustness_report", "drawdown_report", "monte_carlo_report",
                 "calibration_report")


def _mem(tmp_path):
    return MemoryStore(tmp_path / "memory")


def _outcome(sid, r_multiple=1.0, symbol="EURUSD.FX", direction="LONG",
             taken=True, status="CLOSED"):
    won = (r_multiple > 0) if isinstance(r_multiple, (int, float)) else None
    return {"schema_version": 1, "signal_id": sid, "status": status, "won": won,
            "taken": taken, "r_multiple": r_multiple, "direction": direction,
            "symbol": symbol, "ticket": 1, "broker_order_id": 1, "entry": 1.10000,
            "initial_stop": 1.09800, "weighted_close": 1.10400, "closed_volume": 0.10,
            "deal_count": 1, "realized_r_source": "mt5_deal_history"}


def _write(mem, content, ts="2026-01-05T12:00:00Z"):
    mem.write_raw(lifecycle.OUTCOME_KIND, content["symbol"], content,
                  source="outcome_reconciler", timestamp=ts,
                  correlation_id=content["signal_id"])


def _sid(i):
    return hashlib.sha256(str(i).encode()).hexdigest()[:16]


def _seed_closed(mem, n, rs=None):
    for i in range(n):
        r = rs[i] if rs is not None else (1.0 if i % 2 else -1.0)
        _write(mem, _outcome(_sid(i), r_multiple=r,
                             symbol=("EURUSD.FX" if i % 2 else "GBPUSD.FX")),
               ts=f"2026-01-{(i % 27) + 1:02d}T10:00:00Z")


# --------------------------------------------------------------------------- #
# structure + honest degradation
# --------------------------------------------------------------------------- #
def test_emits_every_named_report_on_empty():
    s = report_suite.build([], None, timestamp=TS)
    for name in NAMED_REPORTS:
        assert name in s, f"missing report: {name}"


def test_empty_dataset_degrades_honestly():
    s = report_suite.build([], None, timestamp=TS)
    assert s["baseline_report"]["status"] == report_suite.NO_REALIZED
    assert s["session_report"]["status"] == report_suite.NO_REALIZED
    assert s["symbol_report"]["status"] == report_suite.NO_REALIZED
    assert s["drawdown_report"]["status"] == report_suite.NO_REALIZED
    assert s["monte_carlo_report"]["status"] == report_suite.INSUFFICIENT
    assert s["robustness_report"]["status"] == report_suite.INSUFFICIENT
    assert s["walk_forward_report"]["status"] == report_suite.UNAVAILABLE
    # calibration report falls to the D decision on an empty realized dataset
    assert "NO REALIZED DATASET" in s["calibration_report"]["decision"]


def test_reproducibility_metadata_present():
    s = report_suite.build([], None, timestamp=TS, sessions=["LONDON"], symbols=["EURUSD.FX"])
    p = s["provenance"]
    for k in ("suite_version", "dataset_hash", "strategy_version", "code_commit",
              "timestamp", "sessions", "symbols", "sample_rows", "sample_closed", "seed"):
        assert k in p
    assert p["timestamp"] == TS and p["sessions"] == ["LONDON"]


def test_deterministic_same_inputs_same_hash(tmp_path):
    m = _mem(tmp_path); _seed_closed(m, 10)
    a = report_suite.build([], m, timestamp=TS)
    b = report_suite.build([], m, timestamp=TS)
    assert a["research_dataset"]["dataset_hash"] == b["research_dataset"]["dataset_hash"]
    assert a["baseline_report"] == b["baseline_report"]


# --------------------------------------------------------------------------- #
# OK-path with realized data (delegation + denominators)
# --------------------------------------------------------------------------- #
def test_baseline_uses_canonical_portfolio_summary(tmp_path):
    m = _mem(tmp_path)
    rs = [2.0, -1.0, 1.0, -1.0, 3.0]
    _seed_closed(m, 5, rs=rs)
    s = report_suite.build([], m, timestamp=TS)
    closed = lifecycle.load_closed_trades(m)
    assert s["baseline_report"]["status"] == "OK"
    # exact equality with the canonical single owner (no re-derived math)
    assert s["baseline_report"]["overall"] == portfolio.summary(closed)


def test_denominators_distinguish_candidates_from_closed(tmp_path):
    m = _mem(tmp_path); _seed_closed(m, 4)
    # 3 authorized instructions, only some closed -> candidate vs closed are distinct
    instrs = [{"schema_version": 3, "signal_id": _sid(i), "session_id": "LONDON",
               "strategy_id": "forex_swing_orb", "strategy_version": "swing_orb.v1.4.0",
               "symbol": "EURUSD.FX", "direction": "LONG", "entry_price": 1.106,
               "stop_loss": 1.104, "take_profit": 1.110, "risk_fraction": 0.0025,
               "volume": 0.10, "generated_timestamp": "2026-01-05T09:15:00Z",
               "evidence_summary": {"range_high": 1.105, "range_low": 1.100, "atr14": 0.004,
                                    "boundary": 1.105, "retest_extreme": 1.1045}}
              for i in range(3)]
    s = report_suite.build(instrs, m, timestamp=TS)
    rd = s["research_dataset"]
    assert rd["candidate_observations"] == rd["row_count"]      # authorized observations
    assert rd["closed_trades"] == 4                             # realized subset
    assert rd["closed_trades"] != rd["candidate_observations"]  # denominators differ


def test_monte_carlo_runs_with_enough_realized(tmp_path):
    m = _mem(tmp_path); _seed_closed(m, 40)     # >= MONTE_CARLO_MIN (30)
    s = report_suite.build([], m, timestamp=TS, mc_sims=200, seed=7)
    assert s["monte_carlo_report"]["status"] == "OK"
    assert s["monte_carlo_report"]["n_trades"] == 40
    # seeded -> deterministic
    s2 = report_suite.build([], m, timestamp=TS, mc_sims=200, seed=7)
    assert s["monte_carlo_report"]["result"] == s2["monte_carlo_report"]["result"]


def test_drawdown_report_has_duration_and_rolling(tmp_path):
    m = _mem(tmp_path); _seed_closed(m, 25, rs=[1.0, -2.0, -1.0, 3.0, -1.0] * 5)
    s = report_suite.build([], m, timestamp=TS, rolling_window=5)
    dd = s["drawdown_report"]
    assert dd["status"] == "OK"
    assert "max_drawdown_duration" in dd and isinstance(dd["rolling_expectancy"], list)


# --------------------------------------------------------------------------- #
# artifacts on disk (outputs only)
# --------------------------------------------------------------------------- #
def test_write_suite_emits_named_json_files(tmp_path):
    s = report_suite.build([], None, timestamp=TS)
    written = report_suite.write_suite(tmp_path / "out", s)
    names = {Path(w).stem for w in written}
    for name in NAMED_REPORTS:
        assert name in names
        assert (tmp_path / "out" / f"{name}.json").exists()
