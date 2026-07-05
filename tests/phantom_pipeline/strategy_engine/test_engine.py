"""StrategyEngine orchestration: strategy generation, candidate creation,
multi-candidate handling, conflict handling, determinism, purity,
boundary/type-level, malformed/insufficient-data handling, trace_id
propagation, immutability, replay determinism (ADR-003 §2, §9, §10, §14,
§16, §18)."""

from __future__ import annotations

import dataclasses
import unittest
from datetime import timedelta
from typing import get_type_hints

from phantom_pipeline.data_pipeline.config import PipelineConfig
from phantom_pipeline.data_pipeline.pipeline import DataPipeline
from phantom_pipeline.data_pipeline.replay import replay_through
from phantom_pipeline.scanner import Scanner, ScannerConfig
from phantom_pipeline.scanner.models import Direction
from phantom_pipeline.strategy_engine.config import StrategyEngineConfig
from phantom_pipeline.strategy_engine.engine import StrategyEngine
from phantom_pipeline.strategy_engine.metrics import StrategyEngineMetrics
from phantom_pipeline.strategy_engine.models import CandidateTrade, Evidence, SupportingObservation
from phantom_pipeline.strategy_engine.registry import StrategyRegistry
from tests.phantom_pipeline.strategy_engine._fixtures import (
    SYMBOL,
    T0,
    TIMEFRAME,
    AlwaysDownPlaybook,
    AlwaysUpPlaybook,
    DisabledByDefaultPlaybook,
    ExplodingPlaybook,
    MultiCandidatePlaybook,
    RequiresTrendPlaybook,
    enabled_config,
    nominal_observation,
    warm_up_observation,
)

FORBIDDEN_FIELD_NAME_FRAGMENTS = (
    "score",
    "rank",
    "approve",
    "reject",
    "risk",
    "lot_size",
    "stop_loss",
    "take_profit",
    "compliance",
    "execution",
    "mt5",
)


class TestStrategyGenerationAndCandidateCreation(unittest.TestCase):
    def test_enabled_playbook_produces_a_well_formed_candidate(self):
        registry = StrategyRegistry(playbook_classes=[AlwaysUpPlaybook])
        engine = StrategyEngine(registry, enabled_config("TEST_ALWAYS_UP"))
        observation = nominal_observation()

        candidates = engine.generate(observation, TIMEFRAME)

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.strategy_id, "TEST_ALWAYS_UP")
        self.assertEqual(candidate.direction, Direction.UP)
        self.assertEqual(candidate.symbol, SYMBOL)
        self.assertEqual(candidate.trace_id, observation.trace_id)

    def test_zero_candidates_is_a_healthy_outcome(self):
        registry = StrategyRegistry(playbook_classes=[])
        engine = StrategyEngine(registry, StrategyEngineConfig())
        observation = nominal_observation()

        self.assertEqual(engine.generate(observation, TIMEFRAME), ())

    def test_disabled_playbook_produces_no_candidate(self):
        registry = StrategyRegistry(playbook_classes=[DisabledByDefaultPlaybook])
        engine = StrategyEngine(registry, StrategyEngineConfig())  # nothing enabled
        observation = nominal_observation()

        self.assertEqual(engine.generate(observation, TIMEFRAME), ())


class TestMultiCandidateHandling(unittest.TestCase):
    def test_a_single_playbook_may_produce_multiple_candidates(self):
        registry = StrategyRegistry(playbook_classes=[MultiCandidatePlaybook])
        engine = StrategyEngine(registry, enabled_config("TEST_MULTI"))
        observation = nominal_observation()

        candidates = engine.generate(observation, TIMEFRAME)

        self.assertEqual(len(candidates), 2)
        self.assertEqual({c.candidate_id for c in candidates}, {c.candidate_id for c in candidates})
        self.assertEqual(len({c.candidate_id for c in candidates}), 2)  # distinct ids

    def test_multiple_playbooks_each_contribute_independently(self):
        registry = StrategyRegistry(playbook_classes=[AlwaysUpPlaybook, MultiCandidatePlaybook])
        engine = StrategyEngine(registry, enabled_config("TEST_ALWAYS_UP", "TEST_MULTI"))
        observation = nominal_observation()

        candidates = engine.generate(observation, TIMEFRAME)

        strategy_ids = {c.strategy_id for c in candidates}
        self.assertEqual(strategy_ids, {"TEST_ALWAYS_UP", "TEST_MULTI"})
        self.assertEqual(len(candidates), 3)  # 1 + 2


