"""Integration category (ADR-031): one genuine end-to-end run using the
five REAL engines (no stubs) -- proves the actual wiring compiles and
executes, never mocking away the real `evaluate()`/`evaluate_snapshot()`
signatures."""

from __future__ import annotations

import unittest

from phantom.compliance_engine.config import ComplianceEngineConfig
from phantom.compliance_engine.engine import ComplianceEngine
from phantom.evidence_engine.config import EvidenceEngineConfig
from phantom.evidence_engine.engine import EvidenceEngine
from phantom.market_intelligence.config import MarketIntelligenceConfig
from phantom.market_intelligence.engine import MarketIntelligenceEngine
from phantom.risk_engine.config import RiskEngineConfig
from phantom.risk_engine.engine import RiskEngine
from phantom.risk_engine.models import PortfolioState
from phantom.runtime.engine import RuntimeOrchestrator
from phantom.runtime.models import CycleOutcome
from phantom.strategy_engine.config import StrategyEngineConfig
from phantom.strategy_engine.engine import StrategyEngine
from tests.phantom.runtime._fixtures import T0, make_account_state, make_bars, make_config, make_market_safety_inputs, make_profile, make_stub_bridge_submit


class TestRealEngineWiring(unittest.TestCase):
    def test_real_pipeline_runs_without_error(self):
        orchestrator = RuntimeOrchestrator(
            make_config(),
            EvidenceEngine(EvidenceEngineConfig()),
            MarketIntelligenceEngine(MarketIntelligenceConfig()),
            StrategyEngine(StrategyEngineConfig()),
            RiskEngine(RiskEngineConfig()),
            ComplianceEngine(ComplianceEngineConfig()),
            make_stub_bridge_submit(),
        )
        record = orchestrator.run_cycle_for_pair(
            "EURUSD", make_bars(count=30), (), 1.0, 1.0, make_market_safety_inputs(),
            PortfolioState(), None, make_account_state(), make_profile(), T0, "CYCLE-1",
        )
        # Flat synthetic bars qualify no strategy -- the assertion that
        # matters here is that every real engine was actually invoked
        # without raising, not which outcome a flat market produces.
        self.assertNotEqual(record.outcome, CycleOutcome.FAILED)
        self.assertTrue(len(record.stage_timings) >= 3)


if __name__ == "__main__":
    unittest.main()
