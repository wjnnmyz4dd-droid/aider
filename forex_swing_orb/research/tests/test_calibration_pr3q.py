"""PR-3Q — quality-factor validation & score-model calibration (RESEARCH ONLY).

Proves the calibration machinery is correct, deterministic, leakage-free, and
non-duplicative; that it reuses the single owners (quality_facts extractor,
manage.outcome realized R via lifecycle join, portfolio calculators, cohort_of,
compliance sizing); and that it creates NO live trade score, NO live 70 gate, and
NO score/risk/lot coupling. Synthetic fixtures here exercise MATH ONLY and are
never presented as evidence of predictive power (PR-3Q §AB).

Numbered tests map to the PR-3Q required-test batteries (AJ dataset, AK leakage,
AL analytics, AM threshold, AN authority).
"""

from __future__ import annotations

import copy
import re
from pathlib import Path

import pytest

from forex_swing_orb.agents.memory import MemoryStore
from forex_swing_orb.research import calibration as C
from forex_swing_orb.research import lifecycle, portfolio, quality_facts

REPO = Path(__file__).resolve().parents[3]
PKG = REPO / "forex_swing_orb"
ATR = 0.00100
QFV = quality_facts.QUALITY_FACT_VERSION
TS = "2026-08-14T00:00:00Z"


# --------------------------------------------------------------------------- #
# fixtures — SYNTHETIC (math only; never evidence of edge)
# --------------------------------------------------------------------------- #
def _instr(sid, *, confirm=1.10600, rhigh=1.10500, atr14=ATR, minor=1.10550,
           ts="2026-01-05T09:15:00Z", symbol="EURUSD.FX", session="LONDON",
           direction="LONG"):
    ev = {"trend_d1": "BULLISH", "trend_h4": "BULLISH", "range_high": rhigh,
          "range_low": 1.10000, "atr14": atr14, "boundary": 1.10500,
          "retest_extreme": 1.10450, "minor_swing_ref": minor,
          "confirm_close": confirm, "stop_basis": 1.10400, "rr_planned": 2.0}
    return {"schema_version": 3, "signal_id": sid, "session_id": session,
            "strategy_id": "forex_swing_orb", "strategy_version": "swing_orb.v1.4.0",
            "symbol": symbol, "direction": direction, "entry_price": confirm,
            "stop_loss": 1.10400, "take_profit": 1.11000, "risk_fraction": 0.0025,
            "volume": 0.10, "generated_timestamp": ts, "evidence_summary": ev}


def _mem(tmp_path):
    return MemoryStore(tmp_path / "memory")


def _write_outcome(m, sid, r_multiple, *, taken=True, status="CLOSED",
                   weighted_close=1.11000, symbol="EURUSD.FX", ts="2026-01-05T12:00:00Z"):
    won = (r_multiple > 0) if isinstance(r_multiple, (int, float)) else None
    c = {"schema_version": 1, "signal_id": sid, "status": status, "won": won,
         "taken": taken, "r_multiple": r_multiple, "direction": "LONG", "symbol": symbol,
         "ticket": 1, "broker_order_id": 1, "entry": 1.10600, "initial_stop": 1.10400,
         "weighted_close": weighted_close, "closed_volume": 0.10, "deal_count": 1,
         "realized_r_source": "mt5_deal_history"}
    m.write_raw("execution_outcome", symbol, c, source="outcome_reconciler",
                timestamp=ts, correlation_id=sid)


def _sid(i):
    return f"{i:016x}"


def _closed_corpus(tmp_path, n=40):
    """n instructions whose range_width increases with i, with a SYNTHETIC realized
    R that increases with i (positive monotone) — for exercising analytics math."""
    m = _mem(tmp_path)
    instrs = []
    for i in range(n):
        sid = _sid(i)
        rhigh = 1.10300 + i * 0.00002        # widening OR -> varying range_width
        instrs.append(_instr(sid, rhigh=rhigh,
                             ts=f"2026-01-{1 + i // 5:02d}T09:{i % 60:02d}:00Z"))
        _write_outcome(m, sid, r_multiple=round(-1.0 + i * 0.1, 4))
    return instrs, m


def _row(sid, *, score=None, r=1.0, closed=True, qfv=QFV, symbol="EURUSD.FX",
         session="LONDON", direction="LONG", ts="2026-01-05T09:15:00Z", **facts):
    base = {"signal_id": sid, "quality_fact_version": qfv, "closed": closed,
            "outcome_r": r, "trade_score": score, "symbol": symbol,
            "session_id": session, "direction": direction, "generated_timestamp": ts}
    for f in quality_facts.CONTINUOUS_FACTS:
        base.setdefault(f, 1.0)
    base.update(facts)
    return base


