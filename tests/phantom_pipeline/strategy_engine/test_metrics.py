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


class TestNoHypothesisScanMetrics(unittest.TestCase):
    """Remediation for the ADR-003 audit finding: a non-nominal
    `data_quality_flag` call previously recorded zero metrics."""

    def test_non_nominal_observation_is_counted_by_flag_value(self):
        metrics = StrategyEngineMetrics()
        registry = StrategyRegistry(playbook_classes=[AlwaysUpPlaybook])
        engine = StrategyEngine(registry, enabled_config("TEST_ALWAYS_UP"), metrics=metrics)

        observation = warm_up_observation()
        candidates = engine.generate(observation, TIMEFRAME)

        self.assertEqual(candidates, ())
        self.assertEqual(
            metrics.no_hypothesis_scans_total.get(observation.data_quality_flag.value), 1
        )

    def test_no_candidate_or_abstention_or_failure_metrics_are_recorded(self):
        """No playbook may even be evaluated on non-nominal data quality —
        confirmed here by the complete absence of any per-playbook metric."""
        metrics = StrategyEngineMetrics()
        registry = StrategyRegistry(playbook_classes=[AlwaysUpPlaybook])
        engine = StrategyEngine(registry, enabled_config("TEST_ALWAYS_UP"), metrics=metrics)

        engine.generate(warm_up_observation(), TIMEFRAME)

        self.assertEqual(metrics.candidates_total, {})
        self.assertEqual(metrics.abstentions_total, {})
        self.assertEqual(metrics.failures_total, {})

    def test_nominal_observation_never_increments_no_hypothesis_scans(self):
        metrics = StrategyEngineMetrics()
        registry = StrategyRegistry(playbook_classes=[AlwaysUpPlaybook])
        engine = StrategyEngine(registry, enabled_config("TEST_ALWAYS_UP"), metrics=metrics)

        candidates = engine.generate(nominal_observation(), TIMEFRAME)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(metrics.no_hypothesis_scans_total, {})

    def test_recording_the_no_hypothesis_scan_metric_never_alters_output(self):
        config = enabled_config("TEST_ALWAYS_UP")
        observation = warm_up_observation()

        without_metrics = StrategyEngine(
            StrategyRegistry(playbook_classes=[AlwaysUpPlaybook]), config
        ).generate(observation, TIMEFRAME)
        with_metrics = StrategyEngine(
            StrategyRegistry(playbook_classes=[AlwaysUpPlaybook]), config, metrics=StrategyEngineMetrics()
        ).generate(observation, TIMEFRAME)

        self.assertEqual(without_metrics, with_metrics)
        self.assertEqual(without_metrics, ())


if __name__ == "__main__":
    unittest.main()
