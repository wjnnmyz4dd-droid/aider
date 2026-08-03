"""RiskEngine orchestration: determinism, fail-closed rules, never-
exceeds-maximum, minimum-of-constraints, never-discards, boundary/
type-level, trace_id/candidate_id propagation, replay determinism
(ADR-005 Hard Rules, §15, §18, §20)."""

from __future__ import annotations

import dataclasses
import random
import unittest
from datetime import timedelta
from typing import get_type_hints

from phantom_pipeline.data_pipeline.config import PipelineConfig
from phantom_pipeline.data_pipeline.pipeline import DataPipeline
from phantom_pipeline.data_pipeline.replay import replay_through
from phantom_pipeline.risk_engine.config import RiskEngineConfig
from phantom_pipeline.risk_engine.engine import RiskEngine
from phantom_pipeline.risk_engine.metrics import RiskEngineMetrics
from phantom_pipeline.risk_engine.models import ConstraintEvaluation, OpenPosition, RiskDecision, RiskTier
from phantom_pipeline.scanner import Scanner, ScannerConfig
from phantom_pipeline.scanner.models import Direction
from phantom_pipeline.scoring_engine.config import ScoringEngineConfig
from phantom_pipeline.scoring_engine.engine import ScoringEngine
from phantom_pipeline.scoring_engine.registry import ScoringRuleRegistry
from phantom_pipeline.strategy_engine.config import StrategyEngineConfig as StratConfig
from phantom_pipeline.strategy_engine.engine import StrategyEngine
from phantom_pipeline.strategy_engine.registry import StrategyRegistry
from tests.phantom_pipeline.risk_engine._fixtures import (
    SYMBOL,
    TIMEFRAME,
    make_account_state,
    make_candidate,
    make_score_result,
    nominal_observation,
)
from tests.phantom_pipeline.strategy_engine._fixtures import AlwaysUpPlaybook
from tests.phantom_pipeline.strategy_engine._fixtures import enabled_config as strat_enabled_config

FORBIDDEN_FIELD_NAME_FRAGMENTS = (
    "compliance",
    "verdict",
    "reject",
    "execution",
    "mt5",
    "broker",
    "position_manage",
)
# Note: "approve"/"approval" is deliberately excluded from this fragment
# list — ADR-005 §4 explicitly allows a "risk budget" field, and this
# stage's own `approved_risk_percent`/`approved_risk_amount` fields (named
# verbatim per the task's Logging requirements) describe a sizing amount
# this stage itself authorizes, not a trade-level approval/rejection
# verdict (which belongs to Compliance Engine/Execution Validator).


class TestRiskDecisionCreation(unittest.TestCase):
    def test_produces_a_well_formed_decision_for_a_healthy_input(self):
        candidate = make_candidate()
        score_result = make_score_result(candidate)
        observation = nominal_observation()
        account = make_account_state()

        decision = RiskEngine().decide(score_result, candidate, observation, account)

        self.assertIsInstance(decision, RiskDecision)
        self.assertEqual(decision.trace_id, score_result.trace_id)
        self.assertEqual(decision.candidate_id, score_result.candidate_id)
        self.assertGreaterEqual(decision.approved_risk_percent, 0.0)


class TestDeterminism(unittest.TestCase):
    def test_identical_inputs_yield_identical_decision(self):
        candidate = make_candidate()
        score_result = make_score_result(candidate)
        observation = nominal_observation()
        account = make_account_state()
        engine = RiskEngine()

        first = engine.decide(score_result, candidate, observation, account)
        second = engine.decide(score_result, candidate, observation, account)

        self.assertEqual(first, second)

    def test_two_independent_engine_instances_produce_identical_output(self):
        candidate = make_candidate()
        score_result = make_score_result(candidate)
        observation = nominal_observation()
        account = make_account_state()
        config = RiskEngineConfig()

        first = RiskEngine(config).decide(score_result, candidate, observation, account)
        second = RiskEngine(config).decide(score_result, candidate, observation, account)

        self.assertEqual(first, second)

    def test_no_randomness_across_many_repeated_calls(self):
        candidate = make_candidate()
        score_result = make_score_result(candidate)
        observation = nominal_observation()
        account = make_account_state()
        engine = RiskEngine()

        decisions = {engine.decide(score_result, candidate, observation, account) for _ in range(20)}
        self.assertEqual(len(decisions), 1)


