"""Structured logging emission tests (ADR-006 §16)."""

from __future__ import annotations

import logging
import unittest

from phantom_pipeline.compliance_engine.config import ComplianceEngineConfig
from phantom_pipeline.compliance_engine.config import COMPLIANCE_ENGINE_VERSION
from phantom_pipeline.compliance_engine.engine import ComplianceEngine
from phantom_pipeline.compliance_engine.logging_sink import logger
from phantom_pipeline.compliance_engine.models import NewsCalendarState
from phantom_pipeline.compliance_engine.state_store import InMemoryComplianceStateStore
from tests.phantom_pipeline.compliance_engine._fixtures import (
    SYMBOL,
    make_account_state,
    make_candidate,
    make_market_snapshot,
    make_risk_decision,
    make_score_result,
)

NOMINAL_CONFIG = ComplianceEngineConfig(
    spread_thresholds={SYMBOL: 0.0005}, slippage_thresholds={SYMBOL: 0.0005}
)


class _CapturingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


class TestComplianceDecisionLogging(unittest.TestCase):
    def setUp(self):
        self.handler = _CapturingHandler()
        logger.addHandler(self.handler)
        logger.setLevel(logging.DEBUG)
        self.previous_propagate = logger.propagate
        logger.propagate = False

    def tearDown(self):
        logger.removeHandler(self.handler)
        logger.propagate = self.previous_propagate

    def _nominal_inputs(self):
        candidate = make_candidate()
        score_result = make_score_result(candidate)
        risk_decision = make_risk_decision(candidate, score_result)
        account = make_account_state()
        snapshot = make_market_snapshot()
        news = NewsCalendarState(feed_stale=False, blackout_windows=())
        return risk_decision, candidate, score_result, account, snapshot, news

    def test_compliance_decision_emission_carries_all_required_fields(self):
        engine = ComplianceEngine(InMemoryComplianceStateStore(), NOMINAL_CONFIG)
        self.handler.records.clear()

        decision = engine.evaluate(*self._nominal_inputs(), expected_slippage=0.0001)

        decision_records = [
            r for r in self.handler.records if r.msg == "compliance_engine.compliance_decision"
        ]
        self.assertEqual(len(decision_records), 1)
        record = decision_records[0]
        self.assertEqual(record.trace_id, decision.trace_id)
        self.assertEqual(record.schema_version, decision.schema_version)
        self.assertEqual(record.candidate_id, decision.candidate_id)
        self.assertEqual(record.compliance_engine_version, COMPLIANCE_ENGINE_VERSION)
        self.assertEqual(record.verdict, decision.verdict.value)
        self.assertEqual(record.blocking_rules, list(decision.blocking_rules))
        self.assertEqual(record.reason_codes, list(decision.reason_codes))

    def test_check_evaluation_is_logged_at_a_distinct_granularity(self):
        engine = ComplianceEngine(InMemoryComplianceStateStore(), NOMINAL_CONFIG)
        self.handler.records.clear()

        engine.evaluate(*self._nominal_inputs(), expected_slippage=0.0001)

        check_records = [r for r in self.handler.records if r.msg == "compliance_engine.check_evaluation"]
        self.assertEqual(len(check_records), 9)  # 9 checks, ADR-006 §6-§14

    def test_kill_switch_trigger_is_logged_distinctly(self):
        engine = ComplianceEngine(InMemoryComplianceStateStore(), NOMINAL_CONFIG)
        risk_decision, candidate, score_result, _, snapshot, news = self._nominal_inputs()
        breached_account = make_account_state(total_drawdown_pct=9.0)
        self.handler.records.clear()

        engine.evaluate(risk_decision, candidate, score_result, breached_account, snapshot, news)

        kill_switch_records = [
            r for r in self.handler.records if r.msg == "compliance_engine.kill_switch_triggered"
        ]
        self.assertEqual(len(kill_switch_records), 1)
        self.assertEqual(kill_switch_records[0].reason, "total_drawdown_breach")

    def test_daily_lockout_trigger_is_logged_distinctly(self):
        engine = ComplianceEngine(InMemoryComplianceStateStore(), NOMINAL_CONFIG)
        risk_decision, candidate, score_result, _, snapshot, news = self._nominal_inputs()
        breached_account = make_account_state(daily_drawdown_pct=5.0)
        self.handler.records.clear()

        engine.evaluate(risk_decision, candidate, score_result, breached_account, snapshot, news)

        lockout_records = [
            r for r in self.handler.records if r.msg == "compliance_engine.daily_lockout_triggered"
        ]
        self.assertEqual(len(lockout_records), 1)
        self.assertEqual(lockout_records[0].reason, "daily_drawdown_breach")

    def test_malformed_request_is_logged(self):
        engine = ComplianceEngine(InMemoryComplianceStateStore(), NOMINAL_CONFIG)
        risk_decision, _, score_result, account, snapshot, news = self._nominal_inputs()
        mismatched_candidate = make_candidate(trace_id="different-trace")
        self.handler.records.clear()

        engine.evaluate(risk_decision, mismatched_candidate, score_result, account, snapshot, news)

        malformed_records = [
            r for r in self.handler.records if r.msg == "compliance_engine.malformed_request"
        ]
        self.assertEqual(len(malformed_records), 1)
        self.assertEqual(malformed_records[0].reason, "candidate_mismatch")

    def test_logging_never_alters_engine_output(self):
        risk_decision, candidate, score_result, account, snapshot, news = self._nominal_inputs()

        logger.removeHandler(self.handler)
        silent = ComplianceEngine(InMemoryComplianceStateStore(), NOMINAL_CONFIG).evaluate(
            risk_decision, candidate, score_result, account, snapshot, news, expected_slippage=0.0001
        )

        logger.addHandler(self.handler)
        observed = ComplianceEngine(InMemoryComplianceStateStore(), NOMINAL_CONFIG).evaluate(
            risk_decision, candidate, score_result, account, snapshot, news, expected_slippage=0.0001
        )

        self.assertEqual(silent, observed)


if __name__ == "__main__":
    unittest.main()
