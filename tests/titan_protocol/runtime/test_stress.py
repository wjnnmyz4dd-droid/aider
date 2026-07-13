"""Stress category (ADR-031 SS10): a large multi-pair, multi-outcome
cycle exercised at once."""

from __future__ import annotations

import unittest

from titan_protocol.compliance_engine.models import ComplianceDecision
from titan_protocol.risk_engine.config import RiskEngineConfig
from titan_protocol.risk_engine.models import PortfolioState
from titan_protocol.runtime.engine import RuntimeOrchestrator
from titan_protocol.runtime.models import CycleOutcome, TradingWindow
from titan_protocol.runtime.profiles import make_custom_profile
from tests.titan_protocol.runtime._fixtures import (
    T0,
    make_account_state,
    make_bars,
    make_compliance_snapshot,
    make_config,
    make_market_safety_inputs,
    make_stub_bridge_submit,
    make_stub_compliance_engine,
    make_stub_evidence_engine,
    make_stub_mi_engine,
    make_stub_risk_engine,
    make_stub_strategy_engine,
)

_PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD"]


def _wide_open_profile(profile_id: str, allowed_pairs=None) -> object:
    return make_custom_profile(
        profile_id=profile_id, description="stress test", trading_window=TradingWindow(0, 24),
        session_rules=(), risk_profile=RiskEngineConfig(),
        allowed_pairs=allowed_pairs if allowed_pairs is not None else tuple(_PAIRS * 4)[:28],
    )


class TestLargeMultiPairCycle(unittest.TestCase):
    def test_28_pair_repeated_cycle_produces_no_errors(self):
        orchestrator = RuntimeOrchestrator(
            make_config(), make_stub_evidence_engine(), make_stub_mi_engine(), make_stub_strategy_engine(),
            make_stub_risk_engine(), make_stub_compliance_engine(), make_stub_bridge_submit(),
        )
        profile = _wide_open_profile("stress")
        records = []
        for i, pair in enumerate(profile.allowed_pairs):
            record = orchestrator.run_cycle_for_pair(
                pair, make_bars(), (), 1.0, 1.0, make_market_safety_inputs(),
                PortfolioState(), None, make_account_state(), profile, T0, f"CYCLE-{i}",
            )
            records.append(record)
        self.assertEqual(len(records), 28)
        self.assertTrue(all(r.outcome != CycleOutcome.FAILED for r in records))

    def test_mixed_outcomes_across_many_cycles_each_isolated(self):
        outcomes_seen = set()
        for decision in (ComplianceDecision.APPROVE, ComplianceDecision.REJECT):
            evidence_stub = make_stub_evidence_engine()
            mi_stub = make_stub_mi_engine()
            strategy_stub = make_stub_strategy_engine()
            risk_stub = make_stub_risk_engine()
            compliance_stub = make_stub_compliance_engine(make_compliance_snapshot(decision=decision, original_size_r=1.25))
            orchestrator = RuntimeOrchestrator(make_config(), evidence_stub, mi_stub, strategy_stub, risk_stub, compliance_stub, make_stub_bridge_submit())
            profile = _wide_open_profile("stress2", allowed_pairs=("EURUSD",))
            record = orchestrator.run_cycle_for_pair(
                "EURUSD", make_bars(), (), 1.0, 1.0, make_market_safety_inputs(),
                PortfolioState(), None, make_account_state(), profile, T0, "CYCLE-X",
            )
            outcomes_seen.add(record.outcome)
        self.assertEqual(outcomes_seen, {CycleOutcome.SUBMITTED, CycleOutcome.COMPLIANCE_REJECTED})


if __name__ == "__main__":
    unittest.main()