class TestFailClosedHardRules(unittest.TestCase):
    def setUp(self):
        self.candidate = make_candidate()
        self.score_result = make_score_result(self.candidate)
        self.observation = nominal_observation()
        self.engine = RiskEngine(RiskEngineConfig(correlation_buckets={SYMBOL: "MAJORS"}))

    def test_missing_account_state_yields_zero_risk(self):
        decision = self.engine.decide(self.score_result, self.candidate, self.observation, None)
        self.assertEqual(decision.approved_risk_percent, 0.0)
        self.assertEqual(decision.risk_tier, RiskTier.HALTED)
        self.assertIn("missing_account_state", decision.reason_codes)

    def test_missing_equity_yields_zero_risk(self):
        account = make_account_state(equity=None)
        decision = self.engine.decide(self.score_result, self.candidate, self.observation, account)
        self.assertEqual(decision.approved_risk_percent, 0.0)

    def test_zero_or_negative_equity_yields_zero_risk(self):
        account = make_account_state(equity=0.0)
        decision = self.engine.decide(self.score_result, self.candidate, self.observation, account)
        self.assertEqual(decision.approved_risk_percent, 0.0)

    def test_uncalculable_exposure_yields_zero_risk(self):
        account = make_account_state(
            open_positions=(OpenPosition("NOT_A_PAIR", Direction.UP, 1.0, None),)
        )
        decision = self.engine.decide(self.score_result, self.candidate, self.observation, account)
        self.assertEqual(decision.approved_risk_percent, 0.0)
        self.assertEqual(decision.limiting_constraint, "CURRENCY_EXPOSURE")

    def test_uncalculable_correlation_yields_zero_risk(self):
        engine = RiskEngine(RiskEngineConfig())  # no correlation buckets configured at all
        account = make_account_state()
        decision = engine.decide(self.score_result, self.candidate, self.observation, account)
        self.assertEqual(decision.approved_risk_percent, 0.0)
        self.assertEqual(decision.limiting_constraint, "CORRELATION_EXPOSURE")


class TestNeverExceedsMaximum(unittest.TestCase):
    def test_awarded_risk_never_exceeds_the_configured_ceiling_under_many_inputs(self):
        candidate = make_candidate()
        score_result = make_score_result(candidate)
        observation = nominal_observation()
        config = RiskEngineConfig(
            max_risk_percent_per_trade=1.0, correlation_buckets={SYMBOL: "MAJORS"}
        )
        engine = RiskEngine(config)

        rng = random.Random(1234)
        for _ in range(200):
            account = make_account_state(
                equity=rng.choice([None, 0.0, -100.0, 10000.0, 500000.0]),
                daily_drawdown_pct=rng.choice([None, 0.0, 1.0, 3.0, 5.0, 10.0]),
                total_drawdown_pct=rng.choice([None, 0.0, 1.0, 3.0, 5.0, 10.0]),
                consecutive_losses=rng.choice([None, 0, 2, 3, 5, 20]),
                daily_risk_allocated_pct=rng.choice([None, 0.0, 2.0, 3.0, 10.0]),
                open_positions=tuple(
                    OpenPosition(SYMBOL, Direction.UP, rng.uniform(0, 3), "MAJORS")
                    for _ in range(rng.randint(0, 3))
                ),
            )
            decision = engine.decide(score_result, candidate, observation, account)
            self.assertLessEqual(decision.approved_risk_percent, config.max_risk_percent_per_trade)
            self.assertGreaterEqual(decision.approved_risk_percent, 0.0)

    def test_malformed_adversarial_account_state_never_exceeds_maximum(self):
        candidate = make_candidate()
        score_result = make_score_result(candidate)
        observation = nominal_observation()
        config = RiskEngineConfig(max_risk_percent_per_trade=1.0, correlation_buckets={SYMBOL: "M"})
        engine = RiskEngine(config)

        adversarial_accounts = [
            make_account_state(equity=float("inf")),
            make_account_state(daily_risk_allocated_pct=-999.0),
            make_account_state(consecutive_losses=-5),
            make_account_state(
                open_positions=tuple(OpenPosition(SYMBOL, Direction.UP, 999.0, "M") for _ in range(5))
            ),
        ]
        for account in adversarial_accounts:
            decision = engine.decide(score_result, candidate, observation, account)
            self.assertLessEqual(decision.approved_risk_percent, config.max_risk_percent_per_trade)


