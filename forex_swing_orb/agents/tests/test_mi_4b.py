"""Phase 4B — Market Intelligence live behavior (checks 1-10)."""

from __future__ import annotations

from forex_swing_orb.agents import Assessment, MockLLMProvider, StrategyCandidate
from forex_swing_orb.agents import Orchestrator, MemoryStore
from forex_swing_orb.agents.contract import ReasonCode
from forex_swing_orb.agents.agents import MarketIntelligenceAgent
from forex_swing_orb.bridge.audit import AuditLog
import phase4b_helpers as H


def _mi(market, direction="LONG"):
    agent = MarketIntelligenceAgent(llm=MockLLMProvider())
    return agent.evaluate(H.req(), H.ctx(market=market, direction=direction), H.NOW)


def test_mi_trending_supportive():
    res = _mi(H.market_facts(trend_d1="BULLISH", trend_h4="BULLISH", trend_health="STRONG"))
    assert res["evidence"]["regime"] == "TRENDING"
    assert res["assessment"] == Assessment.CLEAR
    assert ReasonCode.MI_TRENDING_SUPPORTIVE in res["reason_codes"]


def test_mi_ranging():
    res = _mi(H.market_facts(trend_d1="NEUTRAL", trend_h4="NEUTRAL", trend_health="WEAK"))
    assert res["evidence"]["regime"] == "RANGING"
    assert res["assessment"] == Assessment.CAUTION
    assert ReasonCode.MI_RANGING in res["reason_codes"]


def test_mi_transitional():
    res = _mi(H.market_facts(trend_d1="BULLISH", trend_h4="NEUTRAL", trend_health="MODERATE"))
    assert res["evidence"]["regime"] == "TRANSITIONAL"
    assert res["assessment"] == Assessment.CAUTION
    assert ReasonCode.MI_TRANSITIONAL in res["reason_codes"]


def test_mi_disordered_abnormal_volatility():
    res = _mi(H.market_facts(volatility="ABNORMAL"))
    assert res["evidence"]["regime"] == "DISORDERED"
    assert res["assessment"] == Assessment.BLOCK
    assert ReasonCode.MI_DISORDERED in res["reason_codes"]
    assert ReasonCode.MI_VOLATILITY_ABNORMAL in res["reason_codes"]


def test_mi_insufficient_data():
    res = _mi({"session": "LONDON"})   # no trend facts, no regime hint
    assert res["evidence"]["regime"] == "UNKNOWN"
    assert res["assessment"] == Assessment.CAUTION
    assert ReasonCode.MI_DATA_INSUFFICIENT in res["reason_codes"]
    assert "trend_d1" in res["missing_inputs"]


def test_mi_stale_data_gated_by_data_quality():
    # staleness is enforced by the data-quality gate before MI runs
    import tempfile, os
    orch = Orchestrator(MemoryStore(tempfile.mkdtemp()),
                        AuditLog(os.path.join(tempfile.mkdtemp(), "a.jsonl")),
                        llm=MockLLMProvider())
    market = H.market_facts()
    market["timestamp"] = H.iso(H.NOW.replace(hour=4))   # ~8h stale
    market["age_sec"] = 8 * 3600
    out = orch.run_advisory(H.req(), {"market": market, "news": H.news_bundle(),
                                      "liquidity": H.liq_bundle()},
                            StrategyCandidate.QUALIFIED, H.NOW)
    assert out["data_quality"]["ok"] is False
    assert out["advisory_summary"]["advisory_decision"] == "ADVISE_NO_TRADE"


def test_mi_conflicting_structure():
    res = _mi(H.market_facts(trend_d1="BULLISH", trend_h4="BEARISH"))
    assert ReasonCode.MI_STRUCTURE_CONFLICT in res["reason_codes"]
    assert res["assessment"] in (Assessment.CAUTION, Assessment.BLOCK)


def test_mi_abnormal_volatility_reason():
    res = _mi(H.market_facts(volatility="EXTREME"))
    assert ReasonCode.MI_VOLATILITY_ABNORMAL in res["reason_codes"]


def test_mi_does_not_recalculate_strategy_authority():
    res = _mi(H.market_facts(trend_d1="BULLISH", trend_h4="BULLISH"))
    ev = res["evidence"]
    assert ev["consumes_strategy_facts"] is True
    assert ev["recomputes_strategy"] is False
    # trend facts are echoed verbatim, not re-derived
    assert ev["structure_summary"]["trend_d1"] == "BULLISH"
    assert ev["structure_summary"]["trend_h4"] == "BULLISH"


def test_mi_deterministic_output():
    a = _mi(H.market_facts())
    b = _mi(H.market_facts())
    a.pop("generated_timestamp"); b.pop("generated_timestamp")
    assert a == b
