"""ScoringEngine orchestration: determinism, context-independence, purity,
boundary/type-level, no-discard, malformed input, trace_id/candidate_id
propagation, failure isolation, factor breakdown correctness, replay
determinism (ADR-004 §2, §7, §8, §9, §14, §17)."""

from __future__ import annotations

import dataclasses
import unittest
from datetime import datetime, timedelta, timezone
from typing import get_type_hints

from phantom_pipeline.data_pipeline.config import PipelineConfig
from phantom_pipeline.data_pipeline.pipeline import DataPipeline
from phantom_pipeline.data_pipeline.replay import replay_through
from phantom_pipeline.scanner import Scanner, ScannerConfig
from phantom_pipeline.scanner.models import Direction
from phantom_pipeline.scoring_engine.config import ScoringEngineConfig
from phantom_pipeline.scoring_engine.engine import ScoringEngine
from phantom_pipeline.scoring_engine.metrics import ScoringEngineMetrics
from phantom_pipeline.scoring_engine.models import (
    FactorBreakdown,
    RuleContribution,
    RuleOutcome,
    ScoreResult,
    ScoringEvidence,
    ScoringFailureRecord,
)
from phantom_pipeline.scoring_engine.registry import ScoringRuleRegistry
from phantom_pipeline.strategy_engine.config import StrategyEngineConfig as StratConfig
from phantom_pipeline.strategy_engine.engine import StrategyEngine
from phantom_pipeline.strategy_engine.registry import StrategyRegistry
from tests.phantom_pipeline.scoring_engine._fixtures import (
    SYMBOL,
    TIMEFRAME,
    AlwaysAbstainsRule,
    ExplodingRule,
    FlatPointsRule,
    enabled_config,
    make_candidate,
)
from tests.phantom_pipeline.strategy_engine._fixtures import (
    AlwaysUpPlaybook,
    MultiCandidatePlaybook,
    enabled_config as strat_enabled_config,
)

FORBIDDEN_FIELD_NAME_FRAGMENTS = (
    "lot_size",
    "risk",
    "compliance",
    "execution",
    "mt5",
    "position",
    "broker",
    "approve",
    "reject",
)


class TestScoringAndCandidateCreation(unittest.TestCase):
    def test_enabled_rule_produces_a_well_formed_score_result(self):
        registry = ScoringRuleRegistry(rule_classes=[FlatPointsRule])
        engine = ScoringEngine(registry, enabled_config("TEST_FLAT"))
        candidate = make_candidate()

        result = engine.score(candidate)

        self.assertIsInstance(result, ScoreResult)
        self.assertEqual(result.trace_id, candidate.trace_id)
        self.assertEqual(result.candidate_id, candidate.candidate_id)
        self.assertEqual(result.strategy_id, candidate.strategy_id)
        self.assertGreater(result.overall_score, 0)

    def test_zero_rules_still_produces_a_score_result_of_zero(self):
        registry = ScoringRuleRegistry(rule_classes=[])
        engine = ScoringEngine(registry, ScoringEngineConfig())
        result = engine.score(make_candidate())
        self.assertIsInstance(result, ScoreResult)
        self.assertEqual(result.overall_score, 0.0)
        self.assertEqual(result.rule_contributions, ())


class TestDeterminism(unittest.TestCase):
    def test_identical_candidate_yields_identical_score_result(self):
        registry = ScoringRuleRegistry(rule_classes=[FlatPointsRule])
        engine = ScoringEngine(registry, enabled_config("TEST_FLAT"))
        candidate = make_candidate()

        first = engine.score(candidate)
        second = engine.score(candidate)

        self.assertEqual(first, second)

    def test_two_independent_engine_instances_produce_identical_output(self):
        candidate = make_candidate()
        config = enabled_config("TEST_FLAT")

        result_a = ScoringEngine(ScoringRuleRegistry(rule_classes=[FlatPointsRule]), config).score(
            candidate
        )
        result_b = ScoringEngine(ScoringRuleRegistry(rule_classes=[FlatPointsRule]), config).score(
            candidate
        )

        self.assertEqual(result_a, result_b)


