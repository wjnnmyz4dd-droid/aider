"""Integration test (item 6 of the position-limit fix): proves the full,
real six-engine pipeline actually enforces "never more than one open
position per pair" end-to-end, not just at the unit level --

  1. first command submits (compliance sees zero positions)
  2. its ExecutionReport resolves the in-flight entry
  3. a PositionReport confirms one open position for the pair
  4. the next signal for the same pair is rejected by compliance
     (MAX_POSITIONS_PER_PAIR_EXCEEDED), never reaching bridge_submit
  5. the outcome/reason clearly identifies the position-limit rejection

Uses the same real, unstubbed pipeline and `make_trending_bars()`
fixture as `test_in_flight_guard.py`."""

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
from titan_protocol.risk_engine.models import Direction, OpenPosition, PortfolioState
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


def _run(orchestrator, portfolio_state, now, cycle_id):
    return orchestrator.run_cycle_for_pair(
        _PAIR, make_trending_bars(), (), 1.0, 1.0, make_market_safety_inputs(),
        portfolio_state, None, make_account_state(), make_profile(), now, cycle_id,
    )


class TestPositionLimitRejectsSecondEntry(unittest.TestCase):
    def test_full_lifecycle_second_signal_rejected_by_compliance(self):
        submit = make_stub_bridge_submit()
        registry = InFlightCommandRegistry(ttl_seconds=300.0)
        orchestrator = _build_orchestrator(submit, registry)

        # 1. First command submits -- compliance sees zero positions.
        first = _run(orchestrator, PortfolioState(), T0, "cycle-1")
        self.assertEqual(first.outcome, CycleOutcome.SUBMITTED)
        self.assertEqual(len(submit.calls), 1)

        # 2. Its ExecutionReport resolves the in-flight entry.
        registry.reconcile(T0, is_resolved=lambda cid: True)

        # 3. A PositionReport (via the caller-owned adapter, simulated
        # here as an already-mapped OpenPosition -- the adapter itself is
        # covered by tests/deployment_windows/test_start_portfolio_state.py)
        # confirms one open position for the pair, dated after resolution.
        position_report_at = T0 + timedelta(seconds=2)
        registry.confirm_position_report(position_report_at)
        portfolio_with_one_open_position = PortfolioState(
            open_positions=(OpenPosition(pair=_PAIR, direction=Direction.LONG, size_r=1.0, opened_at=position_report_at),)
        )

        # 4. The next signal for the same pair is rejected by compliance,
        # never reaching bridge_submit.
        second = _run(orchestrator, portfolio_with_one_open_position, T0 + timedelta(seconds=15), "cycle-2")

        self.assertEqual(second.outcome, CycleOutcome.COMPLIANCE_REJECTED)
        self.assertEqual(len(submit.calls), 1, "bridge_submit must not be called for the rejected second signal")

        # 5. The outcome clearly reports the position-limit rejection.
        self.assertIn(ComplianceRuleId.MAX_POSITIONS_PER_PAIR_EXCEEDED.value, second.reasons[0])


if __name__ == "__main__":
    unittest.main()