# --------------------------------------------------------------------------- #
# AJ — dataset (1-10)
# --------------------------------------------------------------------------- #
def test_01_one_signal_id_counted_once(tmp_path):
    m = _mem(tmp_path); _write_outcome(m, _sid(1), 2.0)
    ds = C.build_dataset([_instr(_sid(1)), _instr(_sid(1))], memory=m)   # dup signal
    assert [r["signal_id"] for r in ds] == [_sid(1)]


def test_02_replay_does_not_double_count(tmp_path):
    m = _mem(tmp_path); _write_outcome(m, _sid(2), 1.5)
    a = C.build_dataset([_instr(_sid(2))], memory=m)
    b = C.build_dataset([_instr(_sid(2))], memory=m)
    assert a == b and len(a) == 1


def test_03_rejected_candidate_excluded_from_realized_r(tmp_path):
    m = _mem(tmp_path)                          # no outcome written -> candidate only
    ds = C.build_dataset([_instr(_sid(3))], memory=m)
    assert ds[0]["closed"] is False and ds[0]["outcome_r"] is None
    assert C.closed_rows(ds) == []


def test_04_held_excluded_from_realized_r(tmp_path):
    m = _mem(tmp_path)
    _write_outcome(m, _sid(4), 1.0, taken=False, status="HELD")   # not taken
    ds = C.build_dataset([_instr(_sid(4))], memory=m)
    assert C.closed_rows(ds) == []             # non-executed never a closed trade


def test_05_open_trade_excluded_from_realized_r(tmp_path):
    m = _mem(tmp_path)                          # position still open -> no outcome fact
    ds = C.build_dataset([_instr(_sid(5))], memory=m)
    assert C.closed_rows(ds) == []


def test_06_closed_trade_joined_once(tmp_path):
    m = _mem(tmp_path); _write_outcome(m, _sid(6), -1.0)
    ds = C.build_dataset([_instr(_sid(6))], memory=m)
    cr = C.closed_rows(ds)
    assert len(cr) == 1 and cr[0]["outcome_r"] == -1.0 and cr[0]["closed"] is True


def test_07_missing_r_remains_missing_not_zero(tmp_path):
    m = _mem(tmp_path)
    _write_outcome(m, _sid(7), None, status="R_UNDEFINED")   # zero-risk edge: R undefined
    ds = C.build_dataset([_instr(_sid(7))], memory=m)
    assert ds[0]["outcome_r"] is None          # NEVER fabricated to 0.0
    assert C.closed_rows(ds) == []             # excluded from predictive analysis


def test_08_missing_quality_fact_remains_missing(tmp_path):
    m = _mem(tmp_path); _write_outcome(m, _sid(8), 1.0)
    ds = C.build_dataset([_instr(_sid(8), atr14=None)], memory=m)
    assert ds[0]["range_width_atr"] is None and ds[0]["stop_distance_atr"] is None


def test_09_incompatible_version_not_silently_pooled():
    rows = [_row(_sid(1), r=2.0, qfv="session_edge_quality.v1"),
            _row(_sid(2), r=1.0, qfv="session_edge_quality.v2")]
    assert C.version_distribution(rows) == {"session_edge_quality.v1": 1,
                                            "session_edge_quality.v2": 1}
    only_v1 = C.closed_rows(rows, quality_fact_version="session_edge_quality.v1")
    assert [r["signal_id"] for r in only_v1] == [_sid(1)]   # v2 not pooled in


def test_09b_report_flags_multiple_versions(monkeypatch):
    mixed = [_row(_sid(1), r=2.0, qfv="session_edge_quality.v1"),
             _row(_sid(2), r=1.0, qfv="session_edge_quality.v2")]
    monkeypatch.setattr(C, "build_dataset", lambda *a, **k: mixed)
    rep = C.calibration_report([], timestamp=TS)
    assert rep["dataset_summary"]["version_mixing"] == "MULTIPLE_VERSIONS_NOT_POOLED"
    assert rep["feature_distributions"] == {}      # analysis skipped, not pooled