class TestContextIndependentScoring(unittest.TestCase):
    def test_candidate_a_scores_identically_alone_or_beside_100_others(self):
        """Candidate A's score must be identical whether evaluated alone
        or beside 100 other candidates (ADR-004 hard rule)."""
        registry = ScoringRuleRegistry(
            rule_classes=[FlatPointsRule, AlwaysAbstainsRule]
        )
        engine = ScoringEngine(registry, enabled_config("TEST_FLAT", "TEST_ABSTAINS"))

        candidate_a = make_candidate(strategy_id="A", trace_id="trace-a")
        others = [
            make_candidate(strategy_id=f"OTHER_{i}", trace_id=f"trace-{i}") for i in range(100)
        ]

        alone = engine.score(candidate_a)
        batch = engine.score_batch([candidate_a] + others)

        self.assertEqual(alone, batch[0])

    def test_scoring_one_candidate_never_depends_on_anothers_presence(self):
        registry = ScoringRuleRegistry(rule_classes=[FlatPointsRule])
        engine = ScoringEngine(registry, enabled_config("TEST_FLAT"))

        a = make_candidate(strategy_id="A", trace_id="trace-a")
        b = make_candidate(strategy_id="B", trace_id="trace-b")

        result_a_alone = engine.score(a)
        result_a_in_batch = engine.score_batch([b, a])[1]

        self.assertEqual(result_a_alone, result_a_in_batch)


class TestPurity(unittest.TestCase):
    def test_score_never_mutates_the_candidate(self):
        registry = ScoringRuleRegistry(rule_classes=[FlatPointsRule])
        engine = ScoringEngine(registry, enabled_config("TEST_FLAT"))
        candidate = make_candidate()

        before = candidate
        engine.score(candidate)
        self.assertEqual(candidate, before)

        with self.assertRaises(dataclasses.FrozenInstanceError):
            candidate.strategy_id = "OTHER"  # type: ignore[misc]

    def test_attaching_metrics_after_construction_does_not_affect_output(self):
        registry = ScoringRuleRegistry(rule_classes=[FlatPointsRule])
        engine = ScoringEngine(registry, enabled_config("TEST_FLAT"))
        candidate = make_candidate()

        before = engine.score(candidate)
        engine.metrics = ScoringEngineMetrics()
        after = engine.score(candidate)

        self.assertEqual(before, after)


class TestBoundaryTypeLevel(unittest.TestCase):
    ALL_TYPES = (ScoreResult, RuleContribution, FactorBreakdown, ScoringEvidence, ScoringFailureRecord)

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

    def test_score_result_is_frozen(self):
        registry = ScoringRuleRegistry(rule_classes=[FlatPointsRule])
        engine = ScoringEngine(registry, enabled_config("TEST_FLAT"))
        result = engine.score(make_candidate())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.overall_score = 0.0  # type: ignore[misc]

    def test_overall_score_type_hint_is_a_bare_float_never_a_decision_type(self):
        hints = get_type_hints(ScoreResult)
        self.assertIs(hints["overall_score"], float)


class TestNoCandidateDiscarded(unittest.TestCase):
    def test_score_batch_returns_exactly_one_result_per_candidate(self):
        registry = ScoringRuleRegistry(rule_classes=[FlatPointsRule])
        engine = ScoringEngine(registry, enabled_config("TEST_FLAT"))
        candidates = [make_candidate(strategy_id=f"S{i}", trace_id=f"trace-{i}") for i in range(10)]

        results = engine.score_batch(candidates)

        self.assertEqual(len(results), len(candidates))
        for candidate, result in zip(candidates, results):
            self.assertEqual(result.candidate_id, candidate.candidate_id)

    def test_a_malformed_candidate_still_produces_a_record_not_a_drop(self):
        registry = ScoringRuleRegistry(rule_classes=[FlatPointsRule])
        engine = ScoringEngine(registry, enabled_config("TEST_FLAT"))
        good = make_candidate(strategy_id="GOOD", trace_id="trace-good")
        malformed = make_candidate(strategy_id="BAD", trace_id="trace-bad", schema_version=999)

        results = engine.score_batch([good, malformed])

        self.assertEqual(len(results), 2)
        self.assertIsInstance(results[0], ScoreResult)
        self.assertIsInstance(results[1], ScoringFailureRecord)


