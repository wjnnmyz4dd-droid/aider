"""Integration test (fix option (b), ACCOUNT_STATE_STALE): proves the
real six-engine pipeline (not just ComplianceEngine.evaluate() in
isolation) actually blocks new entries when the account balance behind
it is stale, and resumes automatically the moment a fresh report
arrives -- no special reset/reconnect logic anywhere in the loop.

Uses the same real, unstubbed pipeline and `make_trending_bars()`
fixture as `test_position_limit_integration.py`."""

from __future__ import annotations

import unittest
from datetime import timedelta

from titan_protocol.compliance_engine.config import ComplianceEngineConfig
from titan_protocol.compliance_engine.engine import ComplianceEngine
from titan_protocol.compliance_engine.models import ComplianceRuleId
from titan_protocol.evidence_engine.config import EvidenceEngineConfig
from titan_protocol.evidence_engine.engine import EvidenceEngine
from titan_protocol.market_intelligence.config import MarketIntelligenceConfig
from titan_protocol.market_intelligence.engine import MarketIntelligenceEngine
from titan_protocol.risk_engine.config import RiskEngineConfig
from titan_protocol.risk_engine.engine import RiskEngine
from titan_protocol.risk_engine.models import PortfolioState
from titan_protocol.runtime.engine import RuntimeOrchestrator
from titan_protocol.runtime.in_flight_commands import InFlightCommandRegistry
from titan_protocol.runtime.models import CycleOutcome
from titan_protocol.strategy_engine.config import StrategyEngineConfig
from titan_protocol.strategy_engine.engine import StrategyEngine
from tests.titan_protocol.runtime._fixtures import (
    T0,
    make_account_state,
    make_config,
    make_market_safety_inputs,
    make_profile,
    make_stub_bridge_submit,
    make_trending_bars,
)

_PAIR = "EURUSD"


def _build_orchestrator(bridge_submit, in_flight_commands):
    return RuntimeOrchestrator(
        make_config(),
        EvidenceEngine(EvidenceEngineConfig()),
        MarketIntelligenceEngine(MarketIntelligenceConfig()),
        StrategyEngine(StrategyEngineConfig()),
        RiskEngine(RiskEngineConfig()),
        ComplianceEngine(ComplianceEngineConfig()),
        bridge_submit,
        in_flight_commands=in_flight_commands,
    )


def _run(orchestrator, account_state, now, cycle_id):
    return orchestrator.run_cycle_for_pair(
        _PAIR, make_trending_bars(), (), 1.0, 1.0, make_market_safety_inputs(),
        PortfolioState(), None, account_state, make_profile(), now, cycle_id,
    )


class TestAccountStateStalenessBlocksThenResumes(unittest.TestCase):
    def test_stale_account_state_rejects_then_fresh_report_resumes(self):
        submit = make_stub_bridge_submit()
        registry = InFlightCommandRegistry(ttl_seconds=300.0)
        orchestrator = _build_orchestrator(submit, registry)

        # 1. A stale account report (older than the default 30s bound)
        # blocks the new entry with ACCOUNT_STATE_STALE, never reaching
        # bridge_submit -- daily-loss/drawdown is never evaluated against
        # this stale balance.
        stale_account = make_account_state(account_report_age_seconds=90.0)
        first = _run(orchestrator, stale_account, T0, "cycle-1")
        self.assertEqual(first.outcome, CycleOutcome.COMPLIANCE_REJECTED)
        self.assertIn(ComplianceRuleId.ACCOUNT_STATE_STALE.value, first.compliance_triggered_rules)
        self.assertEqual(len(submit.calls), 0)

        # 2. A fresh account report on the very next cycle resumes normal
        # operation automatically -- no reconnect/reset call anywhere,
        # since evaluate() is a pure function of its inputs each cycle.
        fresh_account = make_account_state(account_report_age_seconds=2.0)
        second = _run(orchestrator, fresh_account, T0 + timedelta(seconds=5), "cycle-2")
        self.assertEqual(second.outcome, CycleOutcome.SUBMITTED)
        self.assertEqual(len(submit.calls), 1)


if __name__ == "__main__":
    unittest.main()
