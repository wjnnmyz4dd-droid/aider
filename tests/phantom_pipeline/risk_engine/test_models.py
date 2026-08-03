"""RiskDecision/AccountState immutability (ADR-005 §4)."""

from __future__ import annotations

import dataclasses
import unittest

from phantom_pipeline.risk_engine.engine import RiskEngine
from phantom_pipeline.risk_engine.models import (
    AccountState,
    ConstraintEvaluation,
    OpenPosition,
    RiskDecision,
    RiskTier,
)
from phantom_pipeline.scanner.models import Direction
from tests.phantom_pipeline.risk_engine._fixtures import (
    T0,
    make_account_state,
    make_candidate,
    make_score_result,
    nominal_observation,
)


class TestRiskDecisionImmutability(unittest.TestCase):
    def test_top_level_fields_cannot_be_reassigned(self):
        candidate = make_candidate()
        score_result = make_score_result(candidate)
        observation = nominal_observation()
        decision = RiskEngine().decide(score_result, candidate, observation, make_account_state())

        with self.assertRaises(dataclasses.FrozenInstanceError):
            decision.approved_risk_percent = 999.0  # type: ignore[misc]

    def test_tuple_fields_are_coerced_to_tuples(self):
        decision = RiskDecision(
            schema_version=1,
            trace_id="t",
            candidate_id="c",
            strategy_id="S",
            symbol=" EURUSD",
            timeframe="M1",
            timestamp=T0,
            direction=Direction.UP,
            approved_risk_percent=1.0,
            approved_risk_amount=100.0,
            lot_size=None,
            risk_tier=RiskTier.NORMAL,
            limiting_constraint="NONE",
            constraint_evaluations=[ConstraintEvaluation("C", 1.0, True, "d")],
            reason_codes=["R1", "R2"],
            risk_engine_version="v",
        )
        self.assertIsInstance(decision.constraint_evaluations, tuple)
        self.assertIsInstance(decision.reason_codes, tuple)

    def test_trace_id_and_candidate_id_preserve_upstream_lineage(self):
        candidate = make_candidate()
        score_result = make_score_result(candidate)
        observation = nominal_observation()
        decision = RiskEngine().decide(score_result, candidate, observation, make_account_state())

        self.assertEqual(decision.trace_id, score_result.trace_id)
        self.assertEqual(decision.candidate_id, score_result.candidate_id)


class TestConstraintEvaluationImmutability(unittest.TestCase):
    def test_frozen(self):
        evaluation = ConstraintEvaluation("C", 1.0, True, "d")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            evaluation.allowed_risk_percent = 5.0  # type: ignore[misc]


class TestAccountStateImmutability(unittest.TestCase):
    def test_frozen(self):
        account = make_account_state()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            account.equity = 0.0  # type: ignore[misc]

    def test_open_positions_coerced_to_tuple(self):
        account = AccountState(
            equity=1.0,
            daily_drawdown_pct=0.0,
            total_drawdown_pct=0.0,
            consecutive_losses=0,
            daily_risk_allocated_pct=0.0,
            open_positions=[OpenPosition("EURUSD", Direction.UP, 1.0, None)],
        )
        self.assertIsInstance(account.open_positions, tuple)


class TestOpenPositionImmutability(unittest.TestCase):
    def test_frozen(self):
        position = OpenPosition("EURUSD", Direction.UP, 1.0, None)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            position.allocated_risk_percent = 5.0  # type: ignore[misc]


class TestInputsRemainImmutableAtRiskBoundary(unittest.TestCase):
    def test_deciding_never_mutates_score_result_or_candidate_or_observation(self):
        candidate = make_candidate()
        score_result = make_score_result(candidate)
        observation = nominal_observation()
        account = make_account_state()

        before_candidate = candidate
        before_score = score_result
        before_observation = observation

        RiskEngine().decide(score_result, candidate, observation, account)

        self.assertEqual(candidate, before_candidate)
        self.assertEqual(score_result, before_score)
        self.assertEqual(observation, before_observation)

        with self.assertRaises(dataclasses.FrozenInstanceError):
            candidate.direction = Direction.DOWN  # type: ignore[misc]
        with self.assertRaises(dataclasses.FrozenInstanceError):
            score_result.overall_score = 0.0  # type: ignore[misc]
        with self.assertRaises(dataclasses.FrozenInstanceError):
            observation.symbol = "GBPUSD"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
