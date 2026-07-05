"""Structured logging emission tests (ADR-007 §10)."""

from __future__ import annotations

import logging
import unittest
from datetime import timedelta

from phantom_pipeline.execution_validator.config import EXECUTION_VALIDATOR_VERSION, ExecutionValidatorConfig
from phantom_pipeline.execution_validator.engine import ExecutionValidator
from phantom_pipeline.execution_validator.idempotency_store import InMemoryIdempotencyStore
from phantom_pipeline.execution_validator.logging_sink import logger
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


class _CapturingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


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


class TestExecutionDecisionLogging(unittest.TestCase):
    def setUp(self):
        self.handler = _CapturingHandler()
        logger.addHandler(self.handler)
        logger.setLevel(logging.DEBUG)
        self.previous_propagate = logger.propagate
        logger.propagate = False

    def tearDown(self):
        logger.removeHandler(self.handler)
        logger.propagate = self.previous_propagate

    def test_execution_decision_emission_carries_all_required_fields(self):
        engine = ExecutionValidator(InMemoryIdempotencyStore(300.0), NOMINAL_CONFIG)
        self.handler.records.clear()

        decision = engine.validate(*_nominal_inputs())

        decision_records = [r for r in self.handler.records if r.msg == "execution_validator.execution_decision"]
        self.assertEqual(len(decision_records), 1)
        record = decision_records[0]
        self.assertEqual(record.trace_id, decision.trace_id)
        self.assertEqual(record.schema_version, decision.schema_version)
        self.assertEqual(record.candidate_id, decision.candidate_id)
        self.assertEqual(record.execution_validator_version, EXECUTION_VALIDATOR_VERSION)
        self.assertEqual(record.verdict, decision.verdict.value)
        self.assertEqual(record.blocking_reasons, list(decision.blocking_reasons))
        self.assertEqual(record.reason_codes, list(decision.reason_codes))
        self.assertEqual(record.warnings, list(decision.warnings))

    def test_check_evaluation_is_logged_at_a_distinct_granularity(self):
        engine = ExecutionValidator(InMemoryIdempotencyStore(300.0), NOMINAL_CONFIG)
        self.handler.records.clear()

        engine.validate(*_nominal_inputs())

        check_records = [r for r in self.handler.records if r.msg == "execution_validator.check_evaluation"]
        self.assertEqual(len(check_records), 19)

    def test_rejection_is_logged_with_reason_timestamp_trace_id_and_stage(self):
        engine = ExecutionValidator(InMemoryIdempotencyStore(300.0), NOMINAL_CONFIG)
        inputs = list(_nominal_inputs())
        inputs[5] = BrokerState(connected=False, symbol_tradable=True)
        self.handler.records.clear()

        engine.validate(*inputs)

        rejection_records = [r for r in self.handler.records if r.msg == "execution_validator.rejection"]
        self.assertEqual(len(rejection_records), 1)
        record = rejection_records[0]
        self.assertEqual(record.reason, "BROKER_CONNECTION_HEALTHY")
        self.assertEqual(record.validation_stage, "BROKER_CONNECTION_HEALTHY")
        self.assertIsNotNone(record.timestamp)
        self.assertIsNotNone(record.trace_id)

    def test_logging_never_alters_engine_output(self):
        inputs = _nominal_inputs()

        logger.removeHandler(self.handler)
        silent = ExecutionValidator(InMemoryIdempotencyStore(300.0), NOMINAL_CONFIG).validate(*inputs)

        logger.addHandler(self.handler)
        observed = ExecutionValidator(InMemoryIdempotencyStore(300.0), NOMINAL_CONFIG).validate(*inputs)

        self.assertEqual(silent, observed)


if __name__ == "__main__":
    unittest.main()
