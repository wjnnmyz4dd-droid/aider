"""Structured logging emission (ADR-005 §16)."""

from __future__ import annotations

import logging
import unittest

from phantom_pipeline.risk_engine.config import RISK_ENGINE_VERSION, RiskEngineConfig
from phantom_pipeline.risk_engine.engine import RiskEngine
from phantom_pipeline.risk_engine.logging_sink import logger
from tests.phantom_pipeline.risk_engine._fixtures import (
    SYMBOL,
    make_account_state,
    make_candidate,
    make_score_result,
    nominal_observation,
)


class _CapturingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


class TestRiskDecisionLogging(unittest.TestCase):
    def setUp(self):
        self.handler = _CapturingHandler()
        logger.addHandler(self.handler)
        logger.setLevel(logging.DEBUG)
        self.previous_propagate = logger.propagate
        logger.propagate = False

    def tearDown(self):
        logger.removeHandler(self.handler)
        logger.propagate = self.previous_propagate

    def test_risk_decision_emission_carries_all_required_fields(self):
        candidate = make_candidate()
        score_result = make_score_result(candidate)
        observation = nominal_observation()
        engine = RiskEngine(RiskEngineConfig(correlation_buckets={SYMBOL: "MAJORS"}))
        self.handler.records.clear()

        decision = engine.decide(score_result, candidate, observation, make_account_state())

        decision_records = [r for r in self.handler.records if r.msg == "risk_engine.risk_decision"]
        self.assertEqual(len(decision_records), 1)
        record = decision_records[0]
        self.assertEqual(record.trace_id, decision.trace_id)
        self.assertEqual(record.schema_version, decision.schema_version)
        self.assertEqual(record.candidate_id, decision.candidate_id)
        self.assertEqual(record.risk_engine_version, RISK_ENGINE_VERSION)
        self.assertEqual(record.approved_risk_amount, decision.approved_risk_amount)
        self.assertEqual(record.approved_risk_percent, decision.approved_risk_percent)
        self.assertEqual(record.limiting_constraint, decision.limiting_constraint)
        self.assertEqual(record.reason_codes, list(decision.reason_codes))

    def test_constraint_evaluation_is_logged_at_a_distinct_granularity(self):
        candidate = make_candidate()
        score_result = make_score_result(candidate)
        observation = nominal_observation()
        engine = RiskEngine(RiskEngineConfig(correlation_buckets={SYMBOL: "MAJORS"}))
        self.handler.records.clear()

        engine.decide(score_result, candidate, observation, make_account_state())

        constraint_records = [
            r for r in self.handler.records if r.msg == "risk_engine.constraint_evaluation"
        ]
        self.assertEqual(len(constraint_records), 8)  # 8 constraints, ADR-005 §6-§14

    def test_fail_closed_trigger_is_logged(self):
        candidate = make_candidate()
        score_result = make_score_result(candidate)
        observation = nominal_observation()
        engine = RiskEngine()
        self.handler.records.clear()

        engine.decide(score_result, candidate, observation, None)

        fail_closed_records = [r for r in self.handler.records if r.msg == "risk_engine.fail_closed"]
        self.assertEqual(len(fail_closed_records), 1)
        self.assertEqual(fail_closed_records[0].reason, "missing_account_state")

    def test_logging_never_alters_engine_output(self):
        candidate = make_candidate()
        score_result = make_score_result(candidate)
        observation = nominal_observation()
        config = RiskEngineConfig(correlation_buckets={SYMBOL: "MAJORS"})
        account = make_account_state()

        logger.removeHandler(self.handler)
        silent = RiskEngine(config).decide(score_result, candidate, observation, account)

        logger.addHandler(self.handler)
        observed = RiskEngine(config).decide(score_result, candidate, observation, account)

        self.assertEqual(silent, observed)


if __name__ == "__main__":
    unittest.main()
