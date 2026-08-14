"""PR-3P — quality-fact instrumentation (measurement only; no score, no behavior change).

Proves the pure quality-fact extractor derives continuous facts ONLY from an authorized
instruction's already-emitted evidence (no engine, no bars, no recompute), fails closed
on missing/zero ATR, uses canonical names, is immutable/idempotent, joins to realized R
by signal_id without phantom trades, introduces NO score / no 70 gate / no risk coupling,
and adds zero trading authority. Deterministic.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

from forex_swing_orb.agents.memory import MemoryStore
from forex_swing_orb.research import quality_facts as QF
from forex_swing_orb.research import lifecycle

REPO = Path(__file__).resolve().parents[3]
PKG = REPO / "forex_swing_orb"
ATR = 0.00100


def _instr(sid="a1b2c3d4e5f60718", **ev_over):
    ev = {"trend_d1": "BULLISH", "trend_h4": "BULLISH",
          "range_high": 1.10500, "range_low": 1.10000, "atr14": ATR,
          "boundary": 1.10500, "retest_extreme": 1.10450, "minor_swing_ref": 1.10550,
          "confirm_close": 1.10600, "stop_basis": 1.10400, "rr_planned": 2.0}
    ev.update(ev_over)
    return {"schema_version": 3, "signal_id": sid, "session_id": "LONDON",
            "strategy_id": "forex_swing_orb", "strategy_version": "swing_orb.v1.4.0",
            "symbol": "EURUSD.FX", "direction": "LONG",
            "entry_price": 1.10600, "stop_loss": 1.10400, "take_profit": 1.11000,
            "risk_fraction": 0.0025, "volume": 0.10,
            "generated_timestamp": "2026-01-05T09:15:00Z",
            "evidence_summary": ev}


# --------------------------------------------------------------------------- #
# S — fact extraction: exact formulas / units / determinism / fail-closed
# --------------------------------------------------------------------------- #
def test_S1_exact_formulas():
    q = QF.extract(_instr())
    assert q["range_width_price"] == pytest.approx(0.00500)
    assert q["range_width_atr"] == pytest.approx(5.0)
    assert q["retest_depth_price"] == pytest.approx(0.00050)
    assert q["retest_depth_atr"] == pytest.approx(0.5)
    assert q["entry_extent_beyond_boundary_price"] == pytest.approx(0.00100)
    assert q["entry_extent_beyond_boundary_atr"] == pytest.approx(1.0)
    assert q["confirmation_margin_price"] == pytest.approx(0.00050)
    assert q["confirmation_margin_atr"] == pytest.approx(0.5)
    assert q["stop_distance_price"] == pytest.approx(0.00200)
    assert q["stop_distance_atr"] == pytest.approx(2.0)
    assert q["rr_planned"] == pytest.approx(2.0)


def test_S2_atr_units_are_price_over_atr():
    q = QF.extract(_instr())
    assert q["stop_distance_atr"] == pytest.approx(q["stop_distance_price"] / ATR)


def test_S3_S8_finite_no_nan_inf():
    q = QF.extract(_instr())
    for k, v in q.items():
        if isinstance(v, float):
            assert math.isfinite(v), k


def test_S4_deterministic_same_input_same_fact():
    assert QF.extract(_instr()) == QF.extract(_instr())


def test_S5_order_independent():
    a = QF.extract(_instr())
    reordered = _instr()
    reordered["evidence_summary"] = dict(reversed(list(reordered["evidence_summary"].items())))
    assert QF.extract(reordered) == a


def test_S6_missing_atr_atr_facts_unavailable_price_present():
    q = QF.extract(_instr(atr14=None))
    assert q["range_width_atr"] is None and q["stop_distance_atr"] is None
    assert q["range_width_price"] == pytest.approx(0.00500)      # raw price still present


def test_S7_zero_atr_safe():
    q = QF.extract(_instr(atr14=0.0))
    assert q["range_width_atr"] is None                          # no divide-by-zero


def test_S8_inf_nan_metadata_unavailable():
    for bad in (float("inf"), float("nan")):
        q = QF.extract(_instr(atr14=bad))
        assert q["range_width_atr"] is None


def test_S6b_missing_source_fact_unavailable_not_fabricated():
    q = QF.extract(_instr(minor_swing_ref=None))
    assert q["confirmation_margin_price"] is None and q["confirmation_margin_atr"] is None


def test_S10_canonical_names_and_unavailable_facts():
    q = QF.extract(_instr())
    for name in QF.CONTINUOUS_FACTS:
        assert name in q
    for u in QF.UNAVAILABLE_FACTS:
        assert q[u] is None                                     # engine-discarded -> UNAVAILABLE
    # no alias/duplicate encoding of the same fact
    assert "breakout_pips" not in q and "breakout_extent_price" not in q
    assert q["quality_fact_version"] == "session_edge_quality.v1"


# --------------------------------------------------------------------------- #
# T / V — purity + authority separation (no engine, no trading imports)
# --------------------------------------------------------------------------- #
def test_TV_quality_facts_is_pure_no_trading_imports():
    src = (PKG / "research" / "quality_facts.py").read_text()
    for banned in ("signal_engine", "import producer", "compliance.sizing",
                   "compliance.engine", "compliance.gates", "execution_consumer",
                   "order_send", "position_manager", "get_bars", "resolve("):
        assert banned not in src


def test_V_sizing_does_not_import_quality_facts():
    assert "quality_facts" not in (PKG / "compliance" / "sizing.py").read_text()


def test_V_ea_has_no_quality_fact_logic():
    assert "quality_fact" not in (PKG / "ea_mt5" / "SessionEdgeExecutionEA.mq5").read_text().lower()


def test_V_no_score_or_risk_coupling_in_quality_facts():
    src = (PKG / "research" / "quality_facts.py").read_text().lower()
    for banned in ("trade_score =", "allowable_volume", "risk_fraction =",
                   "score >=", ">= 70", "def score", "volume ="):
        assert banned not in src
    # trade_score is present ONLY as an explicit None (no score computed)
    assert '"trade_score": None' in (PKG / "research" / "quality_facts.py").read_text()


def test_V_no_trading_module_imports_research():
    trading = ("bridge", "compliance", "ea_mt5", "manage", "position", "producer",
               "runtime", "session", "live")
    offenders = []
    for pkg in trading:
        for p in (PKG / pkg).rglob("*.py"):
            if "/tests/" in str(p):
                continue
            if re.search(r"import\s+.*\bresearch\b|from\s+.*research", p.read_text()):
                offenders.append(str(p.relative_to(PKG)))
    assert offenders == []


# --------------------------------------------------------------------------- #
# U — immutability / idempotency + outcome append
# --------------------------------------------------------------------------- #
def _mem(tmp_path):
    return MemoryStore(tmp_path / "memory")


def _write_outcome(m, sid, r_multiple):
    c = {"schema_version": 1, "signal_id": sid, "status": "CLOSED", "won": r_multiple > 0,
         "taken": True, "r_multiple": r_multiple, "direction": "LONG", "symbol": "EURUSD.FX",
         "ticket": 1, "broker_order_id": 1, "entry": 1.10600, "initial_stop": 1.10400,
         "weighted_close": 1.11000, "closed_volume": 0.10, "deal_count": 1,
         "realized_r_source": "mt5_deal_history"}
    m.write_raw("execution_outcome", "EURUSD.FX", c, source="outcome_reconciler",
                timestamp="2026-01-05T12:00:00Z", correlation_id=sid)


def test_U_dataset_dedup_and_idempotent(tmp_path):
    instrs = [_instr("a" * 16), _instr("a" * 16), _instr("b" * 16)]   # duplicate signal_id
    ds1 = lifecycle.quality_dataset(instrs)
    ds2 = lifecycle.quality_dataset(instrs)
    assert [r["signal_id"] for r in ds1] == ["a" * 16, "b" * 16]      # deduped, sorted
    assert ds1 == ds2                                                 # replay-idempotent


def test_U_outcome_append_does_not_rewrite_quality_facts(tmp_path):
    m = _mem(tmp_path); _write_outcome(m, "a" * 16, 2.0)
    without = lifecycle.quality_dataset([_instr("a" * 16)])[0]
    withm = lifecycle.quality_dataset([_instr("a" * 16)], memory=m)[0]
    # outcome R is appended; the quality facts themselves are byte-identical
    for k in QF.CONTINUOUS_FACTS:
        assert without[k] == withm[k]
    assert without["outcome_r"] is None and without["closed"] is False
    assert withm["outcome_r"] == 2.0 and withm["closed"] is True


# --------------------------------------------------------------------------- #
# W — candidate vs executed-trade recording (no phantom trades)
# --------------------------------------------------------------------------- #
def test_W_written_but_unexecuted_is_candidate_not_closed_trade(tmp_path):
    m = _mem(tmp_path)                                   # no outcome for this signal
    row = lifecycle.quality_dataset([_instr("c" * 16)], memory=m)[0]
    assert row["closed"] is False and row["outcome_r"] is None


def test_W_executed_trade_joins_once(tmp_path):
    m = _mem(tmp_path); _write_outcome(m, "d" * 16, -1.0)
    ds = lifecycle.quality_dataset([_instr("d" * 16)], memory=m)
    assert len(ds) == 1 and ds[0]["outcome_r"] == -1.0 and ds[0]["closed"] is True


# --------------------------------------------------------------------------- #
# P/Q — still no score authority after PR-3P
# --------------------------------------------------------------------------- #
def test_PQ_no_score_calculator_introduced():
    # trade_score remains None everywhere; cohort_of stays the sole cohort owner.
    q = QF.extract(_instr())
    assert q["trade_score"] is None
    hits = [p for p in PKG.rglob("*.py")
            if "/tests/" not in str(p) and re.search(r"^def cohort_of\(", p.read_text(), re.M)]
    assert hits == [PKG / "research" / "lifecycle.py"]
    # the quality dataset carries trade_score UNAVAILABLE, not a computed score
    assert lifecycle.quality_dataset([_instr()])[0]["trade_score"] is None
