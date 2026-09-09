"""Orchestration order + hard-override invariants + data quality.
(Test reqs 5,6,8,9,10,11,19.)"""

from __future__ import annotations

from datetime import timedelta

from forex_swing_orb.agents import Advisory, StrategyCandidate, ORCHESTRATION_ORDER
from forex_swing_orb.agents.contract import ReasonCode
from conftest import make_request, good_bundle, NOW, iso


def _run(orch, bundle=None, strategy=StrategyCandidate.QUALIFIED, now=NOW):
    return orch.run(make_request(), bundle or good_bundle(), strategy, now)


def test_orchestration_order_is_frozen(orchestrator):
    out = _run(orchestrator)
    assert out["stages"] == list(ORCHESTRATION_ORDER)


def test_clean_setup_proceeds_advisory(orchestrator):
    out = _run(orchestrator)
    assert out["decision"]["advisory_decision"] == Advisory.PROCEED
    assert out["decision"]["is_order"] is False


def test_strategy_no_trade_cannot_be_overridden(orchestrator):
    out = _run(orchestrator, strategy=StrategyCandidate.NO_TRADE)
    assert out["decision"]["advisory_decision"] == Advisory.NO_TRADE
    assert ReasonCode.COORD_NO_TRADE_STRATEGY in out["decision"]["reason_codes"]


def test_news_block_cannot_be_overridden(orchestrator):
    b = good_bundle()
    b["news"]["events"] = [{
        "time": iso(NOW + timedelta(minutes=5)), "currency": "USD", "impact": "HIGH",
        "event": "NFP", "source": "calendar", "ingested_at": iso(NOW)}]
    out = _run(orchestrator, bundle=b)
    assert out["decision"]["advisory_decision"] == Advisory.NO_TRADE
    assert ReasonCode.COORD_BLOCK_NEWS in out["decision"]["reason_codes"]


def test_risk_reject_cannot_be_overridden(orchestrator):
    b = good_bundle()
    b["risk"]["open_positions_symbol"] = 1
    out = _run(orchestrator, bundle=b)
    assert out["decision"]["advisory_decision"] == Advisory.NO_TRADE
    assert ReasonCode.COORD_BLOCK_RISK in out["decision"]["reason_codes"]


def test_stale_data_fails_closed(orchestrator):
    b = good_bundle()
    b["market"]["timestamp"] = iso(NOW - timedelta(hours=5))   # stale
    b["market"]["age_sec"] = 18000
    out = _run(orchestrator, bundle=b)
    assert out["data_quality"]["ok"] is False
    assert out["decision"]["advisory_decision"] == Advisory.NO_TRADE
    assert ReasonCode.COORD_BLOCK_DATA_QUALITY in out["decision"]["reason_codes"]


def test_missing_required_data_fails_closed(orchestrator):
    b = good_bundle()
    del b["news"]["provenance"]
    out = _run(orchestrator, bundle=b)
    assert out["data_quality"]["ok"] is False
    assert out["decision"]["advisory_decision"] == Advisory.NO_TRADE


def test_high_confidence_never_overrides_block(orchestrator):
    # even a clean, high-confidence context cannot flip a strategy no-trade
    out = _run(orchestrator, strategy=StrategyCandidate.NO_TRADE)
    assert out["decision"]["advisory_decision"] == Advisory.NO_TRADE
    assert out["decision"]["confidence"] == 0.0


def test_caution_agent_yields_advisory_caution(orchestrator):
    b = good_bundle()
    b["liquidity"]["retest_quality"] = "WEAK"       # -> liquidity CAUTION
    out = _run(orchestrator, bundle=b)
    assert out["decision"]["advisory_decision"] == Advisory.CAUTION


def test_explanation_accompanies_every_decision(orchestrator):
    out = _run(orchestrator)
    exp = out["explanation"]
    assert exp["final_assessment"] == out["decision"]["advisory_decision"]
    assert exp["is_decision_maker"] is False
    assert set(exp["agent_outputs"]) == set(out["agent_results"])
