"""Integration category (ADR-031): genuine end-to-end runs using the
five REAL engines (no stubs) -- proves the actual wiring compiles and
executes, never mocking away the real `evaluate()`/`evaluate_snapshot()`
signatures."""

from __future__ import annotations

import unittest

from titan_protocol.compliance_engine.config import ComplianceEngineConfig
from titan_protocol.compliance_engine.engine import ComplianceEngine
from titan_protocol.compliance_engine.models import ComplianceDecision
from titan_protocol.evidence_engine.config import EvidenceEngineConfig
from titan_protocol.evidence_engine.engine import EvidenceEngine
from titan_protocol.market_intelligence.config import MarketIntelligenceConfig
from titan_protocol.market_intelligence.engine import MarketIntelligenceEngine
from titan_protocol.risk_engine.config import RiskEngineConfig
from titan_protocol.risk_engine.engine import RiskEngine
from titan_protocol.risk_engine.models import PortfolioState
from titan_protocol.runtime.engine import RuntimeOrchestrator
from titan_protocol.runtime.models import CycleOutcome, CycleStage
from titan_protocol.strategy_engine.config import StrategyEngineConfig
from titan_protocol.strategy_engine.engine import StrategyEngine
from titan_protocol.strategy_engine.models import StrategyId, TradeIntent
from tests.titan_protocol.runtime._fixtures import (
    T0,
    make_account_state,
    make_bars,
    make_config,
    make_market_safety_inputs,
    make_profile,
    make_stub_bridge_submit,
    make_trending_bars,
)


def _build_real_orchestrator(bridge_submit=None):
    return RuntimeOrchestrator(
        make_config(),
        EvidenceEngine(EvidenceEngineConfig()),
        MarketIntelligenceEngine(MarketIntelligenceConfig()),
        StrategyEngine(StrategyEngineConfig()),
        RiskEngine(RiskEngineConfig()),
        ComplianceEngine(ComplianceEngineConfig()),
        bridge_submit or make_stub_bridge_submit(),
    )


class TestRealEngineWiring(unittest.TestCase):
    def test_real_pipeline_runs_without_error(self):
        orchestrator = _build_real_orchestrator()
        record = orchestrator.run_cycle_for_pair(
            "EURUSD", make_bars(count=30), (), 1.0, 1.0, make_market_safety_inputs(),
            PortfolioState(), None, make_account_state(), make_profile(), T0, "CYCLE-1",
        )
        # Flat synthetic bars qualify no strategy -- the assertion that
        # matters here is that every real engine was actually invoked
        # without raising, not which outcome a flat market produces.
        self.assertNotEqual(record.outcome, CycleOutcome.FAILED)
        self.assertTrue(len(record.stage_timings) >= 3)


class TestRealSignalEndToEnd(unittest.TestCase):
    """Upgrades the flat-bar smoke test above with a genuine trending bar
    sequence (`make_trending_bars()`) -- proves the real pipeline can
    reach a real trade, not just avoid crashing on inert data."""

    def test_trending_market_qualifies_trend_continuation_and_submits(self):
        bridge_submit = make_stub_bridge_submit()
        orchestrator = _build_real_orchestrator(bridge_submit)
        record = orchestrator.run_cycle_for_pair(
            "EURUSD", make_trending_bars(), (), 1.0, 1.0, make_market_safety_inputs(),
            PortfolioState(), None, make_account_state(), make_profile(), T0, "CYCLE-1",
        )
        self.assertEqual(record.outcome, CycleOutcome.SUBMITTED)
        self.assertEqual(record.stage_reached, CycleStage.BRIDGE)
        self.assertEqual(record.selected_strategy, StrategyId.TREND_CONTINUATION)
        self.assertEqual(record.trade_intent, TradeIntent.BUY)
        self.assertTrue(record.risk_approved)
        self.assertEqual(record.compliance_decision, ComplianceDecision.APPROVE)
        self.assertIsNone(record.bridge_error)
        self.assertEqual(len(bridge_submit.calls), 1)

    def test_trending_market_command_carries_the_derived_trade_intent(self):
        bridge_submit = make_stub_bridge_submit()
        orchestrator = _build_real_orchestrator(bridge_submit)
        orchestrator.run_cycle_for_pair(
            "EURUSD", make_trending_bars(), (), 1.0, 1.0, make_market_safety_inputs(),
            PortfolioState(), None, make_account_state(), make_profile(), T0, "CYCLE-1",
        )
        command, _now = bridge_submit.calls[0]
        self.assertEqual(command.symbol, "EURUSD")
        self.assertEqual(command.command_kind.value, "BUY")


if __name__ == "__main__":
    unittest.main()