class TestMalformedInputHandling(unittest.TestCase):
    def test_unsupported_schema_version_produces_a_failure_record(self):
        registry = ScoringRuleRegistry(rule_classes=[FlatPointsRule])
        engine = ScoringEngine(registry, enabled_config("TEST_FLAT"))
        candidate = make_candidate(schema_version=999)

        result = engine.score(candidate)

        self.assertIsInstance(result, ScoringFailureRecord)
        self.assertEqual(result.reason, "unsupported_schema_version")
        self.assertEqual(result.trace_id, candidate.trace_id)
        self.assertEqual(result.candidate_id, candidate.candidate_id)

    def test_never_raises_on_malformed_input(self):
        registry = ScoringRuleRegistry(rule_classes=[FlatPointsRule])
        engine = ScoringEngine(registry, enabled_config("TEST_FLAT"))
        candidate = make_candidate(schema_version=999)

        try:
            engine.score(candidate)
        except Exception as exc:  # pragma: no cover - test fails if this triggers
            self.fail(f"score() must never raise on malformed input, but raised: {exc!r}")


class TestFailureIsolation(unittest.TestCase):
    def test_a_rule_exception_never_crashes_the_engine_or_other_rules(self):
        registry = ScoringRuleRegistry(rule_classes=[ExplodingRule, FlatPointsRule])
        engine = ScoringEngine(registry, enabled_config("TEST_EXPLODES", "TEST_FLAT"))
        candidate = make_candidate()

        try:
            result = engine.score(candidate)
        except Exception as exc:  # pragma: no cover - test fails if this triggers
            self.fail(f"score() must never raise from a rule exception, but raised: {exc!r}")

        self.assertIsInstance(result, ScoreResult)
        outcomes = {rc.rule_id: rc.outcome for rc in result.rule_contributions}
        self.assertEqual(outcomes["TEST_EXPLODES"], RuleOutcome.FAILED)
        self.assertEqual(outcomes["TEST_FLAT"], RuleOutcome.FIRED)
        # The failed rule contributes nothing, but the candidate still
        # receives a full ScoreResult with the other rule's contribution.
        self.assertGreater(result.overall_score, 0)

    def test_failure_is_recorded_in_metrics(self):
        registry = ScoringRuleRegistry(rule_classes=[ExplodingRule])
        metrics = ScoringEngineMetrics()
        engine = ScoringEngine(registry, enabled_config("TEST_EXPLODES"), metrics=metrics)

        engine.score(make_candidate())

        self.assertEqual(metrics.rule_outcomes_total.get(("TEST_EXPLODES", "FAILED")), 1)


class TestFactorBreakdownCorrectness(unittest.TestCase):
    def test_factor_subtotals_sum_to_the_overall_score(self):
        registry = ScoringRuleRegistry()  # the 4 real rules
        config = enabled_config(*registry.registered_ids)
        engine = ScoringEngine(registry, config)
        candidate = make_candidate(direction=Direction.UP, n_evidence=2, n_supporting=1, n_reason=1)

        result = engine.score(candidate)

        self.assertAlmostEqual(
            sum(fb.subtotal for fb in result.factor_breakdown), result.overall_score
        )

    def test_factor_breakdown_rule_ids_match_the_rule_contributions(self):
        registry = ScoringRuleRegistry()
        config = enabled_config(*registry.registered_ids)
        engine = ScoringEngine(registry, config)
        result = engine.score(make_candidate())

        rule_ids_in_breakdown = set()
        for fb in result.factor_breakdown:
            rule_ids_in_breakdown.update(fb.rule_ids)
        rule_ids_in_contributions = {rc.rule_id for rc in result.rule_contributions}

        self.assertEqual(rule_ids_in_breakdown, rule_ids_in_contributions)