def test_10_deterministic_dataset_ordering(tmp_path):
    m = _mem(tmp_path)
    for i in (5, 1, 3):
        _write_outcome(m, _sid(i), 1.0)
    ds = C.build_dataset([_instr(_sid(i)) for i in (5, 1, 3)], memory=m)
    assert [r["signal_id"] for r in ds] == [_sid(1), _sid(3), _sid(5)]


# --------------------------------------------------------------------------- #
# AK — leakage (11-15)
# --------------------------------------------------------------------------- #
def test_11_quality_facts_independent_of_exit_outcome():
    q = quality_facts.extract(_instr(_sid(1)))
    for leaky in ("outcome_r", "r_multiple", "weighted_close", "won", "exit_price",
                  "mae", "mfe", "closed", "realized_pnl"):
        assert leaky not in q


def test_12_changing_realized_r_does_not_change_quality_facts(tmp_path):
    m1 = _mem(tmp_path / "a"); _write_outcome(m1, _sid(1), 3.0)
    m2 = _mem(tmp_path / "b"); _write_outcome(m2, _sid(1), -1.0)
    r1 = C.build_dataset([_instr(_sid(1))], memory=m1)[0]
    r2 = C.build_dataset([_instr(_sid(1))], memory=m2)[0]
    for k in quality_facts.CONTINUOUS_FACTS:
        assert r1[k] == r2[k]                  # facts identical; only outcome_r differs
    assert r1["outcome_r"] == 3.0 and r2["outcome_r"] == -1.0


def test_13_changing_exit_price_does_not_change_authorization_facts(tmp_path):
    m1 = _mem(tmp_path / "a"); _write_outcome(m1, _sid(1), 1.0, weighted_close=1.12000)
    m2 = _mem(tmp_path / "b"); _write_outcome(m2, _sid(1), 1.0, weighted_close=1.09000)
    r1 = C.build_dataset([_instr(_sid(1))], memory=m1)[0]
    r2 = C.build_dataset([_instr(_sid(1))], memory=m2)[0]
    for k in quality_facts.CONTINUOUS_FACTS:
        assert r1[k] == r2[k]


def test_14_post_entry_bars_unavailable_to_extractor():
    # the extractor imports/calls nothing that could read future/post-entry bars
    src = (PKG / "research" / "quality_facts.py").read_text()
    for banned in ("get_bars", "signal_engine", ".iloc", "load_engine", ".generate(",
                   "strategy_adapter", "import producer"):
        assert banned not in src


def test_15_management_result_unavailable_to_extractor():
    # injecting management/exit results into the instruction does NOT change facts,
    # and no management/exit field is ever surfaced by the extractor (behavioral).
    base = _instr(_sid(1))
    poisoned = dict(base)
    poisoned.update({"weighted_close": 1.20000, "r_multiple": 9.0, "mfe": 5.0,
                     "mae": -3.0, "exit_price": 1.19000, "trailing_stop": 1.10500})
    assert quality_facts.extract(poisoned) == quality_facts.extract(base)
    for leaky in ("weighted_close", "r_multiple", "mfe", "mae", "exit_price",
                  "trailing_stop", "bars_held", "outcome_r"):
        assert leaky not in quality_facts.extract(base)


# --------------------------------------------------------------------------- #
# AL — analytics (16-24)
# --------------------------------------------------------------------------- #
def test_16_quantile_calculation_deterministic(tmp_path):
    instrs, m = _closed_corpus(tmp_path)
    ds = C.build_dataset(instrs, memory=m)
    a = C.univariate(ds, "range_width_atr")
    b = C.univariate(ds, "range_width_atr")
    assert a == b and a["status"] == "OK" and a["by_quantile"]


def test_17_pearson_deterministic():
    assert C.pearson([1, 2, 3, 4, 5], [2, 3, 5, 4, 8]) == C.pearson([1, 2, 3, 4, 5], [2, 3, 5, 4, 8])
    assert C.pearson([1, 2, 3, 4], [2, 4, 6, 8]) == pytest.approx(1.0)
    assert C.pearson([1, 2, 3, 4], [8, 6, 4, 2]) == pytest.approx(-1.0)


def test_18_spearman_deterministic():
    xs, ys = [1, 2, 3, 4, 5], [1, 4, 9, 16, 25]
    assert C.spearman(xs, ys) == C.spearman(xs, ys) == pytest.approx(1.0)   # rank-monotone


def test_19_missing_values_handled_explicitly():
    assert C.pearson([1, None, 3], [1, 2, 3]) is None       # <3 finite pairs after drop
    assert C.pearson([1, 2, 3, 4], [1, float("nan"), 3, 4]) is not None  # nan pair dropped


