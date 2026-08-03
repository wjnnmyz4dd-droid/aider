"""ExecutionValidator.validate()/validate_batch() tests (ADR-007 §2-§12)."""

from __future__ import annotations

import unittest
from datetime import timedelta

from phantom_pipeline.execution_validator.config import ExecutionValidatorConfig
from phantom_pipeline.execution_validator.engine import ExecutionValidator
from phantom_pipeline.execution_validator.idempotency_store import InMemoryIdempotencyStore
from phantom_pipeline.execution_validator.models import AccountState, BrokerState, CheckStatus, Verdict
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


def _nominal_engine():
    return ExecutionValidator(InMemoryIdempotencyStore(300.0), NOMINAL_CONFIG)


def _nominal_inputs():
    candidate = make_candidate()
    score_result = make_score_result(candidate)
    risk_decision = make_risk_decision(candidate, score_result)
    compliance_decision = make_compliance_decision(candidate, score_result, risk_decision)
    snapshot = make_market_snapshot()
    broker = BrokerState(connected=True, symbol_tradable=True)
    account = AccountState(equity=10000.0, available_margin=5000.0)
    return (
        compliance_decision,
        risk_decision,
        score_result,
        candidate,
        snapshot,
        broker,
        account,
        NOMINAL_NOW,
        1.1000,
        1.0950,
        1.1100,
    )


class TestNominalApproval(unittest.TestCase):
    def test_all_checks_pass_yields_approve(self):
        engine = _nominal_engine()
        result = engine.validate(*_nominal_inputs())
        self.assertEqual(result.verdict, Verdict.APPROVE)
        self.assertEqual(result.blocking_reasons, ())
        self.assertEqual(len(result.check_evaluations), 19)


