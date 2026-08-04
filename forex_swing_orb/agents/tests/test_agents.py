"""Per-agent behaviour: assessments, fail-closed, stale/missing data, Critic
cannot approve, deterministic-only agents reject an LLM. (Test reqs 1,3,4,5,12.)"""

from __future__ import annotations

import pytest

from forex_swing_orb.agents import Assessment, MockLLMProvider, validate_result
from forex_swing_orb.agents.contract import LiquidityRating, NewsRating, ReasonCode
from forex_swing_orb.agents.agents import (MarketIntelligenceAgent, LiquidityAgent,
                                           NewsComplianceAgent, RiskAgent, CriticAgent)
from conftest import make_request, good_bundle, NOW, iso
from datetime import timedelta


def _ctx(bundle):
    return {"market": bundle["market"], "liquidity": bundle["liquidity"],
            "news": bundle["news"], "risk": bundle["risk"]}


# -- every agent returns a valid structured result --------------------------
@pytest.mark.parametrize("cls,llm_ok", [
    (MarketIntelligenceAgent, True), (LiquidityAgent, True),
    (NewsComplianceAgent, False), (RiskAgent, False), (CriticAgent, True)])
def test_agent_returns_valid_result(cls, llm_ok):
    agent = cls(llm=MockLLMProvider()) if llm_ok else cls()
    ctx = _ctx(good_bundle())
    ctx["agent_results"] = {}
    res = agent.evaluate(make_request(), ctx, NOW)
    ok, reason, detail = validate_result(res)
    assert ok, (reason, detail)
    assert res["assessment"] in Assessment.ALL


def test_deterministic_agent_rejects_llm():
    with pytest.raises(ValueError):
        RiskAgent(llm=MockLLMProvider())
    with pytest.raises(ValueError):
        NewsComplianceAgent(llm=MockLLMProvider())


# -- liquidity structured rating -------------------------------------------
def test_liquidity_avoid_on_trap():
    b = good_bundle()
    b["liquidity"]["breakout_trap_risk"] = True
    res = LiquidityAgent().evaluate(make_request(), _ctx(b), NOW)
    assert res["evidence"]["liquidity_rating"] == LiquidityRating.AVOID
    assert res["assessment"] == Assessment.BLOCK


def test_liquidity_favorable_on_good_retest():
    res = LiquidityAgent().evaluate(make_request(), _ctx(good_bundle()), NOW)
    assert res["evidence"]["liquidity_rating"] == LiquidityRating.FAVORABLE
    assert res["assessment"] == Assessment.CLEAR


# -- news fail-closed + lockout --------------------------------------------
def test_news_fails_closed_on_unverified():
    b = good_bundle()
    b["news"]["verified"] = False
    res = NewsComplianceAgent().evaluate(make_request(), _ctx(b), NOW)
    assert res["assessment"] == Assessment.BLOCK
    assert ReasonCode.DQ_NO_PROVENANCE in res["reason_codes"]


def test_news_block_on_high_impact_in_window():
    b = good_bundle()
    b["news"]["events"] = [{
        "time": iso(NOW + timedelta(minutes=10)), "currency": "EUR", "impact": "HIGH",
        "event": "ECB Rate Decision", "source": "calendar", "ingested_at": iso(NOW)}]
    res = NewsComplianceAgent().evaluate(make_request(), _ctx(b), NOW)
    assert res["assessment"] == Assessment.BLOCK
    assert res["evidence"]["news_rating"] == NewsRating.BLOCK


def test_news_ignores_unrelated_currency():
    b = good_bundle()
    b["news"]["events"] = [{
        "time": iso(NOW + timedelta(minutes=10)), "currency": "JPY", "impact": "HIGH",
        "event": "BOJ", "source": "calendar", "ingested_at": iso(NOW)}]
    res = NewsComplianceAgent().evaluate(make_request(), _ctx(b), NOW)  # EURUSD
    assert res["assessment"] == Assessment.CLEAR


def test_news_malformed_event_fails_closed():
    b = good_bundle()
    b["news"]["events"] = [{"currency": "EUR", "impact": "HIGH"}]  # missing fields
    res = NewsComplianceAgent().evaluate(make_request(), _ctx(b), NOW)
    assert res["assessment"] == Assessment.BLOCK
    assert ReasonCode.DQ_MALFORMED in res["reason_codes"]


# -- risk deterministic rules ----------------------------------------------
def test_risk_blocks_existing_position():
    b = good_bundle()
    b["risk"]["open_positions_symbol"] = 1
    res = RiskAgent().evaluate(make_request(), _ctx(b), NOW)
    assert res["assessment"] == Assessment.BLOCK
    assert ReasonCode.RISK_REJECT in res["reason_codes"]


def test_risk_blocks_daily_loss_breach():
    b = good_bundle()
    b["risk"]["account_daily_loss_pct"] = 3.5   # > max 3.0
    res = RiskAgent().evaluate(make_request(), _ctx(b), NOW)
    assert res["assessment"] == Assessment.BLOCK


def test_risk_missing_inputs_fail_closed():
    b = good_bundle()
    del b["risk"]["planned_rr"]
    res = RiskAgent().evaluate(make_request(), _ctx(b), NOW)
    assert res["assessment"] == Assessment.BLOCK
    assert "planned_rr" in res["missing_inputs"]


# -- critic cannot approve --------------------------------------------------
def test_critic_cannot_approve_only_objects():
    b = good_bundle()
    ctx = _ctx(b)
    ctx["agent_results"] = {}
    ctx["critic_flags"] = {}
    res = CriticAgent().evaluate(make_request(), ctx, NOW)
    # best case is CLEAR (no objection) — never an APPROVE/PROCEED verdict
    assert res["assessment"] in (Assessment.CLEAR, Assessment.CAUTION, Assessment.BLOCK)
    assert "approve" not in str(res["assessment"]).lower()


def test_critic_blocks_on_news_conflict():
    ctx = _ctx(good_bundle())
    ctx["agent_results"] = {}
    ctx["critic_flags"] = {"news_conflict": True}
    res = CriticAgent().evaluate(make_request(), ctx, NOW)
    assert res["assessment"] == Assessment.BLOCK


def test_critic_escalates_upstream_block():
    ctx = _ctx(good_bundle())
    ctx["agent_results"] = {"risk": {"assessment": Assessment.BLOCK}}
    ctx["critic_flags"] = {}
    res = CriticAgent().evaluate(make_request(), ctx, NOW)
    assert res["assessment"] == Assessment.BLOCK
