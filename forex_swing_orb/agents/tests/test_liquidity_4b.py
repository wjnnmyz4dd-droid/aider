"""Phase 4B — Liquidity live behavior (checks 11-24)."""

from __future__ import annotations

from forex_swing_orb.agents import Assessment, MockLLMProvider
from forex_swing_orb.agents.contract import LiquidityRating, ReasonCode
from forex_swing_orb.agents.agents import LiquidityAgent
from forex_swing_orb.agents.agents import liquidity_calc as LC
import phase4b_helpers as H


def _liq(liqb):
    return LiquidityAgent(llm=MockLLMProvider()).evaluate(
        H.req(), H.ctx(liquidity=liqb, market=H.market_facts()), H.NOW)


def _bars_with_equal_highs(level=1.1050, n=30):
    bars = H.flat_bars(n=n, high=1.1020, low=1.0980, close=1.1000)
    for i in (5, 12, 20):                       # repeat the same high (equal highs)
        bars[i]["h"] = level
    return bars


def test_liquidity_equal_highs_detected():
    res = _liq(H.liq_bundle(bars=_bars_with_equal_highs()))
    assert 1.1050 in [round(x, 4) for x in res["evidence"]["equal_highs"]]


def test_liquidity_equal_lows_detected():
    bars = H.flat_bars(n=30)
    for i in (4, 10, 18):
        bars[i]["l"] = 1.0950
    res = _liq(H.liq_bundle(bars=bars))
    assert 1.0950 in [round(x, 4) for x in res["evidence"]["equal_lows"]]


def test_liquidity_prior_session_high_low():
    prior = [H.bar(H.iso(H.NOW), 1.10, 1.1080, 1.0920, 1.10) for _ in range(10)]
    res = _liq(H.liq_bundle(prior_session_bars=prior))
    assert res["evidence"]["prior_session_high"] == 1.1080
    assert res["evidence"]["prior_session_low"] == 1.0920


def test_liquidity_confirmed_sweep():
    bars = _bars_with_equal_highs(level=1.1050)
    bars[-1] = H.bar(bars[-1]["t"], 1.104, 1.1060, 1.103, 1.1035)  # pierce then close back
    res = _liq(H.liq_bundle(bars=bars))
    assert res["evidence"]["sweep_state"] == "CONFIRMED"


def test_liquidity_unconfirmed_sweep():
    bars = _bars_with_equal_highs(level=1.1050)
    bars[-1] = H.bar(bars[-1]["t"], 1.104, 1.1060, 1.104, 1.1058)  # pierce and hold above
    # entry far from the pool so the sweep classification (not trap) is exercised
    res = _liq(H.liq_bundle(bars=bars, candidate={"direction": "LONG", "entry": 1.1090,
                                                  "stop": 1.1070, "target": 1.1110}))
    assert res["evidence"]["sweep_state"] == "UNCONFIRMED"
    assert ReasonCode.LIQUIDITY_SWEEP_UNCONFIRMED in res["reason_codes"]


def test_liquidity_failed_breakout_is_trap():
    bars = _bars_with_equal_highs(level=1.1050)
    # a bar CLOSES above the 1.1050 pool, then the next CLOSES back below (reclaim)
    bars[-2] = H.bar(bars[-2]["t"], 1.104, 1.1065, 1.103, 1.1060)
    bars[-1] = H.bar(bars[-1]["t"], 1.106, 1.1062, 1.102, 1.1030)
    res = _liq(H.liq_bundle(bars=bars))
    assert res["evidence"]["trap_risk"] is True
    assert ReasonCode.LIQUIDITY_FAILED_BREAKOUT in res["reason_codes"]
    assert res["assessment"] == Assessment.BLOCK   # AVOID


def test_liquidity_pool_behind_entry_trap():
    # baseline lows at 1.1004; three interior bars dip to 1.0998 (local troughs =
    # a stop-cluster pool just behind a LONG entry at 1.1000)
    bars = [H.bar(H.iso(H.NOW), 1.1005, 1.1010, 1.1004, 1.1006) for _ in range(30)]
    for i in (3, 9, 15):
        bars[i]["l"] = 1.0998
    res = _liq(H.liq_bundle(bars=bars, candidate={"direction": "LONG", "entry": 1.1000,
                                                  "stop": 1.0980, "target": 1.1040}))
    assert res["evidence"]["trap_risk"] is True
    assert ReasonCode.LIQUIDITY_POOL_BEHIND_ENTRY in res["reason_codes"]
    assert res["evidence"]["liquidity_rating"] == LiquidityRating.AVOID


def test_liquidity_favorable_clean():
    res = _liq(H.liq_bundle())
    assert res["evidence"]["liquidity_rating"] == LiquidityRating.FAVORABLE
    assert res["assessment"] == Assessment.CLEAR


def test_liquidity_weak_retest_context():
    res = _liq(H.liq_bundle(retest_quality="WEAK"))
    assert res["evidence"]["retest_liquidity_quality"] == "WEAK"
    assert res["assessment"] == Assessment.CAUTION
    assert ReasonCode.LIQUIDITY_RETEST_WEAK in res["reason_codes"]


def test_liquidity_insufficient_data():
    res = _liq(H.liq_bundle(bars=H.flat_bars(n=5)))
    assert ReasonCode.LIQUIDITY_DATA_INSUFFICIENT in res["reason_codes"]
    assert res["assessment"] == Assessment.CAUTION


def test_liquidity_stale_data_fails_closed():
    res = _liq(H.liq_bundle(stale=True))
    assert ReasonCode.LIQUIDITY_DATA_STALE in res["reason_codes"]
    assert res["assessment"] == Assessment.BLOCK


def test_liquidity_no_future_bar_dependency():
    # a sweep that only occurs in the final bar must NOT be seen from a prefix
    bars = _bars_with_equal_highs(level=1.1050)
    bars[-1] = H.bar(bars[-1]["t"], 1.104, 1.1060, 1.103, 1.1035)
    tol = 2 * 0.0001
    assert LC.detect_sweep(bars[:-1], 1.1050, "above", tol) != "CONFIRMED"
    assert LC.detect_sweep(bars, 1.1050, "above", tol) == "CONFIRMED"


def test_liquidity_deterministic_output():
    a = _liq(H.liq_bundle()); b = _liq(H.liq_bundle())
    a.pop("generated_timestamp"); b.pop("generated_timestamp")
    assert a == b


def test_liquidity_does_not_generate_direction():
    res = _liq(H.liq_bundle())
    assert res["evidence"]["creates_direction"] is False
    for f in ("direction", "entry_price", "stop_loss", "take_profit"):
        assert f not in res
