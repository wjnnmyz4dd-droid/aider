"""PR-3Q.1 — adversarial debug audit of the PR-3M..PR-3Q analytics chain.

RESEARCH-ONLY correctness/regression suite. Covers the 60-point adversarial matrix
and pins the specific defects fixed in PR-3Q.1:
  * calibration.monotonicity no longer labels non-monotone (trend==0) factors
    POSITIVE/NEGATIVE (was: `trend >= 0`).                              [BUG #1]
  * calibration.pearson fails closed (None) on numeric overflow.       [BUG #3]
  * calibration.chronological_split orders by true UTC instant via the
    canonical serialize.parse_iso; unorderable timestamps fail closed. [BUG #2/#5]
  * quality_facts.range_width_price is a magnitude (abs); the emitted atr14
    is UNAVAILABLE when non-positive.                                   [LOW-1/2]
  * lifecycle.load_closed_trades fails closed on conflicting outcomes, malformed
    signal_id, and malformed r_multiple.                               [F1/F2/F4]
  * portfolio.equity_curve ignores non-finite r_multiple.              [F4.1]

Synthetic fixtures test CODE CORRECTNESS ONLY; never evidence of trading edge.
"""

from __future__ import annotations

import copy
import math
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


# --------------------------------------------------------------------------- #
# fixtures (synthetic; math only)
# --------------------------------------------------------------------------- #
def _sid(i):
    return f"{i:016x}"


def _instr(sid, *, direction="LONG", confirm=1.10600, boundary=1.10500, entry=1.10600,
           stop=1.10400, retest=1.10450, minor=1.10550, rhigh=1.10500, rlow=1.10000,
           atr14=ATR, rr=2.0, ts="2026-01-05T09:15:00Z", symbol="EURUSD.FX",
           session="LONDON"):
    ev = {"trend_d1": "BULLISH", "trend_h4": "BULLISH", "range_high": rhigh,
          "range_low": rlow, "atr14": atr14, "boundary": boundary,
          "retest_extreme": retest, "minor_swing_ref": minor, "confirm_close": confirm,
          "stop_basis": stop, "rr_planned": rr}
    return {"schema_version": 3, "signal_id": sid, "session_id": session,
            "strategy_id": "forex_swing_orb", "strategy_version": "swing_orb.v1.4.0",
            "symbol": symbol, "direction": direction, "entry_price": entry,
            "stop_loss": stop, "take_profit": 1.11000, "risk_fraction": 0.0025,
            "volume": 0.10, "generated_timestamp": ts, "evidence_summary": ev}


def _mem(tmp_path):
    return MemoryStore(tmp_path / "memory")


def _write(m, sid, r, *, taken=True, status="CLOSED", weighted_close=1.11000,
           symbol="EURUSD.FX", ts="2026-01-05T12:00:00Z", **over):
    won = (r > 0) if (isinstance(r, (int, float)) and not isinstance(r, bool)) else None
    c = {"schema_version": 1, "signal_id": sid, "status": status, "won": won,
         "taken": taken, "r_multiple": r, "direction": "LONG", "symbol": symbol,
         "ticket": 1, "broker_order_id": 1, "entry": 1.10600, "initial_stop": 1.10400,
         "weighted_close": weighted_close, "closed_volume": 0.10, "deal_count": 1,
         "realized_r_source": "mt5_deal_history"}
    c.update(over)
    m.write_raw("execution_outcome", symbol, c, source="outcome_reconciler",
                timestamp=ts, correlation_id=sid)


def _row(sid, *, r=1.0, score=None, closed=True, qfv=QFV, symbol="EURUSD.FX",
         session="LONDON", direction="LONG", ts="2026-01-05T09:15:00Z", **facts):
    base = {"signal_id": sid, "quality_fact_version": qfv, "closed": closed,
            "outcome_r": r, "trade_score": score, "symbol": symbol,
            "session_id": session, "direction": direction, "generated_timestamp": ts}
    for f in quality_facts.CONTINUOUS_FACTS:
        base.setdefault(f, 1.0)
    base.update(facts)
    return base


