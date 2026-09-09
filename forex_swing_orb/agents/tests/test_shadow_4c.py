"""Phase 4C — Shadow Mode pipeline, analytics, and authority boundaries."""

from __future__ import annotations

import tempfile
from datetime import timedelta
from pathlib import Path

from forex_swing_orb.agents import (Orchestrator, MemoryStore, MockLLMProvider,
                                    ShadowRunner, ShadowAnalytics, Advisory)
from forex_swing_orb.agents.contract import StrategyCandidate
from forex_swing_orb.bridge.audit import AuditLog
import phase4b_helpers as H


def _rig(llm="m"):
    t = Path(tempfile.mkdtemp())
    mem = MemoryStore(t / "m"); au = AuditLog(t / "a.jsonl")
    orch = Orchestrator(mem, au, llm=(MockLLMProvider() if llm == "m" else llm))
    return ShadowRunner(orch), mem, au, orch


def _strat(candidate=StrategyCandidate.QUALIFIED, direction="LONG", sid="sig-1",
           entry=1.1000, stop=1.0980, target=1.1040):
    return {"candidate": candidate, "direction": direction, "signal_id": sid,
            "entry": entry, "stop": stop, "target": target}


# -- pipeline ---------------------------------------------------------------
def test_shadow_pipeline_runs_and_is_informational():
    sr, mem, au, _ = _rig()
    rep = sr.observe(H.req(), H.full_bundle(), _strat(), H.NOW)
    assert rep["shadow"] is True and rep["informational_only"] is True
    assert rep["is_order"] is False
    assert rep["advisory_summary"]["advisory_decision"] == Advisory.PROCEED
    assert rep["memory_id"] is not None


def test_shadow_does_not_mutate_strategy_decision():
    sr, _, _, _ = _rig()
    strat = _strat()
    before = dict(strat)
    sr.observe(H.req(), H.full_bundle(), strat, H.NOW)
    assert strat == before                      # strategy decision untouched
    # the report stores a COPY
    rep = sr.observe(H.req(), H.full_bundle(), strat, H.NOW)
    rep["strategy_decision"]["entry"] = 9.9
    assert strat["entry"] == before["entry"]


def test_shadow_strategy_remains_authoritative_no_trade():
    sr, _, _, _ = _rig()
    rep = sr.observe(H.req(), H.full_bundle(), _strat(candidate=StrategyCandidate.NO_TRADE), H.NOW)
    # even with all agents CLEAR, strategy no-trade keeps advisory NO_TRADE
    assert rep["advisory_summary"]["advisory_decision"] == Advisory.NO_TRADE
    assert rep["metrics"]["strategy_decision"] == StrategyCandidate.NO_TRADE


# -- agreement / disagreement ------------------------------------------------
def test_shadow_full_agreement():
    sr, _, _, _ = _rig()
    rep = sr.observe(H.req(), H.full_bundle(), _strat(), H.NOW)
    m = rep["metrics"]
    assert m["full_agreement"] is True
    assert m["agreement_score"] == 1.0
    assert m["conflicting_agents"] == []
    assert m["strategy_advisory_agreement"] is True


def test_shadow_disagreement_when_liquidity_avoids():
    sr, _, _, _ = _rig()
    # a breakout-trap liquidity picture -> liquidity BLOCK while MI/News CLEAR
    bars = H.flat_bars(n=30)
    for i in (5, 12, 20):
        bars[i]["h"] = 1.1050
    bars[-2] = H.bar(bars[-2]["t"], 1.104, 1.1065, 1.103, 1.1060)
    bars[-1] = H.bar(bars[-1]["t"], 1.106, 1.1062, 1.102, 1.1030)
    bundle = H.full_bundle(liquidity=H.liq_bundle(bars=bars))
    rep = sr.observe(H.req(), bundle, _strat(), H.NOW)
    m = rep["metrics"]
    assert m["liquidity_assessment"] == "BLOCK"
    assert "liquidity" in m["conflicting_agents"]
    assert m["full_agreement"] is False
    assert rep["advisory_summary"]["advisory_decision"] == Advisory.NO_TRADE   # block wins


