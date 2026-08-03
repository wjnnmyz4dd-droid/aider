"""Structured logging emission (ADR-004 §10)."""

from __future__ import annotations

import logging
import unittest

from phantom_pipeline.scoring_engine.config import SCORING_ENGINE_VERSION
from phantom_pipeline.scoring_engine.engine import ScoringEngine
from phantom_pipeline.scoring_engine.logging_sink import logger
from phantom_pipeline.scoring_engine.models import ScoringFailureRecord
from phantom_pipeline.scoring_engine.registry import ScoringRuleRegistry
from tests.phantom_pipeline.scoring_engine._fixtures import (
    AlwaysAbstainsRule,
    ExplodingRule,
    FlatPointsRule,
    enabled_config,
    make_candidate,
)


class _CapturingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


class TestScoreResultLogging(unittest.TestCase):
    def setUp(self):
        self.handler = _CapturingHandler()
        logger.addHandler(self.handler)
        logger.setLevel(logging.DEBUG)
        self.previous_propagate = logger.propagate
        logger.propagate = False

    def tearDown(self):
        logger.removeHandler(self.handler)
        logger.propagate = self.previous_propagate

    def test_score_result_emission_carries_all_required_fields(self):
        registry = ScoringRuleRegistry(rule_classes=[FlatPointsRule])
        engine = ScoringEngine(registry, enabled_config("TEST_FLAT"))
        candidate = make_candidate()
        self.handler.records.clear()

        result = engine.score(candidate)

        score_records = [r for r in self.handler.records if r.msg == "scoring_engine.score_result"]
        self.assertEqual(len(score_records), 1)
        record = score_records[0]
        self.assertEqual(record.trace_id, result.trace_id)
        self.assertEqual(record.schema_version, result.schema_version)
        self.assertEqual(record.candidate_id, result.candidate_id)
        self.assertEqual(record.strategy_id, result.strategy_id)
        self.assertEqual(record.overall_score, result.overall_score)
        self.assertEqual(record.scoring_version, SCORING_ENGINE_VERSION)
        self.assertEqual(
            record.factor_summary, {fb.factor: fb.subtotal for fb in result.factor_breakdown}
        )

    def test_rule_execution_is_logged_at_a_distinct_granularity(self):
        registry = ScoringRuleRegistry(rule_classes=[FlatPointsRule, AlwaysAbstainsRule])
        engine = ScoringEngine(registry, enabled_config("TEST_FLAT", "TEST_ABSTAINS"))
        self.handler.records.clear()

        engine.score(make_candidate())

        rule_records = [r for r in self.handler.records if r.msg == "scoring_engine.rule_execution"]
        self.assertEqual(len(rule_records), 2)
        rule_ids = {r.rule_id for r in rule_records}
        self.assertEqual(rule_ids, {"TEST_FLAT", "TEST_ABSTAINS"})

    def test_rule_failure_is_logged_with_diagnostic_detail(self):
        registry = ScoringRuleRegistry(rule_classes=[ExplodingRule])
        engine = ScoringEngine(registry, enabled_config("TEST_EXPLODES"))
        self.handler.records.clear()

        engine.score(make_candidate())

        rule_records = [r for r in self.handler.records if r.msg == "scoring_engine.rule_execution"]
        self.assertEqual(len(rule_records), 1)
        self.assertEqual(rule_records[0].outcome, "FAILED")
        self.assertIn("simulated scoring rule implementation bug", rule_records[0].detail)

    def test_scoring_failure_record_is_logged(self):
        registry = ScoringRuleRegistry(rule_classes=[FlatPointsRule])
        engine = ScoringEngine(registry, enabled_config("TEST_FLAT"))
        candidate = make_candidate(schema_version=999)
        self.handler.records.clear()

        result = engine.score(candidate)
        self.assertIsInstance(result, ScoringFailureRecord)

        failure_records = [
            r for r in self.handler.records if r.msg == "scoring_engine.scoring_failure_record"
        ]
        self.assertEqual(len(failure_records), 1)
        self.assertEqual(failure_records[0].reason, "unsupported_schema_version")
        self.assertEqual(failure_records[0].trace_id, candidate.trace_id)
        self.assertEqual(failure_records[0].candidate_id, candidate.candidate_id)

    def test_logging_never_alters_engine_output(self):
        registry_a = ScoringRuleRegistry(rule_classes=[FlatPointsRule])
        registry_b = ScoringRuleRegistry(rule_classes=[FlatPointsRule])
        config = enabled_config("TEST_FLAT")
        candidate = make_candidate()

        logger.removeHandler(self.handler)
        silent = ScoringEngine(registry_a, config).score(candidate)

        logger.addHandler(self.handler)
        observed = ScoringEngine(registry_b, config).score(candidate)

        self.assertEqual(silent, observed)

    def test_registry_initialization_logs_a_lifecycle_event(self):
        self.handler.records.clear()
        registry = ScoringRuleRegistry(rule_classes=[FlatPointsRule])

        lifecycle_records = [
            r for r in self.handler.records if r.msg == "scoring_engine.registry_initialized"
        ]
        self.assertEqual(len(lifecycle_records), 1)
        self.assertEqual(lifecycle_records[0].registered_ids, registry.registered_ids)


if __name__ == "__main__":
    unittest.main()