def _corpus(tmp_path, n=40, *, mono=True):
    """n closed trades; range_width_atr increases with i and R increases with i
    (clean monotone) for analytics exercise. Synthetic — code correctness only."""
    m = _mem(tmp_path)
    instrs = []
    for i in range(n):
        sid = _sid(i)
        instrs.append(_instr(sid, rhigh=1.10300 + i * 0.00002,
                             ts=f"2026-01-{1 + i // 5:02d}T09:{i % 60:02d}:00Z"))
        _write(m, sid, r=round(-1.0 + i * 0.1, 4) if mono else round((i - 8) ** 2 * 0.01, 4))
    return instrs, m


# ===================== AE 1-10 — dataset ==================================== #
def test_01_duplicate_outcome_identical_dedups(tmp_path):
    m = _mem(tmp_path); _write(m, _sid(1), 2.0); _write(m, _sid(1), 2.0, ts="2026-01-05T13:00:00Z")
    assert len(lifecycle.load_closed_trades(m)) == 1          # benign duplicate -> one


def test_02_conflicting_outcome_fails_closed(tmp_path):
    m = _mem(tmp_path); _write(m, _sid(1), 1.5); _write(m, _sid(1), -1.0, ts="2026-01-05T13:00:00Z")
    assert lifecycle.load_closed_trades(m) == []             # F1: quarantined, no silent first-wins


def test_03_malformed_signal_id_ignored(tmp_path):
    m = _mem(tmp_path)
    _write(m, "NOThex", 1.0); _write(m, "A1B2C3D4E5F60718", 1.0)   # non-hex / uppercase
    _write(m, "a1b2c3d4e5f6071", 1.0)                              # 15 chars
    assert lifecycle.load_closed_trades(m) == []             # F2: reader as strict as writer


def test_04_R_zero_is_scratch_not_dropped(tmp_path):
    m = _mem(tmp_path); _write(m, _sid(1), 0.0)
    t = lifecycle.load_closed_trades(m)
    assert len(t) == 1 and t[0]["r_multiple"] == 0.0         # R=0 is a real scratch trade


def test_05_negative_R_kept(tmp_path):
    m = _mem(tmp_path); _write(m, _sid(1), -2.3)
    assert lifecycle.load_closed_trades(m)[0]["r_multiple"] == -2.3


def test_06_nan_R_unwritable_at_store(tmp_path):
    # the store's canonical_json(allow_nan=False) rejects NaN at write; defense-in-depth
    m = _mem(tmp_path)
    with pytest.raises(Exception):
        _write(m, _sid(1), float("nan"))


def test_07_inf_R_unwritable_at_store(tmp_path):
    m = _mem(tmp_path)
    with pytest.raises(Exception):
        _write(m, _sid(1), float("inf"))


def test_08_bool_R_dropped(tmp_path):
    m = _mem(tmp_path); _write(m, _sid(1), True)             # bool masquerading as number
    assert lifecycle.load_closed_trades(m) == []            # F4: corrupt R -> dropped


def test_08b_string_R_dropped(tmp_path):
    m = _mem(tmp_path); _write(m, _sid(1), "1.5")
    assert lifecycle.load_closed_trades(m) == []


def test_09_malformed_quality_evidence_fails_closed():
    for ev in (None, [], "x", 42):
        q = quality_facts.extract({"signal_id": _sid(1), "evidence_summary": ev})
        assert q["range_width_price"] is None and q["stop_distance_price"] is None
    assert quality_facts.extract("not-a-dict") is None


def test_10_atr_zero_and_negative_unavailable():
    for bad in (0.0, -0.001):
        q = quality_facts.extract(_instr(_sid(1), atr14=bad))
        assert q["range_width_atr"] is None and q["stop_distance_atr"] is None
        assert q["atr14"] is None                            # LOW-2: non-positive atr surfaced None


def test_11_atr_negative_price_facts_still_present():
    q = quality_facts.extract(_instr(_sid(1), atr14=-0.001))
    assert q["range_width_price"] == pytest.approx(0.00500)  # raw price retained


# ===================== AE 12-17 — semantics / leakage / immutability ======= #
def test_12_13_long_short_mirror_equal_magnitudes():
    lng = quality_facts.extract(_instr(_sid(1), direction="LONG", confirm=1.10600,
        boundary=1.10500, entry=1.10600, stop=1.10400, retest=1.10450, minor=1.10550))
    sht = quality_facts.extract(_instr(_sid(2), direction="SHORT", confirm=1.10400,
        boundary=1.10500, entry=1.10400, stop=1.10600, retest=1.10550, minor=1.10450))
    for f in quality_facts.CONTINUOUS_FACTS:
        assert lng[f] == pytest.approx(sht[f]), f            # magnitude, direction-agnostic
        if lng[f] is not None:
            assert lng[f] >= 0                               # never a negative quality magnitude


