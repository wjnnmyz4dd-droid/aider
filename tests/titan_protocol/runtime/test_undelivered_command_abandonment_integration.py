"""Integration test (root-cause fix: "why doesn't Titan ever trade"):
proves the real six-engine pipeline actually recovers from a command
that is submitted but never delivered to the EA (the CommandQueue-level
symptom of a persistently flaky /bridge/commands/poll transport), instead
of blocking that pair for the full in-flight TTL doing nothing.

Uses a real BridgeEngine + CommandQueue + ConnectionHealth (not a bare
stub) so `command_resolved()`/`command_delivered()` reflect genuine queue
state -- `bridge_submit` enqueues into a real CommandQueue, and this test
controls whether the EA "polls" it (via `poll_commands()`) or not,
exactly as a flaky transport would in the field."""

from __future__ import annotations

import unittest
from datetime import timedelta

from titan_protocol.bridge.command_queue import CommandQueue
from titan_protocol.bridge.connection_health import ConnectionHealth
from titan_protocol.bridge.engine import BridgeEngine
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
from tests.titan_protocol.bridge._fixtures import make_config as make_bridge_config
from tests.titan_protocol.runtime._fixtures import (
    T0,
    make_account_state,
    make_config,
    make_market_safety_inputs,
    make_profile,
    make_trending_bars,
)

_PAIR = "EURUSD"
_COMMAND_TTL_SECONDS = 15.0
_IN_FLIGHT_TTL_SECONDS = 300.0  # mirrors deployment_windows/start.py's own 20x live-cycle-interval bound


class _MutableClock:
    """A simple settable clock -- ConnectionHealth.is_ready() reads its
    own clock independently of whatever `now` a test passes into
    run_cycle_for_pair()/submit_command(), so both must agree on "now"
    for a heartbeat recorded at T to still read as fresh at T."""

    def __init__(self, at):
        self.at = at

    def __call__(self):
        return self.at


def _build_bridge_engine(clock: _MutableClock) -> BridgeEngine:
    config = make_bridge_config(command_ttl_seconds=_COMMAND_TTL_SECONDS, allowed_symbols=(_PAIR,))
    connection_health = ConnectionHealth(config, clock)
    connection_health.record_heartbeat(clock.at)
    return BridgeEngine(config, CommandQueue(config), connection_health, clock)


def _build_orchestrator(bridge_engine: BridgeEngine, in_flight_commands: InFlightCommandRegistry) -> RuntimeOrchestrator:
    def bridge_submit(command, now):
        return bridge_engine.submit_command(command, now)

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
        _PAIR, make_trending_bars(), (), 1.0, 1.0, make_market_safety_inputs(),
        PortfolioState(), None, make_account_state(), make_profile(), now, cycle_id,
    )


class TestUndeliveredCommandNoLongerBlocksTheFullTtl(unittest.TestCase):
    def test_command_never_polled_is_abandoned_and_pair_resubmits_after_grace_not_full_ttl(self):
        clock = _MutableClock(T0)
        bridge_engine = _build_bridge_engine(clock)
        registry = InFlightCommandRegistry(
            ttl_seconds=_IN_FLIGHT_TTL_SECONDS, undelivered_grace_seconds=_COMMAND_TTL_SECONDS,
        )
        orchestrator = _build_orchestrator(bridge_engine, registry)

        # 1. Compliance approves and a command is genuinely enqueued into
        # the real Bridge CommandQueue -- but the EA never polls it (the
        # flaky-transport symptom: BridgePollCommands() never succeeds).
        first = _run(orchestrator, T0, "cycle-1")
        self.assertEqual(first.outcome, CycleOutcome.SUBMITTED)
        self.assertFalse(bridge_engine.command_delivered(first.bridge_correlation_id))

        # 2. Well past command_ttl_seconds (15s) but nowhere near the
        # in-flight ttl_seconds (300s): CommandQueue.poll() would already
        # silently drop this command as stale if the EA polled now.
        past_command_ttl_not_full_ttl = T0 + timedelta(seconds=20)
        clock.at = past_command_ttl_not_full_ttl

        # 3. reconcile() (called once per live cycle in start.py, ahead of
        # this cycle's own per-pair gate) now drops the abandoned entry
        # via the undelivered-grace path -- freeing the pair immediately,
        # not after the full 300s in-flight TTL.
        registry.reconcile(
            past_command_ttl_not_full_ttl, bridge_engine.command_resolved, bridge_engine.command_delivered,
        )
        second = _run(orchestrator, past_command_ttl_not_full_ttl, "cycle-2")
        self.assertEqual(second.outcome, CycleOutcome.SUBMITTED)
        self.assertNotEqual(
            second.bridge_correlation_id, first.bridge_correlation_id,
            "the abandoned command must be replaced by a fresh submission, not silently retried under the same id",
        )

    def test_without_the_fix_the_pair_stays_blocked_long_after_the_command_already_expired(self):
        """Control case: an in-flight registry constructed the old way
        (no undelivered_grace_seconds) reproduces the pre-fix "loop never
        exits" symptom -- still blocked long after the command has
        already silently expired, undelivered, in CommandQueue."""
        clock = _MutableClock(T0)
        bridge_engine = _build_bridge_engine(clock)
        registry = InFlightCommandRegistry(ttl_seconds=_IN_FLIGHT_TTL_SECONDS)  # no undelivered_grace_seconds
        orchestrator = _build_orchestrator(bridge_engine, registry)

        first = _run(orchestrator, T0, "cycle-1")
        self.assertEqual(first.outcome, CycleOutcome.SUBMITTED)

        past_command_ttl_not_full_ttl = T0 + timedelta(seconds=20)
        clock.at = past_command_ttl_not_full_ttl
        registry.reconcile(past_command_ttl_not_full_ttl, bridge_engine.command_resolved)
        second = _run(orchestrator, past_command_ttl_not_full_ttl, "cycle-2")
        self.assertEqual(
            second.outcome, CycleOutcome.IN_FLIGHT_COMMAND_PENDING,
            "without the fix, an undelivered command keeps blocking the pair long after it has already "
            "expired undelivered in CommandQueue",
        )


if __name__ == "__main__":
    unittest.main()