def test_20_constant_feature_handled_safely(tmp_path):
    instrs, m = _closed_corpus(tmp_path)
    # stop_distance_atr is constant across the corpus (entry/stop fixed) -> undefined corr
    ds = C.build_dataset(instrs, memory=m)
    uni = C.univariate(ds, "stop_distance_atr")
    assert uni["status"] == "OK" and uni["pearson_r"] is None      # no crash, no fabrication
    mono = C.monotonicity(ds, "stop_distance_atr")
    assert mono["classification"] == C.FLAT


def test_21_tiny_sample_returns_insufficient(tmp_path):
    m = _mem(tmp_path); _write_outcome(m, _sid(1), 1.0)
    ds = C.build_dataset([_instr(_sid(1))], memory=m)         # 1 closed trade
    assert C.univariate(ds, "range_width_atr")["status"] == C.INSUFFICIENT
    assert C.monotonicity(ds, "range_width_atr")["classification"] == C.INSUFFICIENT


def test_22_outlier_removal_robustness_deterministic(tmp_path):
    instrs, m = _closed_corpus(tmp_path)
    ds = C.build_dataset(instrs, memory=m)
    assert C.robustness(ds, "range_width_atr") == C.robustness(ds, "range_width_atr")


def test_23_chronological_split_never_randomizes(tmp_path):
    instrs, m = _closed_corpus(tmp_path)
    ds = C.build_dataset(instrs, memory=m)
    early, late = C.chronological_split(ds, 0.7)
    shuffled = list(reversed(ds))
    early2, late2 = C.chronological_split(shuffled, 0.7)
    assert [r["signal_id"] for r in early] == [r["signal_id"] for r in early2]   # order-independent
    assert len(early) + len(late) == len(C.closed_rows(ds))


def test_24_no_future_observation_leaks_into_earlier_window(tmp_path):
    instrs, m = _closed_corpus(tmp_path)
    ds = C.build_dataset(instrs, memory=m)
    early, late = C.chronological_split(ds, 0.6)
    assert early and late
    max_early = max(r["generated_timestamp"] for r in early)
    min_late = min(r["generated_timestamp"] for r in late)
    assert max_early <= min_late                 # strict chronological boundary


# --------------------------------------------------------------------------- #
# AM — threshold retrospective (25-30). A live score does NOT exist; these prove
# the retrospective MACHINERY is correct and creates no live gate.
# --------------------------------------------------------------------------- #
def _scored_rows():
    return [_row(_sid(i), score=s, r=r) for i, (s, r) in enumerate(
        [(60, -1.0), (69, -0.5), (70, 1.0), (75, 2.0), (95, 3.0)])]


def test_25_retrospective_70_filter_deterministic():
    rows = _scored_rows()
    assert C.threshold_retrospective(rows) == C.threshold_retrospective(rows)


def test_26_score_exactly_70_retained():
    rows = [_row(_sid(1), score=70, r=1.0)]
    res = C.threshold_retrospective(rows)
    assert res["retained"] == 1 and res["removed"] == 0    # >= 70 retained


def test_27_below_70_filtered_observationally():
    rows = [_row(_sid(1), score=69, r=1.0)]
    res = C.threshold_retrospective(rows)
    assert res["retained"] == 0 and res["removed"] == 1


def test_28_no_live_gate_created_on_scoreless_data(tmp_path):
    m = _mem(tmp_path); _write_outcome(m, _sid(1), 1.0)
    ds = C.build_dataset([_instr(_sid(1))], memory=m)        # trade_score is None
    assert C.threshold_retrospective(ds)["status"] == lifecycle.SCORE_UNAVAILABLE


def test_29_canonical_portfolio_metrics_reused():
    res = C.threshold_retrospective(_scored_rows())
    assert set(res["retained_metrics"].keys()) == set(
        portfolio.summary([{"r_multiple": 1.0}]).keys())


def test_30_threshold_analysis_does_not_modify_original():
    rows = _scored_rows()
    snapshot = copy.deepcopy(rows)
    C.threshold_retrospective(rows)
    assert rows == snapshot


# --------------------------------------------------------------------------- #
# AN — authority (31-40)
# --------------------------------------------------------------------------- #
def _def_owners(func_sig):
    return [p for p in PKG.rglob("*.py")
            if "/tests/" not in str(p) and re.search(func_sig, p.read_text(), re.M)]