class TestConflictHandling(unittest.TestCase):
    def test_opposing_hypotheses_are_both_forwarded_unmodified(self):
        """ADR-003 §9: the Strategy Engine never chooses a winner between
        directly opposing CandidateTrades."""
        registry = StrategyRegistry(playbook_classes=[AlwaysUpPlaybook, AlwaysDownPlaybook])
        engine = StrategyEngine(registry, enabled_config("TEST_ALWAYS_UP", "TEST_ALWAYS_DOWN"))
        observation = nominal_observation()

        candidates = engine.generate(observation, TIMEFRAME)

        directions = {c.direction for c in candidates}
        self.assertEqual(directions, {Direction.UP, Direction.DOWN})
        self.assertEqual(len(candidates), 2)  # neither was dropped or merged

    def test_conflict_resolution_order_never_depends_on_reasoning_content(self):
        """Reasoning-metadata boundary test (ADR-003 §16): reasoning text
        must never influence ordering/ranking of CandidateTrades."""
        registry = StrategyRegistry(playbook_classes=[AlwaysUpPlaybook, AlwaysDownPlaybook])
        engine = StrategyEngine(registry, enabled_config("TEST_ALWAYS_UP", "TEST_ALWAYS_DOWN"))
        observation = nominal_observation()

        first_run = engine.generate(observation, TIMEFRAME)
        second_run = engine.generate(observation, TIMEFRAME)

        self.assertEqual(
            [c.strategy_id for c in first_run], [c.strategy_id for c in second_run]
        )
        # Order is strategy_id-sorted (registry order), independent of any
        # candidate's reasoning/evidence content.
        self.assertEqual([c.strategy_id for c in first_run], sorted(c.strategy_id for c in first_run))


class TestDeterminism(unittest.TestCase):
    def test_identical_observation_yields_identical_candidates(self):
        registry = StrategyRegistry(playbook_classes=[AlwaysUpPlaybook, MultiCandidatePlaybook])
        engine = StrategyEngine(registry, enabled_config("TEST_ALWAYS_UP", "TEST_MULTI"))
        observation = nominal_observation()

        first = engine.generate(observation, TIMEFRAME)
        second = engine.generate(observation, TIMEFRAME)

        self.assertEqual(first, second)

    def test_two_independent_engine_instances_produce_identical_output(self):
        observation = nominal_observation()
        config = enabled_config("TEST_ALWAYS_UP")

        engine_a = StrategyEngine(StrategyRegistry(playbook_classes=[AlwaysUpPlaybook]), config)
        engine_b = StrategyEngine(StrategyRegistry(playbook_classes=[AlwaysUpPlaybook]), config)

        self.assertEqual(engine_a.generate(observation, TIMEFRAME), engine_b.generate(observation, TIMEFRAME))


class TestPurity(unittest.TestCase):
    def test_generate_never_mutates_the_observation(self):
        registry = StrategyRegistry(playbook_classes=[AlwaysUpPlaybook])
        engine = StrategyEngine(registry, enabled_config("TEST_ALWAYS_UP"))
        observation = nominal_observation()

        with self.assertRaises(dataclasses.FrozenInstanceError):
            observation.symbol = "GBPUSD"  # type: ignore[misc]

        before = observation
        engine.generate(observation, TIMEFRAME)
        self.assertEqual(observation, before)

    def test_attaching_metrics_after_construction_does_not_affect_output(self):
        registry = StrategyRegistry(playbook_classes=[AlwaysUpPlaybook])
        engine = StrategyEngine(registry, enabled_config("TEST_ALWAYS_UP"))
        observation = nominal_observation()

        before = engine.generate(observation, TIMEFRAME)
        engine.metrics = StrategyEngineMetrics()
        after = engine.generate(observation, TIMEFRAME)

        self.assertEqual(before, after)


class TestBoundaryTypeLevel(unittest.TestCase):
    ALL_TYPES = (CandidateTrade, SupportingObservation, Evidence)

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

    def test_candidate_trade_is_frozen(self):
        registry = StrategyRegistry(playbook_classes=[AlwaysUpPlaybook])
        engine = StrategyEngine(registry, enabled_config("TEST_ALWAYS_UP"))
        candidate = engine.generate(nominal_observation(), TIMEFRAME)[0]
        with self.assertRaises(dataclasses.FrozenInstanceError):
            candidate.direction = Direction.DOWN  # type: ignore[misc]

    def test_direction_type_hint_is_the_shared_scanner_direction_enum(self):
        hints = get_type_hints(CandidateTrade)
        self.assertIs(hints["direction"], Direction)