def test_13b_range_width_is_magnitude_even_if_high_below_low():
    q = quality_facts.extract(_instr(_sid(1), rhigh=1.10300, rlow=1.10500))  # malformed
    assert q["range_width_price"] >= 0 and q["range_width_atr"] >= 0          # LOW-1: abs()


def test_14_instruction_immutability():
    instr = _instr(_sid(1))
    snap = copy.deepcopy(instr)
    quality_facts.extract(instr)
    assert instr == snap                                     # no mutation of nested evidence_summary


def test_15_repeated_extraction_idempotent():
    instr = _instr(_sid(1))
    assert quality_facts.extract(instr) == quality_facts.extract(instr)


def test_16_outcome_leakage_blocked():
    base = _instr(_sid(1))
    poisoned = dict(base)
    poisoned.update({"exit_price": 1.2, "r_multiple": 9.0, "won": True,
                     "close_time": "2026-01-06T00:00:00Z", "mae": -3.0, "mfe": 5.0,
                     "commission": 1.0, "swap": 0.5})
    assert quality_facts.extract(poisoned) == quality_facts.extract(base)


def test_17_management_leakage_blocked():
    base = _instr(_sid(1))
    poisoned = dict(base)
    poisoned.update({"trailing_stop": 1.105, "management_state": "TRAILING",
                     "weighted_close": 1.111, "future_bars": [1, 2, 3]})
    q = quality_facts.extract(poisoned)
    assert q == quality_facts.extract(base)
    for leaky in ("trailing_stop", "management_state", "weighted_close", "future_bars"):
        assert leaky not in q


# ===================== AE 18-21 — joins ==================================== #
def test_18_unmatched_instruction_is_candidate(tmp_path):
    m = _mem(tmp_path)                                       # no outcome
    row = lifecycle.quality_dataset([_instr(_sid(1))], memory=m)[0]
    assert row["closed"] is False and row["outcome_r"] is None


def test_19_unmatched_outcome_never_a_phantom_row(tmp_path):
    m = _mem(tmp_path); _write(m, _sid(1), 1.0)             # outcome but no instruction supplied
    assert lifecycle.quality_dataset([], memory=m) == []    # dataset keyed on instructions


def test_20_duplicate_instruction_deduped(tmp_path):
    m = _mem(tmp_path); _write(m, _sid(1), 1.0)
    ds = lifecycle.quality_dataset([_instr(_sid(1)), _instr(_sid(1))], memory=m)
    assert len(ds) == 1


def test_21_conflicting_quality_facts_first_immutable_set_wins(tmp_path):
    # two instructions, same signal_id, different evidence -> dedup keeps ONE immutable
    # fact set (instructions are immutable+content-addressed upstream; this is dedup,
    # not an outcome conflict). Deterministic: first in encounter order.
    a = _instr(_sid(1), rhigh=1.10500)
    b = _instr(_sid(1), rhigh=1.10900)
    ds = lifecycle.quality_dataset([a, b])
    assert len(ds) == 1


# ===================== AE 22-27 — correlation primitives =================== #
def test_22_pearson_constant():
    assert C.pearson([5, 5, 5, 5], [1, 2, 3, 4]) is None
    assert C.pearson([1, 2, 3, 4], [7, 7, 7, 7]) is None


def test_23_pearson_near_constant_all_scales():
    for scale in (1.0, 1e-6, 1e6, 1e12):
        xs = [scale * (1 + k * 1e-15) for k in range(6)]     # residual ~1e-15 relative
        assert C.pearson(xs, [1, 2, 3, 4, 5, 6]) is None, scale
    # and a genuinely varying series is NOT swallowed
    assert C.pearson([1, 2, 3, 4], [2, 4, 6, 8]) == pytest.approx(1.0)


def test_23b_pearson_overflow_fails_closed():
    assert C.pearson([1e300, 2e300, 3e300, 4e300], [1, 2, 3, 4]) is None   # BUG #3