def test_31_exactly_one_quality_fact_extractor():
    # the quality-fact version constant is defined in exactly one module
    owners = _def_owners(r"^QUALITY_FACT_VERSION\s*=")
    assert owners == [PKG / "research" / "quality_facts.py"]


def test_32_exactly_one_realized_r_owner():
    owners = _def_owners(r"^\s*def _realized_r\(")
    assert owners == [PKG / "manage" / "outcome.py"]
    # calibration never recomputes R from prices
    src = (PKG / "research" / "calibration.py").read_text()
    assert "weighted_close" not in src and "initial_stop" not in src


def test_33_exactly_one_portfolio_metric_owner():
    assert _def_owners(r"^def expectancy\(") == [PKG / "research" / "portfolio.py"]
    assert _def_owners(r"^def profit_factor\(") == [PKG / "research" / "portfolio.py"]


def test_34_exactly_one_cohort_classifier():
    assert _def_owners(r"^def cohort_of\(") == [PKG / "research" / "lifecycle.py"]


def test_35_exactly_one_lot_size_authority():
    assert _def_owners(r"^def allowable_volume\(") == [PKG / "compliance" / "sizing.py"]


def test_36_zero_production_score_calculators():
    # no proposed model is produced without evidence; nothing computes a live score
    rep = C.calibration_report([], timestamp=TS)
    assert rep["proposed_score_model"] is None
    src = (PKG / "research" / "calibration.py").read_text()
    assert "def score(" not in src and "trade_score =" not in src


def test_37_zero_live_score_thresholds():
    # the 70 constant lives only as a research constant, never wired into sizing/gates
    trading = ("bridge", "compliance", "position", "producer", "ea_mt5", "manage",
               "runtime", "session", "live")
    for pkg in trading:
        for p in (PKG / pkg).rglob("*.py"):
            if "/tests/" in str(p):
                continue
            txt = p.read_text()
            assert "SCORE_MIN_QUALIFYING" not in txt
            assert "trade_score" not in txt


def test_38_no_trading_module_imports_calibration_or_research():
    trading = ("bridge", "compliance", "ea_mt5", "manage", "position", "producer",
               "runtime", "session", "live")
    offenders = []
    for pkg in trading:
        for p in (PKG / pkg).rglob("*.py"):
            if "/tests/" in str(p):
                continue
            if re.search(r"import\s+.*\bresearch\b|from\s+.*research|calibration", p.read_text()):
                offenders.append(str(p.relative_to(PKG)))
    assert offenders == []


def test_39_research_cannot_send_orders():
    src = (PKG / "research" / "calibration.py").read_text()
    for banned in ("order_send", "OrderSend", "place_order", "write_instruction",
                   "bridge.enter", "position_manager", "socket", "requests", "http"):
        assert banned not in src


def test_40_ea_contains_no_score_logic():
    ea = (PKG / "ea_mt5" / "SessionEdgeExecutionEA.mq5").read_text().lower()
    assert "score" not in ea and "quality_fact" not in ea


# --------------------------------------------------------------------------- #
# decision + no-authority end-to-end
# --------------------------------------------------------------------------- #
def test_decision_D_on_empty_dataset():
    rep = C.calibration_report([], timestamp=TS)
    assert rep["decision"] == C.DECISION_D
    assert rep["higher_score_better"] == lifecycle.SCORE_UNAVAILABLE


def test_decision_never_forced_A_without_survival():
    # even a CALIBRATION-CANDIDATE count decides C (not A) unless a model survives
    assert C.decide(500, C.CALIBRATION_CANDIDATE, model_survives=False) == C.DECISION_C
    assert C.decide(50, C.EXPLORATORY) == C.DECISION_B
    assert C.decide(0, C.INSUFFICIENT) == C.DECISION_D


def test_report_is_deterministic(tmp_path):
    instrs, m = _closed_corpus(tmp_path)
    a = C.calibration_report(instrs, memory=m, timestamp=TS)
    b = C.calibration_report(instrs, memory=m, timestamp=TS)
    assert a == b


def test_cohort_performance_all_unavailable_without_score(tmp_path):
    instrs, m = _closed_corpus(tmp_path)
    ds = C.build_dataset(instrs, memory=m)
    perf = C.cohort_performance(ds)
    assert list(perf.keys()) == [lifecycle.SCORE_UNAVAILABLE]   # no scored cohorts exist