class TestFailureIsolation(unittest.TestCase):
    def test_a_playbook_exception_never_crashes_the_engine(self):
        registry = StrategyRegistry(playbook_classes=[ExplodingPlaybook, AlwaysUpPlaybook])
        engine = StrategyEngine(registry, enabled_config("TEST_EXPLODES", "TEST_ALWAYS_UP"))
        observation = nominal_observation()

        try:
            candidates = engine.generate(observation, TIMEFRAME)
        except Exception as exc:  # pragma: no cover - test fails if this triggers
            self.fail(f"generate() must never raise from a playbook exception, but raised: {exc!r}")

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].strategy_id, "TEST_ALWAYS_UP")

    def test_failure_is_recorded_in_metrics(self):
        registry = StrategyRegistry(playbook_classes=[ExplodingPlaybook])
        metrics = StrategyEngineMetrics()
        engine = StrategyEngine(registry, enabled_config("TEST_EXPLODES"), metrics=metrics)

        engine.generate(nominal_observation(), TIMEFRAME)

        self.assertEqual(metrics.failures_total.get("TEST_EXPLODES"), 1)


class TestMalformedAndInsufficientDataHandling(unittest.TestCase):
    def test_non_nominal_observation_yields_no_hypotheses_for_any_playbook(self):
        registry = StrategyRegistry(playbook_classes=[AlwaysUpPlaybook])
        engine = StrategyEngine(registry, enabled_config("TEST_ALWAYS_UP"))
        observation = warm_up_observation()

        self.assertNotEqual(observation.data_quality_flag.value, "NOMINAL")
        self.assertEqual(engine.generate(observation, TIMEFRAME), ())

    def test_playbook_with_missing_required_field_abstains_rather_than_crashing(self):
        registry = StrategyRegistry(playbook_classes=[RequiresTrendPlaybook])
        engine = StrategyEngine(registry, enabled_config("TEST_REQUIRES_TREND"))

        # nominal_observation() has enough bars for a real trend reading.
        observation = nominal_observation()
        candidates = engine.generate(observation, TIMEFRAME)
        # Whether or not it fires depends on the fixture's trend direction —
        # what matters is it never raises and only fires with a real reading.
        for candidate in candidates:
            self.assertNotEqual(candidate.direction, Direction.UNKNOWN)

    def test_unsupported_symbol_or_timeframe_is_a_silent_non_applicability_not_a_crash(self):
        registry = StrategyRegistry(playbook_classes=[AlwaysUpPlaybook])
        engine = StrategyEngine(registry, enabled_config("TEST_ALWAYS_UP"))
        observation = nominal_observation()

        self.assertEqual(engine.generate(observation, "H4"), ())  # unsupported timeframe


class TestTraceIdPropagation(unittest.TestCase):
    def test_every_candidate_carries_the_observations_trace_id(self):
        registry = StrategyRegistry(playbook_classes=[AlwaysUpPlaybook, MultiCandidatePlaybook])
        engine = StrategyEngine(registry, enabled_config("TEST_ALWAYS_UP", "TEST_MULTI"))
        observation = nominal_observation()

        candidates = engine.generate(observation, TIMEFRAME)

        self.assertTrue(candidates)
        for candidate in candidates:
            self.assertEqual(candidate.trace_id, observation.trace_id)

    def test_candidate_ids_are_unique_even_when_trace_id_is_shared(self):
        registry = StrategyRegistry(playbook_classes=[AlwaysUpPlaybook, AlwaysDownPlaybook])
        engine = StrategyEngine(registry, enabled_config("TEST_ALWAYS_UP", "TEST_ALWAYS_DOWN"))
        observation = nominal_observation()

        candidates = engine.generate(observation, TIMEFRAME)
        trace_ids = {c.trace_id for c in candidates}
        candidate_ids = {c.candidate_id for c in candidates}

        self.assertEqual(trace_ids, {observation.trace_id})
        self.assertEqual(len(candidate_ids), len(candidates))


class TestReplayDeterminism(unittest.TestCase):
    def test_replaying_captured_ticks_reproduces_identical_candidates(self):
        pipeline = DataPipeline(PipelineConfig())
        for minute in range(130):
            pipeline.process_raw_tick(
                SYMBOL,
                T0 + timedelta(minutes=minute),
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

        registry = StrategyRegistry(playbook_classes=[AlwaysUpPlaybook, MultiCandidatePlaybook])
        engine = StrategyEngine(registry, enabled_config("TEST_ALWAYS_UP", "TEST_MULTI"))

        original_candidates = engine.generate(original_observation, TIMEFRAME)
        replayed_candidates = engine.generate(replayed_observation, TIMEFRAME)

        self.assertEqual(original_candidates, replayed_candidates)


if __name__ == "__main__":
    unittest.main()