class TestMinimumOfConstraints(unittest.TestCase):
    def test_approved_risk_equals_the_minimum_across_all_constraint_evaluations(self):
        candidate = make_candidate()
        score_result = make_score_result(candidate)
        observation = nominal_observation()
        account = make_account_state(
            daily_risk_allocated_pct=0.7,
            open_positions=(OpenPosition(SYMBOL, Direction.UP, 1.0, "M"),),
        )
        config = RiskEngineConfig(correlation_buckets={SYMBOL: "M"})
        decision = RiskEngine(config).decide(score_result, candidate, observation, account)

        expected_min = min(e.allowed_risk_percent for e in decision.constraint_evaluations)
        self.assertEqual(decision.approved_risk_percent, expected_min)

    def test_exactly_the_tied_minimum_constraints_are_marked_binding(self):
        candidate = make_candidate()
        score_result = make_score_result(candidate)
        observation = nominal_observation()
        account = make_account_state()
        config = RiskEngineConfig(correlation_buckets={SYMBOL: "M"})
        decision = RiskEngine(config).decide(score_result, candidate, observation, account)

        min_value = min(e.allowed_risk_percent for e in decision.constraint_evaluations)
        binding = {e.constraint for e in decision.constraint_evaluations if e.binding}
        expected_binding = {
            e.constraint for e in decision.constraint_evaluations if e.allowed_risk_percent == min_value
        }
        self.assertEqual(binding, expected_binding)
        self.assertTrue(binding)


class TestNeverDiscards(unittest.TestCase):
    def test_decide_batch_returns_exactly_one_decision_per_request(self):
        engine = RiskEngine(RiskEngineConfig(correlation_buckets={SYMBOL: "M"}))
        observation = nominal_observation()
        requests = []
        for i in range(5):
            candidate = make_candidate(strategy_id=f"S{i}", trace_id=f"trace-{i}")
            score_result = make_score_result(candidate)
            account = make_account_state()
            requests.append((score_result, candidate, observation, account, None))

        decisions = engine.decide_batch(requests)

        self.assertEqual(len(decisions), len(requests))
        for (score_result, candidate, _, _, _), decision in zip(requests, decisions):
            self.assertEqual(decision.candidate_id, score_result.candidate_id)

    def test_an_unevaluable_candidate_still_produces_a_decision_not_a_drop(self):
        engine = RiskEngine()
        candidate = make_candidate()
        score_result = make_score_result(candidate)
        observation = nominal_observation()

        decision = engine.decide(score_result, candidate, observation, None)
        self.assertIsInstance(decision, RiskDecision)


class TestBoundaryTypeLevel(unittest.TestCase):
    ALL_TYPES = (RiskDecision, ConstraintEvaluation)

    def test_no_field_name_resembles_a_forbidden_downstream_concept(self):
        for cls in self.ALL_TYPES:
            for f in dataclasses.fields(cls):
                lowered = f.name.lower()
                for forbidden in FORBIDDEN_FIELD_NAME_FRAGMENTS:
                    self.assertNotIn(
                        forbidden,
                        lowered,
                        f"{cls.__name__}.{f.name} resembles a forbidden downstream field",
                    )

    def test_risk_decision_is_frozen(self):
        candidate = make_candidate()
        score_result = make_score_result(candidate)
        observation = nominal_observation()
        decision = RiskEngine().decide(score_result, candidate, observation, make_account_state())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            decision.lot_size = 1.0  # type: ignore[misc]

    def test_risk_tier_type_hint_is_the_qualitative_enum_never_numeric(self):
        hints = get_type_hints(RiskDecision)
        self.assertIs(hints["risk_tier"], RiskTier)