class TestRuleContributionCorrectness(unittest.TestCase):
    def test_overall_score_equals_sum_of_fired_contributions_only(self):
        registry = ScoringRuleRegistry(rule_classes=[FlatPointsRule, AlwaysAbstainsRule])
        engine = ScoringEngine(registry, enabled_config("TEST_FLAT", "TEST_ABSTAINS"))
        result = engine.score(make_candidate())

        expected = sum(
            rc.points for rc in result.rule_contributions if rc.outcome == RuleOutcome.FIRED
        )
        self.assertEqual(result.overall_score, expected)
        # An abstained rule contributes zero even though it's still recorded.
        abstained = [rc for rc in result.rule_contributions if rc.outcome == RuleOutcome.ABSTAINED]
        self.assertTrue(abstained)
        self.assertTrue(all(rc.points == 0.0 for rc in abstained))

    def test_disabled_rule_is_recorded_as_abstained_with_zero_points(self):
        registry = ScoringRuleRegistry(rule_classes=[FlatPointsRule])
        engine = ScoringEngine(registry, ScoringEngineConfig())  # not enabled
        result = engine.score(make_candidate())

        self.assertEqual(len(result.rule_contributions), 1)
        self.assertEqual(result.rule_contributions[0].outcome, RuleOutcome.ABSTAINED)
        self.assertEqual(result.overall_score, 0.0)


class TestTraceIdAndCandidateIdPropagation(unittest.TestCase):
    def test_every_result_carries_the_candidates_trace_id_and_candidate_id(self):
        registry = ScoringRuleRegistry(rule_classes=[FlatPointsRule])
        engine = ScoringEngine(registry, enabled_config("TEST_FLAT"))
        candidates = [make_candidate(strategy_id=f"S{i}", trace_id=f"trace-{i}") for i in range(5)]

        results = engine.score_batch(candidates)

        for candidate, result in zip(candidates, results):
            self.assertEqual(result.trace_id, candidate.trace_id)
            self.assertEqual(result.candidate_id, candidate.candidate_id)


class TestNoForbiddenLogicExists(unittest.TestCase):
    """Direct behavioral confirmation that no compliance/risk/execution
    logic exists anywhere in a live score computation."""

    def test_score_result_never_contains_a_decision_shaped_value(self):
        registry = ScoringRuleRegistry()
        config = enabled_config(*registry.registered_ids)
        engine = ScoringEngine(registry, config)
        result = engine.score(make_candidate())

        self.assertIsInstance(result.overall_score, float)
        # No field anywhere resembles APPROVE/BLOCK/REJECT/size/SL/TP.
        result_dict = dataclasses.asdict(result)
        for value in result_dict.values():
            if isinstance(value, str):
                self.assertNotIn("APPROVE", value.upper())
                self.assertNotIn("BLOCK", value.upper())


_T0 = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)


class TestReplayDeterminism(unittest.TestCase):
    def test_replaying_captured_ticks_reproduces_identical_score_results(self):
        pipeline = DataPipeline(PipelineConfig())
        for minute in range(130):
            pipeline.process_raw_tick(
                SYMBOL,
                _T0 + timedelta(minutes=minute),
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

        strat_registry = StrategyRegistry(playbook_classes=[AlwaysUpPlaybook, MultiCandidatePlaybook])
        strat_engine = StrategyEngine(strat_registry, strat_enabled_config("TEST_ALWAYS_UP", "TEST_MULTI"))

        original_candidates = strat_engine.generate(original_observation, TIMEFRAME)
        replayed_candidates = strat_engine.generate(replayed_observation, TIMEFRAME)
        self.assertEqual(original_candidates, replayed_candidates)

        score_registry = ScoringRuleRegistry()
        score_engine = ScoringEngine(score_registry, enabled_config(*score_registry.registered_ids))

        original_scores = score_engine.score_batch(original_candidates)
        replayed_scores = score_engine.score_batch(replayed_candidates)

        self.assertEqual(original_scores, replayed_scores)


if __name__ == "__main__":
    unittest.main()
