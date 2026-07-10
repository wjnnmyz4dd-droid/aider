"""Regression category: determinism -- identical inputs (including a
fixed `Clock`) produce an identical decision on every run. Timing
fields (`duration_ms`, `stage_timings`) are real wall-clock telemetry
and are excluded from the comparison (ADR-031's own SS3 note: they are
operational metrics, not decisions)."""

from __future__ import annotations

import dataclasses
import unittest

from phantom.risk_engine.models import PortfolioState
from phantom.runtime.engine import RuntimeOrchestrator
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


def _decision_fields(record):
    return dataclasses.replace(record, duration_ms=0.0, stage_timings=())


class TestDeterminism(unittest.TestCase):
    def test_repeated_calls_produce_identical_decisions(self):
        orchestrator = RuntimeOrchestrator(
            make_config(), make_stub_evidence_engine(), make_stub_mi_engine(), make_stub_strategy_engine(),
            make_stub_risk_engine(), make_stub_compliance_engine(), make_stub_bridge_submit(),
        )
        profile = make_profile()
        results = [
            _decision_fields(orchestrator.run_cycle_for_pair(
                "EURUSD", make_bars(), (), 1.0, 1.0, make_market_safety_inputs(),
                PortfolioState(), None, make_account_state(), profile, T0, "CYCLE-1",
            ))
            for _ in range(10)
        ]
        first = results[0]
        for result in results:
            self.assertEqual(result, first)

    def test_two_independent_orchestrators_agree(self):
        def build():
            return RuntimeOrchestrator(
                make_config(), make_stub_evidence_engine(), make_stub_mi_engine(), make_stub_strategy_engine(),
                make_stub_risk_engine(), make_stub_compliance_engine(), make_stub_bridge_submit(),
            )

        profile = make_profile()
        record_a = build().run_cycle_for_pair(
            "EURUSD", make_bars(), (), 1.0, 1.0, make_market_safety_inputs(),
            PortfolioState(), None, make_account_state(), profile, T0, "CYCLE-1",
        )
        record_b = build().run_cycle_for_pair(
            "EURUSD", make_bars(), (), 1.0, 1.0, make_market_safety_inputs(),
            PortfolioState(), None, make_account_state(), profile, T0, "CYCLE-1",
        )
        self.assertEqual(_decision_fields(record_a), _decision_fields(record_b))


if __name__ == "__main__":
    unittest.main()
