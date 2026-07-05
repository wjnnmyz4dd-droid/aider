"""Scoring-Engine-only metrics surface (ADR-004 §10, §13) — export-only,
additive, zero effect on returned results."""

from __future__ import annotations

import unittest

from phantom_pipeline.scoring_engine.engine import ScoringEngine
from phantom_pipeline.scoring_engine.metrics import ScoringEngineMetrics
from phantom_pipeline.scoring_engine.registry import ScoringRuleRegistry
from tests.phantom_pipeline.scoring_engine._fixtures import (
    AlwaysAbstainsRule,
    ExplodingRule,
    FlatPointsRule,
    enabled_config,
    make_candidate,
)


class TestScoringEngineMetrics(unittest.TestCase):
    def test_score_results_counted_by_strategy_id(self):
        metrics = ScoringEngineMetrics()
        registry = ScoringRuleRegistry(rule_classes=[FlatPointsRule])
        engine = ScoringEngine(registry, enabled_config("TEST_FLAT"), metrics=metrics)

        engine.score(make_candidate(strategy_id="S1"))

        self.assertEqual(metrics.score_results_total.get("S1"), 1)

    def test_failure_records_counted_by_reason(self):
        metrics = ScoringEngineMetrics()
        registry = ScoringRuleRegistry(rule_classes=[FlatPointsRule])
        engine = ScoringEngine(registry, enabled_config("TEST_FLAT"), metrics=metrics)

        engine.score(make_candidate(schema_version=999))

        self.assertEqual(metrics.failure_records_total.get("unsupported_schema_version"), 1)

    def test_rule_outcomes_counted_by_rule_id_and_outcome(self):
        metrics = ScoringEngineMetrics()
        registry = ScoringRuleRegistry(rule_classes=[FlatPointsRule, AlwaysAbstainsRule])
        engine = ScoringEngine(registry, enabled_config("TEST_FLAT", "TEST_ABSTAINS"), metrics=metrics)

        engine.score(make_candidate())

        self.assertEqual(metrics.rule_outcomes_total.get(("TEST_FLAT", "FIRED")), 1)
        self.assertEqual(metrics.rule_outcomes_total.get(("TEST_ABSTAINS", "ABSTAINED")), 1)

    def test_rule_failures_counted(self):
        metrics = ScoringEngineMetrics()
        registry = ScoringRuleRegistry(rule_classes=[ExplodingRule])
        engine = ScoringEngine(registry, enabled_config("TEST_EXPLODES"), metrics=metrics)

        engine.score(make_candidate())

        self.assertEqual(metrics.rule_outcomes_total.get(("TEST_EXPLODES", "FAILED")), 1)

    def test_recording_metrics_never_alters_returned_results(self):
        candidate = make_candidate()
        config = enabled_config("TEST_FLAT")

        without_metrics = ScoringEngine(
            ScoringRuleRegistry(rule_classes=[FlatPointsRule]), config
        ).score(candidate)
        with_metrics = ScoringEngine(
            ScoringRuleRegistry(rule_classes=[FlatPointsRule]), config, metrics=ScoringEngineMetrics()
        ).score(candidate)

        self.assertEqual(without_metrics, with_metrics)

    def test_snapshots_are_copies_not_live_views(self):
        metrics = ScoringEngineMetrics()
        registry = ScoringRuleRegistry(rule_classes=[FlatPointsRule])
        engine = ScoringEngine(registry, enabled_config("TEST_FLAT"), metrics=metrics)
        engine.score(make_candidate())

        snapshot = metrics.score_results_total
        snapshot["INJECTED"] = 999
        self.assertNotIn("INJECTED", metrics.score_results_total)


if __name__ == "__main__":
    unittest.main()
