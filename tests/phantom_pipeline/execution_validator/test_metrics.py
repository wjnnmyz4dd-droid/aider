"""Execution-Validator-only metrics surface (ADR-007 §11) — export-only,
additive, zero effect on returned decisions."""

from __future__ import annotations

import unittest
from datetime import timedelta

from phantom_pipeline.execution_validator.config import ExecutionValidatorConfig
from phantom_pipeline.execution_validator.engine import ExecutionValidator
from phantom_pipeline.execution_validator.idempotency_store import InMemoryIdempotencyStore
from phantom_pipeline.execution_validator.metrics import ExecutionValidatorMetrics
from phantom_pipeline.execution_validator.models import AccountState, BrokerState
from tests.phantom_pipeline.execution_validator._fixtures import (
    SYMBOL,
    T0,
    make_candidate,
    make_compliance_decision,
    make_market_snapshot,
    make_risk_decision,
    make_score_result,
)

NOMINAL_CONFIG = ExecutionValidatorConfig(max_spread={SYMBOL: 0.0005})
NOMINAL_NOW = T0 + timedelta(seconds=1)


def _nominal_inputs():
    candidate = make_candidate()
    score_result = make_score_result(candidate)
    risk_decision = make_risk_decision(candidate, score_result)
    compliance_decision = make_compliance_decision(candidate, score_result, risk_decision)
    return (
        compliance_decision,
        risk_decision,
        score_result,
        candidate,
        make_market_snapshot(),
        BrokerState(connected=True, symbol_tradable=True),
        AccountState(equity=10000.0, available_margin=5000.0),
        NOMINAL_NOW,
        1.1000,
        1.0950,
        1.1100,
    )


class TestExecutionValidatorMetrics(unittest.TestCase):
    def test_decisions_counted_by_verdict(self):
        metrics = ExecutionValidatorMetrics()
        engine = ExecutionValidator(InMemoryIdempotencyStore(300.0), NOMINAL_CONFIG, metrics=metrics)

        decision = engine.validate(*_nominal_inputs())

        self.assertEqual(metrics.decisions_by_verdict.get(decision.verdict.value), 1)

    def test_duplicate_prevention_count_increments(self):
        metrics = ExecutionValidatorMetrics()
        engine = ExecutionValidator(InMemoryIdempotencyStore(300.0), NOMINAL_CONFIG, metrics=metrics)
        inputs = _nominal_inputs()

        engine.validate(*inputs)
        engine.validate(*inputs)

        self.assertEqual(metrics.duplicate_prevention_count, 1)

    def test_blocks_counted_by_every_triggering_check(self):
        metrics = ExecutionValidatorMetrics()
        engine = ExecutionValidator(InMemoryIdempotencyStore(300.0), NOMINAL_CONFIG, metrics=metrics)
        inputs = list(_nominal_inputs())
        inputs[5] = BrokerState(connected=False, symbol_tradable=False)  # 2 simultaneous failures

        engine.validate(*inputs)

        self.assertEqual(metrics.blocks_by_check.get("BROKER_CONNECTION_HEALTHY"), 1)
        self.assertEqual(metrics.blocks_by_check.get("SYMBOL_TRADABLE"), 1)

    def test_approval_rate_reflects_recorded_decisions(self):
        metrics = ExecutionValidatorMetrics()
        engine = ExecutionValidator(InMemoryIdempotencyStore(300.0), NOMINAL_CONFIG, metrics=metrics)

        engine.validate(*_nominal_inputs())

        self.assertEqual(metrics.approval_rate, 1.0)

    def test_recording_metrics_never_alters_returned_decision(self):
        inputs = _nominal_inputs()
        without_metrics = ExecutionValidator(InMemoryIdempotencyStore(300.0), NOMINAL_CONFIG).validate(*inputs)
        with_metrics = ExecutionValidator(
            InMemoryIdempotencyStore(300.0), NOMINAL_CONFIG, metrics=ExecutionValidatorMetrics()
        ).validate(*inputs)

        self.assertEqual(without_metrics, with_metrics)

    def test_snapshots_are_copies_not_live_views(self):
        metrics = ExecutionValidatorMetrics()
        engine = ExecutionValidator(InMemoryIdempotencyStore(300.0), NOMINAL_CONFIG, metrics=metrics)
        engine.validate(*_nominal_inputs())

        snapshot = metrics.decisions_by_verdict
        snapshot["INJECTED"] = 999
        self.assertNotIn("INJECTED", metrics.decisions_by_verdict)


if __name__ == "__main__":
    unittest.main()