class TestOneDecisionPerComplianceDecision(unittest.TestCase):
    def test_validate_always_returns_exactly_one_decision(self):
        engine = _nominal_engine()
        result = engine.validate(*_nominal_inputs())
        self.assertIsNotNone(result)

    def test_validate_batch_never_discards(self):
        engine = _nominal_engine()
        requests = []
        for i in range(3):
            candidate = make_candidate(trace_id=f"trace-{i}")
            score_result = make_score_result(candidate)
            risk_decision = make_risk_decision(candidate, score_result)
            compliance_decision = make_compliance_decision(candidate, score_result, risk_decision)
            requests.append(
                (
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
            )
        results = engine.validate_batch(requests)
        self.assertEqual(len(results), 3)


class TestDeterminism(unittest.TestCase):
    def test_same_inputs_same_decision(self):
        inputs = _nominal_inputs()
        first = ExecutionValidator(InMemoryIdempotencyStore(300.0), NOMINAL_CONFIG).validate(*inputs)
        second = ExecutionValidator(InMemoryIdempotencyStore(300.0), NOMINAL_CONFIG).validate(*inputs)
        self.assertEqual(first, second)

    def test_replay_determinism_across_fresh_engines(self):
        results = []
        for _ in range(3):
            engine = ExecutionValidator(InMemoryIdempotencyStore(300.0), NOMINAL_CONFIG)
            results.append(engine.validate(*_nominal_inputs()))
        self.assertTrue(all(r == results[0] for r in results))


class TestTraceIdAndCandidateIdPropagation(unittest.TestCase):
    def test_trace_id_and_candidate_id_match_candidate(self):
        engine = _nominal_engine()
        inputs = _nominal_inputs()
        candidate = inputs[3]
        result = engine.validate(*inputs)
        self.assertEqual(result.trace_id, candidate.trace_id)
        self.assertEqual(result.candidate_id, candidate.candidate_id)


class TestDuplicatePrevention(unittest.TestCase):
    def test_second_identical_request_is_rejected(self):
        engine = _nominal_engine()
        inputs = _nominal_inputs()
        first = engine.validate(*inputs)
        self.assertEqual(first.verdict, Verdict.APPROVE)

        second = engine.validate(*inputs)
        self.assertEqual(second.verdict, Verdict.REJECT)
        self.assertIn("NO_DUPLICATE_REQUEST", second.blocking_reasons)


class TestStaleTradeRejection(unittest.TestCase):
    def test_beyond_max_order_age_is_rejected(self):
        config = ExecutionValidatorConfig(max_spread={SYMBOL: 0.0005}, max_order_age_seconds=1.0)
        engine = ExecutionValidator(InMemoryIdempotencyStore(300.0), config)
        inputs = list(_nominal_inputs())
        inputs[7] = T0 + timedelta(seconds=10)  # `now` far beyond max_order_age_seconds

        result = engine.validate(*inputs)

        self.assertEqual(result.verdict, Verdict.REJECT)
        self.assertIn("TRADE_NOT_STALE", result.blocking_reasons)


class TestBrokerDisconnect(unittest.TestCase):
    def test_unreachable_broker_is_rejected_not_a_hang(self):
        engine = _nominal_engine()
        inputs = list(_nominal_inputs())
        inputs[5] = BrokerState(connected=False, symbol_tradable=True)

        result = engine.validate(*inputs)

        self.assertEqual(result.verdict, Verdict.REJECT)
        self.assertIn("BROKER_CONNECTION_HEALTHY", result.blocking_reasons)


class TestSpreadDrift(unittest.TestCase):
    def test_wide_spread_is_rejected(self):
        engine = _nominal_engine()
        inputs = list(_nominal_inputs())
        inputs[4] = make_market_snapshot(spread=0.01)

        result = engine.validate(*inputs)

        self.assertEqual(result.verdict, Verdict.REJECT)
        self.assertIn("SPREAD_UNCHANGED", result.blocking_reasons)


class TestSlippageDrift(unittest.TestCase):
    def test_price_drift_beyond_tolerance_is_rejected(self):
        config = ExecutionValidatorConfig(max_spread={SYMBOL: 0.0005}, max_price_drift=0.0005)
        engine = ExecutionValidator(InMemoryIdempotencyStore(300.0), config)
        inputs = list(_nominal_inputs())
        inputs[4] = make_market_snapshot(price=1.105)

        result = engine.validate(*inputs)

        self.assertEqual(result.verdict, Verdict.REJECT)
        self.assertIn("SLIPPAGE_WITHIN_LIMITS", result.blocking_reasons)


class TestMarginFailure(unittest.TestCase):
    def test_insufficient_current_margin_is_rejected_even_with_valid_original_sizing(self):
        engine = _nominal_engine()
        inputs = list(_nominal_inputs())
        inputs[6] = AccountState(equity=10000.0, available_margin=1.0)

        result = engine.validate(*inputs)

        self.assertEqual(result.verdict, Verdict.REJECT)
        self.assertIn("SUFFICIENT_MARGIN", result.blocking_reasons)


class TestSynchronizationFailure(unittest.TestCase):
    def test_candidate_risk_decision_mismatch_is_rejected(self):
        engine = _nominal_engine()
        inputs = list(_nominal_inputs())
        other_candidate = make_candidate(trace_id="unrelated-trace")
        inputs[3] = other_candidate

        result = engine.validate(*inputs)

        self.assertEqual(result.verdict, Verdict.REJECT)
        self.assertIn("CANDIDATE_INTEGRITY", result.blocking_reasons)


class TestMissingComplianceDecision(unittest.TestCase):
    def test_missing_compliance_decision_is_rejected(self):
        engine = _nominal_engine()
        inputs = list(_nominal_inputs())
        inputs[0] = None

        result = engine.validate(*inputs)

        self.assertEqual(result.verdict, Verdict.REJECT)
        self.assertIn("COMPLIANCE_APPROVAL_VALID", result.blocking_reasons)


class TestMissingRiskDecision(unittest.TestCase):
    def test_missing_risk_decision_is_rejected(self):
        engine = _nominal_engine()
        inputs = list(_nominal_inputs())
        inputs[1] = None

        result = engine.validate(*inputs)

        self.assertEqual(result.verdict, Verdict.REJECT)
        self.assertIn("RISK_DECISION_CONSISTENT", result.blocking_reasons)


class TestMissingMarketState(unittest.TestCase):
    def test_missing_market_snapshot_is_rejected(self):
        engine = _nominal_engine()
        inputs = list(_nominal_inputs())
        inputs[4] = None

        result = engine.validate(*inputs)

        self.assertEqual(result.verdict, Verdict.REJECT)
        blocked_checks = {e.check for e in result.check_evaluations if e.blocks}
        self.assertIn("MARKET_OPEN", blocked_checks)
        self.assertIn("PRICE_VALID", blocked_checks)


class TestFailClosedBehavior(unittest.TestCase):
    def test_every_unevaluable_check_blocks_the_overall_decision(self):
        engine = ExecutionValidator(InMemoryIdempotencyStore(300.0), ExecutionValidatorConfig())
        inputs = list(_nominal_inputs())

        result = engine.validate(*inputs)

        self.assertEqual(result.verdict, Verdict.REJECT)
        statuses = {e.status for e in result.check_evaluations}
        self.assertIn(CheckStatus.UNEVALUABLE, statuses)


class TestNoUpstreamModification(unittest.TestCase):
    def test_compliance_and_risk_decisions_are_untouched(self):
        engine = _nominal_engine()
        inputs = _nominal_inputs()
        compliance_decision, risk_decision = inputs[0], inputs[1]
        before_compliance, before_risk = compliance_decision, risk_decision

        engine.validate(*inputs)

        self.assertEqual(compliance_decision, before_compliance)
        self.assertEqual(risk_decision, before_risk)
        self.assertIs(compliance_decision, before_compliance)
        self.assertIs(risk_decision, before_risk)


class TestNoShortCircuit(unittest.TestCase):
    def test_every_check_runs_even_after_an_early_one_fails(self):
        """Compliance approval fails first in evaluation order, but every
        other check must still run and appear in the audit trail."""
        engine = _nominal_engine()
        inputs = list(_nominal_inputs())
        inputs[0] = None  # missing compliance decision

        result = engine.validate(*inputs)

        self.assertEqual(len(result.check_evaluations), 19)
        checked_names = {e.check for e in result.check_evaluations}
        self.assertIn("SUFFICIENT_MARGIN", checked_names)
        self.assertIn("MINIMUM_RR", checked_names)


class TestWarnings(unittest.TestCase):
    def test_near_threshold_spread_produces_a_warning_without_blocking(self):
        config = ExecutionValidatorConfig(max_spread={SYMBOL: 0.0005}, warning_threshold_ratio=0.8)
        engine = ExecutionValidator(InMemoryIdempotencyStore(300.0), config)
        inputs = list(_nominal_inputs())
        inputs[4] = make_market_snapshot(spread=0.00045)

        result = engine.validate(*inputs)

        self.assertEqual(result.verdict, Verdict.APPROVE)
        self.assertTrue(any("SPREAD_UNCHANGED" in w for w in result.warnings))


if __name__ == "__main__":
    unittest.main()
