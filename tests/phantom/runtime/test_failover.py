"""Failover category (ADR-031 SS8): fail closed -- an unexpected
exception mid-cycle is caught, recorded as FAILED, and never propagates
or produces a partial `TradeCommand`. Other pairs are unaffected."""

from __future__ import annotations

import unittest

from phantom.risk_engine.models import PortfolioState
from phantom.runtime.engine import RuntimeOrchestrator
from phantom.runtime.models import CycleOutcome, CycleStage
from tests.phantom.runtime._fixtures import (
    T0,
    make_account_state,
    make_bars,
    make_config,
    make_market_safety_inputs,
    make_profile,
    make_stub_bridge_submit,
    make_stub_compliance_engine,
    make_stub_evidence_engine,
    make_stub_mi_engine,
    make_stub_risk_engine,
    make_stub_strategy_engine,
)


class _RaisingStub:
    def evaluate(self, *args, **kwargs):
        raise RuntimeError("simulated engine failure")

    evaluate_snapshot = evaluate


class TestUnknownEngineState(unittest.TestCase):
    def test_evidence_engine_exception_yields_failed_outcome(self):
        bridge_submit = make_stub_bridge_submit()
        orchestrator = RuntimeOrchestrator(
            make_config(), _RaisingStub(), make_stub_mi_engine(), make_stub_strategy_engine(),
            make_stub_risk_engine(), make_stub_compliance_engine(), bridge_submit,
        )
        record = orchestrator.run_cycle_for_pair(
            "EURUSD", make_bars(), (), 1.0, 1.0, make_market_safety_inputs(),
            PortfolioState(), None, make_account_state(), make_profile(), T0, "CYCLE-1",
        )
        self.assertEqual(record.outcome, CycleOutcome.FAILED)
        self.assertEqual(record.stage_reached, CycleStage.EVIDENCE)
        self.assertTrue(record.reasons)
        self.assertEqual(len(bridge_submit.calls), 0)

    def test_strategy_engine_exception_never_reaches_bridge(self):
        bridge_submit = make_stub_bridge_submit()
        orchestrator = RuntimeOrchestrator(
            make_config(), make_stub_evidence_engine(), make_stub_mi_engine(), _RaisingStub(),
            make_stub_risk_engine(), make_stub_compliance_engine(), bridge_submit,
        )
        record = orchestrator.run_cycle_for_pair(
            "EURUSD", make_bars(), (), 1.0, 1.0, make_market_safety_inputs(),
            PortfolioState(), None, make_account_state(), make_profile(), T0, "CYCLE-1",
        )
        self.assertEqual(record.outcome, CycleOutcome.FAILED)
        self.assertEqual(record.stage_reached, CycleStage.STRATEGY)
        self.assertEqual(len(bridge_submit.calls), 0)

    def test_one_pair_failing_does_not_affect_another_pairs_cycle(self):
        orchestrator = RuntimeOrchestrator(
            make_config(), make_stub_evidence_engine(), make_stub_mi_engine(), make_stub_strategy_engine(),
            make_stub_risk_engine(), make_stub_compliance_engine(), make_stub_bridge_submit(),
        )
        profile = make_profile(allowed_pairs=("EURUSD", "GBPUSD"))
        good_record = orchestrator.run_cycle_for_pair(
            "GBPUSD", make_bars(), (), 1.0, 1.0, make_market_safety_inputs(),
            PortfolioState(), None, make_account_state(), profile, T0, "CYCLE-2",
        )
        self.assertNotEqual(good_record.outcome, CycleOutcome.FAILED)


if __name__ == "__main__":
    unittest.main()
