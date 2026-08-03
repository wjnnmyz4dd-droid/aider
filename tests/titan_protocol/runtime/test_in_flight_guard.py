"""Integration tests: RuntimeOrchestrator + InFlightCommandRegistry --
proves the actual defect traced across this session's forensic audit is
fixed: previously, run_cycle_for_pair() submitted a fresh TradeCommand
(with a new correlation_id, since it's `f"{cycle_id}:{pair}"`) every
cycle whenever compliance.ready_for_bridge stayed true, with no memory
of a command already outstanding for the same pair. Uses the same real,
unstubbed six-engine pipeline and `make_trending_bars()` fixture
`test_integration.py`'s own `TestRealSignalEndToEnd` already relies on
to reliably reach `CycleOutcome.SUBMITTED` -- not a flat/inert bar
sequence, which qualifies no strategy at all."""

from __future__ import annotations

import unittest
from datetime import timedelta

from titan_protocol.compliance_engine.config import ComplianceEngineConfig
from titan_protocol.compliance_engine.engine import ComplianceEngine
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


def _build_orchestrator(bridge_submit, in_flight_commands=None):
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


def _run(orchestrator, now, cycle_id):
    return orchestrator.run_cycle_for_pair(
        "EURUSD", make_trending_bars(), (), 1.0, 1.0, make_market_safety_inputs(),
        PortfolioState(), None, make_account_state(), make_profile(), now, cycle_id,
    )


class TestBackwardCompatibility(unittest.TestCase):
    def test_default_has_no_registry_and_no_gating(self):
        """in_flight_commands=None (the default, matching every existing
        caller/test) -- old behavior, unchanged."""
        submit = make_stub_bridge_submit()
        orchestrator = _build_orchestrator(submit)
        self.assertIsNone(orchestrator.in_flight_commands)
        first = _run(orchestrator, T0, "cycle-1")
        second = _run(orchestrator, T0 + timedelta(seconds=15), "cycle-2")
        self.assertEqual(first.outcome, CycleOutcome.SUBMITTED)
        self.assertEqual(second.outcome, CycleOutcome.SUBMITTED)
        self.assertEqual(len(submit.calls), 2, "no registry means no duplicate-prevention -- this is the pre-fix defect, reproduced deliberately")


class TestInFlightGuardPreventsDuplicateSubmission(unittest.TestCase):
    def test_second_cycle_for_same_pair_is_blocked_while_unresolved(self):
        submit = make_stub_bridge_submit()
        registry = InFlightCommandRegistry(ttl_seconds=300.0)
        orchestrator = _build_orchestrator(submit, registry)

        first = _run(orchestrator, T0, "cycle-1")
        second = _run(orchestrator, T0 + timedelta(seconds=15), "cycle-2")

        self.assertEqual(first.outcome, CycleOutcome.SUBMITTED)
        self.assertEqual(len(submit.calls), 1, "only the first cycle's command should ever reach bridge_submit")
        self.assertEqual(second.outcome, CycleOutcome.IN_FLIGHT_COMMAND_PENDING)
        self.assertEqual(second.bridge_correlation_id, first.bridge_correlation_id)
        self.assertEqual(registry.in_flight_count(), 1)

    def test_resubmission_allowed_once_registry_reconciles_as_resolved(self):
        submit = make_stub_bridge_submit()
        registry = InFlightCommandRegistry(ttl_seconds=300.0)
        orchestrator = _build_orchestrator(submit, registry)

        first = _run(orchestrator, T0, "cycle-1")
        self.assertEqual(first.outcome, CycleOutcome.SUBMITTED)

        registry.reconcile(T0, is_resolved=lambda cid: True)
        registry.confirm_position_report(T0 + timedelta(seconds=1))  # post-execution snapshot observed
        third = _run(orchestrator, T0 + timedelta(seconds=15), "cycle-3")

        self.assertEqual(third.outcome, CycleOutcome.SUBMITTED)
        self.assertEqual(len(submit.calls), 2, "resubmission must be allowed once the prior command resolved")

    def test_resubmission_allowed_after_ttl_expiry_even_if_unresolved(self):
        submit = make_stub_bridge_submit()
        registry = InFlightCommandRegistry(ttl_seconds=60.0)
        orchestrator = _build_orchestrator(submit, registry)

        first = _run(orchestrator, T0, "cycle-1")
        self.assertEqual(first.outcome, CycleOutcome.SUBMITTED)

        much_later = T0 + timedelta(seconds=61)
        registry.reconcile(much_later, is_resolved=lambda cid: False)  # still unresolved, but expired
        third = _run(orchestrator, much_later, "cycle-3")

        self.assertEqual(third.outcome, CycleOutcome.SUBMITTED)
        self.assertEqual(len(submit.calls), 2)

    def test_different_pairs_never_block_each_other(self):
        registry = InFlightCommandRegistry(ttl_seconds=300.0)
        registry.record_submission("EURUSD", "corr-1", T0)
        self.assertTrue(registry.has_unresolved("EURUSD", T0))
        self.assertFalse(registry.has_unresolved("GBPUSD", T0))

    def test_resolved_command_does_not_reopen_pair_before_position_report_confirms(self):
        """The traced ExecutionReport-vs-PositionReport race: reconcile()
        observes the command resolved, but no positions snapshot dated at
        or after that resolution has been confirmed yet -- the pair must
        stay blocked (IN_FLIGHT_COMMAND_PENDING), not silently reopen."""
        submit = make_stub_bridge_submit()
        registry = InFlightCommandRegistry(ttl_seconds=300.0)
        orchestrator = _build_orchestrator(submit, registry)

        first = _run(orchestrator, T0, "cycle-1")
        self.assertEqual(first.outcome, CycleOutcome.SUBMITTED)

        registry.reconcile(T0, is_resolved=lambda cid: True)
        # No confirm_position_report() call -- the "just resolved, but
        # position not yet visible" window.
        third = _run(orchestrator, T0 + timedelta(seconds=15), "cycle-3")

        self.assertEqual(third.outcome, CycleOutcome.IN_FLIGHT_COMMAND_PENDING)
        self.assertEqual(len(submit.calls), 1, "no second submission until a fresh position report confirms")


if __name__ == "__main__":
    unittest.main()
