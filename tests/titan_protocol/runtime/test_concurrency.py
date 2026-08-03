"""Concurrency category (ADR-031 SS10): `RuntimeOrchestrator` holds no
mutable per-call state, so concurrent `run_cycle_for_pair()` calls
against one shared instance must never error and must always agree."""

from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor

from titan_protocol.risk_engine.models import PortfolioState
from titan_protocol.runtime.engine import RuntimeOrchestrator
from tests.titan_protocol.runtime._fixtures import (
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


def _build_orchestrator():
    return RuntimeOrchestrator(
        make_config(), make_stub_evidence_engine(), make_stub_mi_engine(), make_stub_strategy_engine(),
        make_stub_risk_engine(), make_stub_compliance_engine(), make_stub_bridge_submit(),
    )


class TestConcurrentCycles(unittest.TestCase):
    def test_concurrent_calls_across_many_threads_no_errors(self):
        orchestrator = _build_orchestrator()
        profile = make_profile()
        errors = []

        def worker(_):
            try:
                orchestrator.run_cycle_for_pair(
                    "EURUSD", make_bars(), (), 1.0, 1.0, make_market_safety_inputs(),
                    PortfolioState(), None, make_account_state(), profile, T0, "CYCLE-1",
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))

        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(worker, range(32)))

        self.assertEqual(errors, [])

    def test_concurrent_calls_produce_consistent_decisions(self):
        orchestrator = _build_orchestrator()
        profile = make_profile()
        results = []

        def worker(_):
            record = orchestrator.run_cycle_for_pair(
                "EURUSD", make_bars(), (), 1.0, 1.0, make_market_safety_inputs(),
                PortfolioState(), None, make_account_state(), profile, T0, "CYCLE-1",
            )
            results.append((record.outcome, record.stage_reached, record.trade_intent, record.selected_strategy))

        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(worker, range(32)))

        first = results[0]
        for result in results:
            self.assertEqual(result, first)


if __name__ == "__main__":
    unittest.main()