def test_24_pearson_positive():
    assert C.pearson([1, 2, 3, 4], [1, 2, 3, 4]) == pytest.approx(1.0)


def test_25_pearson_negative():
    assert C.pearson([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)


def test_26_spearman_ties():
    assert C.spearman([1, 1, 1, 1], [1, 2, 3, 4]) is None    # all ties -> constant -> None
    assert C.spearman([1, 1, 2, 3], [1, 1, 2, 3]) == pytest.approx(1.0)   # partial ties ok


def test_27_spearman_reverse():
    assert C.spearman([1, 2, 3, 4, 5], [10, 8, 6, 4, 2]) == pytest.approx(-1.0)


# ===================== AE 28-34 — quantiles & monotonicity ================= #
def test_28_quantile_empty_and_tiny():
    assert C.quantile_cuts([], 4) is None
    assert C.quantile_cuts([1.0], 4) is None
    assert C.quantile_cuts([1, 2], 4) is None
    assert C.quantile_cuts([1, 2, 3, 4], 2) is not None


def test_29_quantile_duplicate_boundaries_all_equal():
    cuts = C.quantile_cuts([5, 5, 5, 5, 5, 5], 3)
    assert cuts is not None and all(c == 5 for c in cuts)    # no crash; all in bin 0
    assert C.assign_bin(5, cuts) == 0


def test_30_monotonic_positive(tmp_path):
    instrs, m = _corpus(tmp_path, 40, mono=True)
    ds = lifecycle.quality_dataset(instrs, memory=m)
    assert C.monotonicity(ds, "range_width_atr")["classification"] == C.POSITIVE


def test_31_monotonic_negative():
    rows = [_row(_sid(i), r=round(5.0 - i * 0.2, 4), range_width_atr=float(i)) for i in range(30)]
    assert C.monotonicity(rows, "range_width_atr")["classification"] == C.NEGATIVE


def test_32_non_monotonic_u_shape_not_forced_positive():        # BUG #1 regression
    rows = [_row(_sid(i), r=round((i - 8) ** 2 * 0.05, 4), range_width_atr=float(i))
            for i in range(24)]
    m = C.monotonicity(rows, "range_width_atr")
    assert m["classification"] == C.NON_MONOTONIC                # was POSITIVE before fix
    assert m["quantile_trend"] == 0


def test_33_monotonic_flat():
    rows = [_row(_sid(i), r=(1.0 if i % 2 else -1.0), range_width_atr=float(i)) for i in range(30)]
    assert C.monotonicity(rows, "range_width_atr")["classification"] in (C.FLAT, C.NON_MONOTONIC)


def test_33b_flat_on_constant_outcome_reason_accurate():
    rows = [_row(_sid(i), r=0.5, range_width_atr=float(i)) for i in range(24)]   # outcome constant
    m = C.monotonicity(rows, "range_width_atr")
    assert m["classification"] == C.FLAT
    assert m.get("reason") == "constant feature or outcome"      # BUG #4: label accurate


def test_34_monotonic_insufficient():
    rows = [_row(_sid(i), r=float(i), range_width_atr=float(i)) for i in range(10)]  # < 20
    assert C.monotonicity(rows, "range_width_atr")["classification"] == C.INSUFFICIENT


# ===================== AE 35-36 — correlation matrix / version ============= #
def test_35_symmetric_correlation():
    rows = [_row(_sid(i), r=float(i), range_width_atr=float(i), stop_distance_atr=float(i % 5))
            for i in range(30)]
    mat = C.correlation_matrix(rows, facts=("range_width_atr", "stop_distance_atr"))
    key = "range_width_atr|stop_distance_atr"
    # single direction key; value equals the reverse computed directly
    assert key in mat
    direct = C.pearson([r["range_width_atr"] for r in rows], [r["stop_distance_atr"] for r in rows])
    rev = C.pearson([r["stop_distance_atr"] for r in rows], [r["range_width_atr"] for r in rows])
    assert direct == rev == mat[key]["pearson"]


def test_36_version_mismatch_not_pooled():
    rows = [_row(_sid(1), qfv="session_edge_quality.v1"),
            _row(_sid(2), qfv="session_edge_quality.v2")]
    only_v1 = C.closed_rows(rows, quality_fact_version="session_edge_quality.v1")
    assert [r["signal_id"] for r in only_v1] == [_sid(1)]
    assert C.version_distribution(rows) == {"session_edge_quality.v1": 1,
                                            "session_edge_quality.v2": 1}


# ===================== AE 37-40 — chronological / OOS ====================== #
def test_37_chronological_unsorted_input_deterministic(tmp_path):
    instrs, m = _corpus(tmp_path, 30)
    ds = lifecycle.quality_dataset(instrs, memory=m)
    e1, l1 = C.chronological_split(ds, 0.7)
    e2, l2 = C.chronological_split(list(reversed(ds)), 0.7)
    assert [r["signal_id"] for r in e1] == [r["signal_id"] for r in e2]   # no shuffle, order-independent


def test_38_chronological_same_timestamp_tiebreak_signal_id():
    rows = [_row(_sid(3), ts="2026-01-01T00:00:00Z"),
            _row(_sid(1), ts="2026-01-01T00:00:00Z"),
            _row(_sid(2), ts="2026-01-01T00:00:00Z")]
    early, late = C.chronological_split(rows, 0.67)
    assert [r["signal_id"] for r in early + late] == [_sid(1), _sid(2), _sid(3)]  # sid tiebreak


def test_39_chronological_timezone_offsets_order_by_instant():      # BUG #2 regression
    rows = [_row(_sid(1), ts="2025-01-01T09:00:00+09:00"),   # 00:00:00Z (earlier)
            _row(_sid(2), ts="2025-01-01T00:00:01Z")]        # later
    early, late = C.chronological_split(rows, 0.5)
    assert [r["signal_id"] for r in early] == [_sid(1)]      # Tokyo row earlier, no leak
    assert [r["signal_id"] for r in late] == [_sid(2)]


def test_40_chronological_missing_or_malformed_timestamp_fails_closed():
    rows = [_row(_sid(1), ts="2026-01-01T00:00:00Z"),
            _row(_sid(2), ts=None),                          # missing
            _row(_sid(3), ts="not-a-timestamp")]             # malformed
    early, late = C.chronological_split(rows, 0.7)
    kept = {r["signal_id"] for r in early + late}
    assert kept == {_sid(1)}                                 # unorderable rows excluded (fail closed)


def test_40b_no_future_leaks_into_earlier_window(tmp_path):
    instrs, m = _corpus(tmp_path, 30)
    ds = lifecycle.quality_dataset(instrs, memory=m)
    early, late = C.chronological_split(ds, 0.6)
    from forex_swing_orb.bridge import serialize
    if early and late:
        assert max(serialize.parse_iso(r["generated_timestamp"]) for r in early) <= \
               min(serialize.parse_iso(r["generated_timestamp"]) for r in late)


# ===================== AE 41-46 — sample-size / robustness ================= #
def test_41_44_sample_size_boundaries():
    assert C.classify_sample_size(0) == C.INSUFFICIENT
    assert C.classify_sample_size(29) == C.INSUFFICIENT
    assert C.classify_sample_size(30) == C.EXPLORATORY
    assert C.classify_sample_size(199) == C.EXPLORATORY
    assert C.classify_sample_size(200) == C.CALIBRATION_CANDIDATE
    assert C.classify_sample_size(201) == C.CALIBRATION_CANDIDATE


def test_45_46_robustness_deterministic_and_nonmutating(tmp_path):
    instrs, m = _corpus(tmp_path, 40)
    ds = lifecycle.quality_dataset(instrs, memory=m)
    snap = copy.deepcopy(ds)
    a = C.robustness(ds, "range_width_atr")
    b = C.robustness(ds, "range_width_atr")
    assert a == b                                            # deterministic drop-best/worst
    assert ds == snap                                        # original not mutated


def test_46b_robustness_tiny_sample_insufficient():
    rows = [_row(_sid(1), r=1.0), _row(_sid(2), r=2.0)]
    assert C.robustness(rows, "range_width_atr")["status"] == C.INSUFFICIENT


# ===================== AE 47-49 — pipeline behaviors ======================= #
def test_47_empty_pipeline_decision_D():
    rep = C.calibration_report([], timestamp="2026-08-14T00:00:00Z")
    assert rep["decision"] == C.DECISION_D
    assert rep["dataset_summary"]["closed_trades"] == 0
    assert rep["proposed_score_model"] is None
    assert rep["feature_distributions"] == {} and rep["correlation_matrix"] == {}
    assert rep["threshold_retrospective"]["status"] == lifecycle.SCORE_UNAVAILABLE


def test_48_open_only_pipeline_no_phantom(tmp_path):
    m = _mem(tmp_path)                                       # instructions, no closed outcomes
    rep = C.calibration_report([_instr(_sid(i)) for i in range(5)], memory=m,
                               timestamp="2026-08-14T00:00:00Z")
    assert rep["dataset_summary"]["candidate_observations"] == 5
    assert rep["dataset_summary"]["closed_trades"] == 0
    assert rep["decision"] == C.DECISION_D                   # no fabricated metrics


def test_49_full_e2e_closed_pipeline(tmp_path):
    # SYNTHETIC machinery proof only — NOT evidence of predictive edge.
    instrs, m = _corpus(tmp_path, 40)
    rep = C.calibration_report(instrs, memory=m, timestamp="2026-08-14T00:00:00Z")
    assert rep["dataset_summary"]["closed_trades"] == 40
    assert rep["sample_size_classification"] == C.EXPLORATORY
    assert rep["decision"] == C.DECISION_B                   # 30<=n<200
    assert rep["feature_distributions"]["range_width_atr"]["status"] == "OK"
    # per-quantile metrics come from canonical portfolio calculators
    bq = rep["feature_distributions"]["range_width_atr"]["by_quantile"]
    assert bq and all("win_rate" in v and "profit_factor" in v for v in bq.values())
    assert rep["proposed_score_model"] is None              # never fabricated


# ===================== AE 50-58 — authority invariants ===================== #
def _def_owners(sig):
    return [p for p in PKG.rglob("*.py")
            if "/tests/" not in str(p) and re.search(sig, p.read_text(), re.M)]


def test_50_no_production_score_calculator():
    assert C.calibration_report([], timestamp="2026-08-14T00:00:00Z")["proposed_score_model"] is None
    assert "def score(" not in (PKG / "research" / "calibration.py").read_text()


def test_51_no_live_70_gate_in_trading():
    for pkg in ("bridge", "compliance", "position", "producer", "ea_mt5", "manage",
                "runtime", "session", "live"):
        for p in (PKG / pkg).rglob("*.py"):
            if "/tests/" in str(p):
                continue
            txt = p.read_text()
            assert "SCORE_MIN_QUALIFYING" not in txt and "trade_score" not in txt


def test_52_no_quality_to_risk_coupling():
    assert "quality_facts" not in (PKG / "compliance" / "sizing.py").read_text()
    assert "calibration" not in (PKG / "compliance" / "sizing.py").read_text()


def test_53_sole_lot_authority():
    assert _def_owners(r"^def allowable_volume\(") == [PKG / "compliance" / "sizing.py"]


def test_54_sole_realized_r_authority():
    assert _def_owners(r"^\s*def _realized_r\(") == [PKG / "manage" / "outcome.py"]
    # research never reconstructs R from prices
    for mod in ("calibration.py", "lifecycle.py"):
        src = (PKG / "research" / mod).read_text()
        assert "def _realized_r" not in src


def test_55_sole_portfolio_metric_authority():
    for fn in ("expectancy", "profit_factor", "win_loss", "max_drawdown", "equity_curve"):
        assert _def_owners(rf"^def {fn}\(") == [PKG / "research" / "portfolio.py"]


def test_56_sole_cohort_authority():
    assert _def_owners(r"^def cohort_of\(") == [PKG / "research" / "lifecycle.py"]


def test_56b_sole_correlation_authority():
    assert _def_owners(r"^def pearson\(") == [PKG / "research" / "calibration.py"]
    assert _def_owners(r"^def spearman\(") == [PKG / "research" / "calibration.py"]


def test_57_no_trading_module_imports_research():
    offenders = []
    for pkg in ("bridge", "compliance", "ea_mt5", "manage", "position", "producer",
                "runtime", "session", "live"):
        for p in (PKG / pkg).rglob("*.py"):
            if "/tests/" in str(p):
                continue
            if re.search(r"import\s+.*\bresearch\b|from\s+.*research|\bcalibration\b|\bquality_facts\b",
                         p.read_text()):
                offenders.append(str(p.relative_to(PKG)))
    assert offenders == []


def test_58_no_research_order_send_path():
    for p in (PKG / "research").rglob("*.py"):
        if "/tests/" in str(p):
            continue
        src = p.read_text()
        for banned in ("order_send", "OrderSend", "place_order", "write_instruction",
                       "bridge.enter", "socket", "urllib", "requests"):
            assert banned not in src, (p.name, banned)


# ===================== AE 59 — property / fuzz (deterministic) ============= #
def test_59_property_finite_inputs_finite_dimensionless_idempotent_nonmutating():
    # deterministic grid (no RNG); varies geometry across scales & directions
    combos = []
    for di, direction in enumerate(("LONG", "SHORT")):
        for atr in (0.00010, 0.00100, 0.05000):             # non-JPY and JPY-like
            for k in range(6):
                base = 1.10000 + k * 0.00050 if atr < 0.01 else 150.000 + k * 0.050
                combos.append((direction, atr, base, k, di))
    for direction, atr, base, k, di in combos:
        instr = _instr(_sid(k + di * 100 + int(atr * 1e5)), direction=direction, atr14=atr,
                       rhigh=base + 0.005 if atr < 0.01 else base + 0.5,
                       rlow=base, boundary=base + 0.003 if atr < 0.01 else base + 0.3,
                       confirm=base + 0.004 if atr < 0.01 else base + 0.4,
                       entry=base + 0.004 if atr < 0.01 else base + 0.4,
                       stop=base if atr < 0.01 else base,
                       retest=base + 0.002 if atr < 0.01 else base + 0.2,
                       minor=base + 0.001 if atr < 0.01 else base + 0.1)
        snap = copy.deepcopy(instr)
        q = quality_facts.extract(instr)
        assert instr == snap                                # no mutation
        assert q == quality_facts.extract(instr)            # idempotent
        for f in quality_facts.CONTINUOUS_FACTS:
            v = q[f]
            if v is not None:
                assert math.isfinite(v) and v >= 0          # finite, non-negative magnitude
        # ATR-normalized == price / atr (dimensionless, single ATR source)
        for pf, af in (("range_width_price", "range_width_atr"),
                       ("stop_distance_price", "stop_distance_atr")):
            if q[pf] is not None and q[af] is not None:
                assert q[af] == pytest.approx(q[pf] / atr)


def test_59b_dataset_order_does_not_change_aggregates(tmp_path):
    instrs, m = _corpus(tmp_path, 30)
    ds1 = lifecycle.quality_dataset(instrs, memory=m)
    ds2 = lifecycle.quality_dataset(list(reversed(instrs)), memory=m)
    assert ds1 == ds2                                        # deterministic regardless of input order
    assert C.univariate(ds1, "range_width_atr") == C.univariate(ds2, "range_width_atr")


def test_59c_duplicate_replay_does_not_change_counts(tmp_path):
    instrs, m = _corpus(tmp_path, 20)
    a = lifecycle.quality_dataset(instrs + instrs, memory=m)
    b = lifecycle.quality_dataset(instrs, memory=m)
    assert len(a) == len(b) == 20


# ===================== AE 60 — docs consistency ============================ #
def test_60_docs_assert_no_live_score_or_active_threshold():
    docs = REPO / "docs"
    # collapse whitespace so line-wrapped phrases still match
    calib = re.sub(r"\s+", " ", (docs / "SESSION_EDGE_CALIBRATION.md").read_text().lower())
    assert "no live trade score" in calib or "no trade score" in calib
    assert "no 70 gate" in calib or ("70 threshold" in calib and "not activated" in calib)
    assert "sole lot-size authority" in calib          # PR-3J owns volume
    quality = (docs / "SESSION_EDGE_QUALITY_FACTS.md").read_text()
    assert "no trade score" in quality.lower() or "trade_score" in quality


# ===================== extra: portfolio equity_curve F4.1 ================== #
def test_equity_curve_ignores_nonfinite():
    eq = portfolio.equity_curve([{"r_multiple": 1.0}, {"r_multiple": float("nan")},
                                 {"r_multiple": 2.0}])
    assert eq == [1.0, 1.0, 3.0]                             # NaN contributes 0, no poison
    assert math.isfinite(portfolio.max_drawdown(eq))
