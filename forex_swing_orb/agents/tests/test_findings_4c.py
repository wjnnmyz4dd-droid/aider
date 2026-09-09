"""Phase 4C — regression tests for accepted review findings A and D."""

from __future__ import annotations

from datetime import timedelta

from forex_swing_orb.agents import Assessment
from forex_swing_orb.agents.contract import ReasonCode
from forex_swing_orb.agents.agents import NewsComplianceAgent, LiquidityAgent
import phase4b_helpers as H


def _news(ev):
    return NewsComplianceAgent().evaluate(H.req(), {"news": H.news_bundle(events=[ev])}, H.NOW)


# -- Finding A: verification blocking limited to in-window events -------------
def test_findingA_unverified_far_future_does_not_block():
    ev = H.event(currency="EUR", impact="LOW", minutes_from_now=7200,   # 5 days out
                 verification_state="UNVERIFIED")
    res = _news(ev)
    assert res["assessment"] == Assessment.CLEAR
    assert ReasonCode.NEWS_CLEAR in res["reason_codes"]
    assert ReasonCode.NEWS_SOURCE_UNVERIFIED not in res["reason_codes"]


def test_findingA_unverified_high_far_future_does_not_block():
    ev = H.event(currency="USD", impact="HIGH", minutes_from_now=4320,   # 3 days out
                 verification_state="RUMOR")
    assert _news(ev)["assessment"] == Assessment.CLEAR


def test_findingA_unverified_in_window_still_blocks():
    ev = H.event(currency="EUR", impact="HIGH", minutes_from_now=10,
                 verification_state="RUMOR")
    res = _news(ev)
    assert res["assessment"] == Assessment.BLOCK
    assert ReasonCode.NEWS_SOURCE_UNVERIFIED in res["reason_codes"]


def test_findingA_reason_code_precision_unverified_not_labeled_high():
    # an unverified MEDIUM in-window event blocks for UNVERIFIED, not HIGH_IMPACT
    ev = H.event(currency="EUR", impact="MEDIUM", minutes_from_now=10,
                 verification_state="UNVERIFIED")
    res = _news(ev)
    assert res["assessment"] == Assessment.BLOCK
    assert ReasonCode.NEWS_SOURCE_UNVERIFIED in res["reason_codes"]
    assert ReasonCode.NEWS_HIGH_IMPACT_BLOCK not in res["reason_codes"]


def test_findingA_verified_high_in_window_still_blocks():
    ev = H.event(currency="EUR", impact="HIGH", minutes_from_now=10)
    res = _news(ev)
    assert res["assessment"] == Assessment.BLOCK
    assert ReasonCode.NEWS_HIGH_IMPACT_BLOCK in res["reason_codes"]


# -- Finding D: liquidity robust when market context is None/absent -----------
def _bars_equal_highs():
    bars = H.flat_bars(n=30)
    for i in (5, 12, 20):
        bars[i]["h"] = 1.1050
    return bars


def test_findingD_liquidity_market_none_no_crash():
    lq = LiquidityAgent(llm=None)
    res = lq.evaluate(H.req(), {"market": None, "liquidity": H.liq_bundle(bars=_bars_equal_highs())},
                      H.NOW)
    assert res["assessment"] in Assessment.ALL
    assert "sweep_state" in res["evidence"]          # live path completed (not fail-closed)
    assert res["evidence"].get("fail_closed") is not True


def test_findingD_liquidity_market_key_absent_no_crash():
    lq = LiquidityAgent(llm=None)
    res = lq.evaluate(H.req(), {"liquidity": H.liq_bundle(bars=_bars_equal_highs())}, H.NOW)
    assert res["assessment"] in Assessment.ALL
    assert "equal_highs" in res["evidence"]


def test_findingD_freshness_market_none_is_null_not_error():
    lq = LiquidityAgent(llm=None)
    res = lq.evaluate(H.req(), {"market": None, "liquidity": H.liq_bundle(bars=_bars_equal_highs())},
                      H.NOW)
    assert res["data_freshness"]["market"] is None
