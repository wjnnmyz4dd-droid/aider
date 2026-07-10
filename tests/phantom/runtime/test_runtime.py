"""Runtime category (ADR-031 SS3): the fixed six-stage sequence and its
early-exit discipline -- a rejection at any stage stops the cycle
immediately, no later stage is called."""

from __future__ import annotations

import unittest

from phantom.compliance_engine.models import ComplianceDecision
from phantom.risk_engine.models import PortfolioState
from phantom.runtime.engine import RuntimeOrchestrator
from phantom.runtime.models import CycleOutcome, CycleStage
from tests.phantom.runtime._fixtures import (
    T0,
    make_account_state,
    make_bars,
    make_compliance_snapshot,
    make_config,
    make_market_safety_inputs,
    make_profile,
    make_qualified_strategy_snapshot,
    make_risk_snapshot,
    make_stub_bridge_submit,
    make_stub_compliance_engine,
    make_stub_evidence_engine,
    make_stub_mi_engine,
    make_stub_risk_engine,
    make_stub_strategy_engine,
)


def _run(evidence=None, mi=None, strategy=None, risk=None, compliance=None, bridge_submit=None):
    evidence_stub = make_stub_evidence_engine(evidence)
    mi_stub = make_stub_mi_engine(mi)
    strategy_stub = make_stub_strategy_engine(strategy)
    risk_stub = make_stub_risk_engine(risk)
    compliance_stub = make_stub_compliance_engine(compliance)
    bridge_submit = bridge_submit if bridge_submit is not None else make_stub_bridge_submit()
    orchestrator = RuntimeOrchestrator(make_config(), evidence_stub, mi_stub, strategy_stub, risk_stub, compliance_stub, bridge_submit)
    record = orchestrator.run_cycle_for_pair(
        "EURUSD", make_bars(), (), 1.0, 1.0, make_market_safety_inputs(),
        PortfolioState(), None, make_account_state(), make_profile(), T0, "CYCLE-1",
    )
    return record, evidence_stub, mi_stub, strategy_stub, risk_stub, compliance_stub, bridge_submit


class TestFullSequenceApproved(unittest.TestCase):
    def test_every_stage_called_in_order_and_command_submitted(self):
        record, evidence_stub, mi_stub, strategy_stub, risk_stub, compliance_stub, bridge_submit = _run()
        self.assertEqual(record.outcome, CycleOutcome.SUBMITTED)
        self.assertEqual(record.stage_reached, CycleStage.BRIDGE)
        self.assertEqual(evidence_stub.call_count, 1)
        self.assertEqual(mi_stub.call_count, 1)
        self.assertEqual(strategy_stub.call_count, 1)
        self.assertEqual(risk_stub.call_count, 1)
        self.assertEqual(compliance_stub.call_count, 1)
        self.assertEqual(len(bridge_submit.calls), 1)
        stages = [t.stage for t in record.stage_timings]
        self.assertEqual(stages, [CycleStage.EVIDENCE, CycleStage.MARKET_INTELLIGENCE, CycleStage.STRATEGY, CycleStage.RISK, CycleStage.COMPLIANCE, CycleStage.BRIDGE])