class TestNoComplianceOrExecutionLogic(unittest.TestCase):
    def test_risk_engine_never_blocks_for_news_or_talks_to_mt5(self):
        import phantom_pipeline.risk_engine as pkg
        import inspect

        source = inspect.getsource(pkg.engine) + inspect.getsource(pkg.constraints)
        for forbidden in ("mt5", "MT5", "news", "compliance"):
            self.assertNotIn(forbidden, source)


class TestTraceIdAndCandidateIdPropagation(unittest.TestCase):
    def test_every_decision_carries_the_score_results_trace_id_and_candidate_id(self):
        engine = RiskEngine()
        observation = nominal_observation()
        for i in range(5):
            candidate = make_candidate(strategy_id=f"S{i}", trace_id=f"trace-{i}")
            score_result = make_score_result(candidate)
            decision = engine.decide(score_result, candidate, observation, make_account_state())
            self.assertEqual(decision.trace_id, score_result.trace_id)
            self.assertEqual(decision.candidate_id, score_result.candidate_id)


class TestReplayDeterminism(unittest.TestCase):
    def test_replaying_captured_ticks_reproduces_identical_risk_decisions(self):
        from datetime import datetime, timezone

        t0 = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)
        pipeline = DataPipeline(PipelineConfig())
        for minute in range(130):
            pipeline.process_raw_tick(
                SYMBOL,
                t0 + timedelta(minutes=minute),
                1.1000 + (minute % 20) * 0.0002,
                1.1002 + (minute % 20) * 0.0002,
                None,
                1.0,
                "test",
            )
        pipeline.flush(SYMBOL)

        original_series = pipeline.get_historical_series(SYMBOL, TIMEFRAME)
        scanner = Scanner(ScannerConfig())
        original_observation = scanner.scan(
            SYMBOL, {TIMEFRAME: original_series.bars}, None, original_series.bars[-1].timestamp, TIMEFRAME
        )

        replay_series = pipeline.capture_replay(SYMBOL)
        fresh_pipeline = DataPipeline(PipelineConfig())
        replay_through(replay_series, fresh_pipeline)
        fresh_pipeline.flush(SYMBOL)
        reconstructed_series = fresh_pipeline.get_historical_series(SYMBOL, TIMEFRAME)
        replayed_observation = scanner.scan(
            SYMBOL, {TIMEFRAME: reconstructed_series.bars}, None, reconstructed_series.bars[-1].timestamp, TIMEFRAME
        )
        self.assertEqual(original_observation, replayed_observation)

        strat_registry = StrategyRegistry(playbook_classes=[AlwaysUpPlaybook])
        strat_engine = StrategyEngine(strat_registry, strat_enabled_config("TEST_ALWAYS_UP"))
        original_candidates = strat_engine.generate(original_observation, TIMEFRAME)
        replayed_candidates = strat_engine.generate(replayed_observation, TIMEFRAME)
        self.assertEqual(original_candidates, replayed_candidates)

        score_registry = ScoringRuleRegistry()
        score_engine = ScoringEngine(
            score_registry, ScoringEngineConfig(enabled_rules={r: True for r in score_registry.registered_ids})
        )
        original_scores = score_engine.score_batch(original_candidates)
        replayed_scores = score_engine.score_batch(replayed_candidates)
        self.assertEqual(original_scores, replayed_scores)

        risk_engine = RiskEngine(RiskEngineConfig(correlation_buckets={SYMBOL: "MAJORS"}))
        account = make_account_state()

        original_decisions = tuple(
            risk_engine.decide(score, original_candidates[i], original_observation, account)
            for i, score in enumerate(original_scores)
        )
        replayed_decisions = tuple(
            risk_engine.decide(score, replayed_candidates[i], replayed_observation, account)
            for i, score in enumerate(replayed_scores)
        )
        self.assertEqual(original_decisions, replayed_decisions)


if __name__ == "__main__":
    unittest.main()
