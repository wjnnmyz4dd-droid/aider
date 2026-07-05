"""Strategy-Engine-only metrics surface (ADR-003 §12) — export-only,
additive, zero effect on returned candidates."""

from __future__ import annotations

import unittest

from phantom_pipeline.strategy_engine.engine import StrategyEngine
from phantom_pipeline.strategy_engine.metrics import StrategyEngineMetrics
from phantom_pipeline.strategy_engine.registry import StrategyRegistry
from tests.phantom_pipeline.strategy_engine._fixtures import (
    TIMEFRAME,
    AlwaysUpPlaybook,
    ExplodingPlaybook,
    MultiCandidatePlaybook,
    enabled_config,
    nominal_observation,
    warm_up_observation,
)


class TestStrategyEngineMetrics(unittest.TestCase):
    def test_candidates_counted_by_strategy_direction_and_symbol(self):
        metrics = StrategyEngineMetrics()
        registry = StrategyRegistry(playbook_classes=[AlwaysUpPlaybook])
        engine = StrategyEngine(registry, enabled_config("TEST_ALWAYS_UP"), metrics=metrics)

        engine.generate(nominal_observation(), TIMEFRAME)

        self.assertEqual(metrics.candidates_total.get(("TEST_ALWAYS_UP", "UP", "EURUSD")), 1)

    def test_multi_candidate_playbook_counts_each_candidate(self):
        metrics = StrategyEngineMetrics()
        registry = StrategyRegistry(playbook_classes=[MultiCandidatePlaybook])
        engine = StrategyEngine(registry, enabled_config("TEST_MULTI"), metrics=metrics)

        engine.generate(nominal_observation(), TIMEFRAME)

        self.assertEqual(metrics.candidates_total.get(("TEST_MULTI", "UP", "EURUSD")), 1)
        self.assertEqual(metrics.candidates_total.get(("TEST_MULTI", "DOWN", "EURUSD")), 1)

    def test_failures_counted_by_strategy_id(self):
        metrics = StrategyEngineMetrics()
        registry = StrategyRegistry(playbook_classes=[ExplodingPlaybook])
        engine = StrategyEngine(registry, enabled_config("TEST_EXPLODES"), metrics=metrics)

        engine.generate(nominal_observation(), TIMEFRAME)

        self.assertEqual(metrics.failures_total.get("TEST_EXPLODES"), 1)

    def test_abstentions_counted_for_disabled_and_non_nominal_calls(self):
        metrics = StrategyEngineMetrics()
        registry = StrategyRegistry(playbook_classes=[AlwaysUpPlaybook])
        engine = StrategyEngine(registry, enabled_config())  # not enabled
        engine.metrics = metrics

        engine.generate(nominal_observation(), TIMEFRAME)

        self.assertEqual(metrics.abstentions_total.get("TEST_ALWAYS_UP"), 1)

    def test_recording_metrics_never_alters_returned_candidates(self):
        registry_a = StrategyRegistry(playbook_classes=[AlwaysUpPlaybook])
        registry_b = StrategyRegistry(playbook_classes=[AlwaysUpPlaybook])
        config = enabled_config("TEST_ALWAYS_UP")
        observation = nominal_observation()

        without_metrics = StrategyEngine(registry_a, config).generate(observation, TIMEFRAME)
        with_metrics = StrategyEngine(registry_b, config, metrics=StrategyEngineMetrics()).generate(
            observation, TIMEFRAME
        )

        self.assertEqual(without_metrics, with_metrics)

    def test_snapshots_are_copies_not_live_views(self):
        metrics = StrategyEngineMetrics()
        registry = StrategyRegistry(playbook_classes=[AlwaysUpPlaybook])
        engine = StrategyEngine(registry, enabled_config("TEST_ALWAYS_UP"), metrics=metrics)
        engine.generate(nominal_observation(), TIMEFRAME)

        snapshot = metrics.candidates_total
        snapshot[("INJECTED", "UP", "X")] = 999
        self.assertNotIn(("INJECTED", "UP", "X"), metrics.candidates_total)


if __name__ == "__main__":
    unittest.main()