def test_shadow_news_block_recorded():
    sr, _, _, _ = _rig()
    bundle = H.full_bundle(events=[H.event(currency="EUR", impact="HIGH", minutes_from_now=10)])
    rep = sr.observe(H.req(), bundle, _strat(), H.NOW)
    assert rep["metrics"]["news_assessment"] == "BLOCK"
    assert rep["metrics"]["any_block"] is True


# -- analytics --------------------------------------------------------------
def test_shadow_statistics_aggregate():
    sr, mem, _, _ = _rig()
    for i in range(3):
        sr.observe(H.req(correlation_id=f"c{i}"), H.full_bundle(), _strat(sid=f"s{i}"), H.NOW)
    an = ShadowAnalytics(mem)
    summ = an.summarize()
    assert summ["count"] == 3
    assert summ["historical_agreement_matrix"].get("QUALIFIED->ADVISE_PROCEED") == 3
    assert summ["regime_distribution"].get("TRENDING") == 3
    assert summ["mean_agreement_score"] == 1.0
    assert "MI_TRENDING_SUPPORTIVE" in summ["reason_code_frequency"]


def test_shadow_accuracy_with_outcomes():
    sr, mem, _, _ = _rig()
    sr.observe(H.req(correlation_id="cA"), H.full_bundle(), _strat(sid="win"), H.NOW)
    sr.observe(H.req(correlation_id="cB"), H.full_bundle(), _strat(sid="loss"), H.NOW)
    mem.write_raw("execution_outcome", "EURUSD.FX", {"signal_id": "win", "won": True, "taken": True},
                  source="exec", timestamp=H.iso(H.NOW))
    mem.write_raw("execution_outcome", "EURUSD.FX", {"signal_id": "loss", "won": False, "taken": True},
                  source="exec", timestamp=H.iso(H.NOW))
    acc = ShadowAnalytics(mem).accuracy(symbol="EURUSD.FX")
    assert acc["outcomes_available"] is True and acc["considered"] == 2
    assert acc["true_positive"] == 1 and acc["false_positive"] == 1
    assert acc["advisory_accuracy"] == 0.5


def test_shadow_accuracy_zero_without_outcomes():
    sr, mem, _, _ = _rig()
    sr.observe(H.req(), H.full_bundle(), _strat(), H.NOW)
    acc = ShadowAnalytics(mem).accuracy()
    assert acc["outcomes_available"] is False and acc["considered"] == 0


# -- boundaries -------------------------------------------------------------
def test_shadow_writes_no_bridge_instructions():
    sr, mem, _, _ = _rig()
    sr.observe(H.req(), H.full_bundle(), _strat(), H.NOW)
    root = mem.root
    assert not (root / "outbox").exists() and not (root / "inbox").exists()
    # only memory tiers exist
    assert (root / "raw").exists()


def test_shadow_source_has_no_execution_or_networking():
    src = (Path(__file__).resolve().parents[1] / "shadow.py").read_text()
    for tok in ("ea_mt5", "producer", "write_instruction", "order_send",
                "import socket", "urllib", "requests.get", "WebRequest("):
        assert tok not in src


def test_shadow_report_carries_outcome_reference():
    sr, _, _, _ = _rig()
    rep = sr.observe(H.req(), H.full_bundle(), _strat(sid="ref-xyz"), H.NOW)
    assert rep["metrics"]["outcome_reference"] == "ref-xyz"


def test_shadow_deterministic():
    a_sr, _, _, _ = _rig()
    b_sr, _, _, _ = _rig()
    ra = a_sr.observe(H.req(), H.full_bundle(), _strat(), H.NOW)["metrics"]
    rb = b_sr.observe(H.req(), H.full_bundle(), _strat(), H.NOW)["metrics"]
    assert ra == rb