class TestEarlyExits(unittest.TestCase):
    def test_strategy_rejection_stops_before_risk(self):
        from tests.phantom.risk_engine._fixtures import make_strategy_snapshot

        rejected_strategy = make_strategy_snapshot(rejected=True)
        record, _, _, _, risk_stub, compliance_stub, bridge_submit = _run(strategy=rejected_strategy)
        self.assertEqual(record.outcome, CycleOutcome.NO_STRATEGY)
        self.assertEqual(record.stage_reached, CycleStage.STRATEGY)
        self.assertEqual(risk_stub.call_count, 0)
        self.assertEqual(compliance_stub.call_count, 0)
        self.assertEqual(len(bridge_submit.calls), 0)

    def test_risk_rejection_stops_before_compliance(self):
        rejected_risk = make_risk_snapshot(approved=False)
        record, _, _, _, _, compliance_stub, bridge_submit = _run(risk=rejected_risk)
        self.assertEqual(record.outcome, CycleOutcome.RISK_REJECTED)
        self.assertEqual(record.stage_reached, CycleStage.RISK)
        self.assertEqual(compliance_stub.call_count, 0)
        self.assertEqual(len(bridge_submit.calls), 0)

    def test_compliance_rejection_stops_before_bridge(self):
        rejected_compliance = make_compliance_snapshot(decision=ComplianceDecision.REJECT, original_size_r=1.25)
        record, _, _, _, _, _, bridge_submit = _run(compliance=rejected_compliance)
        self.assertEqual(record.outcome, CycleOutcome.COMPLIANCE_REJECTED)
        self.assertEqual(record.stage_reached, CycleStage.COMPLIANCE)
        self.assertEqual(len(bridge_submit.calls), 0)

    def test_bridge_error_is_recorded(self):
        from phantom.bridge.models import ErrorCode

        bridge_submit = make_stub_bridge_submit(error=ErrorCode.BRIDGE_NOT_READY)
        record, *_ = _run(bridge_submit=bridge_submit)
        self.assertEqual(record.outcome, CycleOutcome.BRIDGE_ERROR)
        self.assertEqual(record.bridge_error, ErrorCode.BRIDGE_NOT_READY)

    def test_outside_trading_window_never_calls_evidence(self):
        evidence_stub = make_stub_evidence_engine()
        mi_stub = make_stub_mi_engine()
        strategy_stub = make_stub_strategy_engine()
        risk_stub = make_stub_risk_engine()
        compliance_stub = make_stub_compliance_engine()
        bridge_submit = make_stub_bridge_submit()
        orchestrator = RuntimeOrchestrator(make_config(), evidence_stub, mi_stub, strategy_stub, risk_stub, compliance_stub, bridge_submit)
        from phantom.runtime.models import TradingWindow

        narrow_profile = make_profile(trading_window=TradingWindow(start_hour_utc=1, end_hour_utc=2))
        record = orchestrator.run_cycle_for_pair(
            "EURUSD", make_bars(), (), 1.0, 1.0, make_market_safety_inputs(),
            PortfolioState(), None, make_account_state(), narrow_profile, T0, "CYCLE-1",
        )
        self.assertEqual(record.outcome, CycleOutcome.OUTSIDE_TRADING_WINDOW)
        self.assertEqual(evidence_stub.call_count, 0)

    def test_session_not_in_profile_stops_after_evidence(self):
        from phantom.evidence_engine.models import SessionName

        record, evidence_stub, mi_stub, *_ = _run()  # default snapshot session is LONDON_NEW_YORK_OVERLAP
        # Re-run with a profile only allowing ASIAN -- the fixture's session won't match.
        evidence_stub2 = make_stub_evidence_engine()
        mi_stub2 = make_stub_mi_engine()
        strategy_stub2 = make_stub_strategy_engine()
        risk_stub2 = make_stub_risk_engine()
        compliance_stub2 = make_stub_compliance_engine()
        orchestrator = RuntimeOrchestrator(make_config(), evidence_stub2, mi_stub2, strategy_stub2, risk_stub2, compliance_stub2, make_stub_bridge_submit())
        asian_only_profile = make_profile(session_rules=(SessionName.ASIAN,))
        result = orchestrator.run_cycle_for_pair(
            "EURUSD", make_bars(), (), 1.0, 1.0, make_market_safety_inputs(),
            PortfolioState(), None, make_account_state(), asian_only_profile, T0, "CYCLE-1",
        )
        self.assertEqual(result.outcome, CycleOutcome.SESSION_NOT_ALLOWED)
        self.assertEqual(mi_stub2.call_count, 0)


class TestNoDecisionAuthority(unittest.TestCase):
    def test_bridge_never_called_when_not_ready_for_bridge(self):
        reduced_but_not_ready = make_compliance_snapshot(decision=ComplianceDecision.REJECT, original_size_r=0.0)
        record, *_, bridge_submit = _run(compliance=reduced_but_not_ready)
        self.assertEqual(len(bridge_submit.calls), 0)


if __name__ == "__main__":
    unittest.main()
