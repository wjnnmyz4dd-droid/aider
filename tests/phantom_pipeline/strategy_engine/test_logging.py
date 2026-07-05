"""Structured logging emission (ADR-003 §12)."""

from __future__ import annotations

import logging
import unittest

from phantom_pipeline.strategy_engine.config import STRATEGY_ENGINE_VERSION, StrategyEngineConfig
from phantom_pipeline.strategy_engine.engine import StrategyEngine
from phantom_pipeline.strategy_engine.logging_sink import logger
from phantom_pipeline.strategy_engine.registry import StrategyRegistry
from tests.phantom_pipeline.strategy_engine._fixtures import (
    TIMEFRAME,
    AlwaysUpPlaybook,
    DisabledByDefaultPlaybook,
    ExplodingPlaybook,
    enabled_config,
    nominal_observation,
    warm_up_observation,
)


class _CapturingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


class TestCandidateTradeLogging(unittest.TestCase):
    def setUp(self):
        self.handler = _CapturingHandler()
        logger.addHandler(self.handler)
        logger.setLevel(logging.DEBUG)
        self.previous_propagate = logger.propagate
        logger.propagate = False

    def tearDown(self):
        logger.removeHandler(self.handler)
        logger.propagate = self.previous_propagate

    def test_candidate_trade_emission_carries_all_required_fields(self):
        registry = StrategyRegistry(playbook_classes=[AlwaysUpPlaybook])
        engine = StrategyEngine(registry, enabled_config("TEST_ALWAYS_UP"))
        observation = nominal_observation()
        self.handler.records.clear()

        candidates = engine.generate(observation, TIMEFRAME)
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]

        candidate_records = [
            r for r in self.handler.records if r.msg == "strategy_engine.candidate_trade"
        ]
        self.assertEqual(len(candidate_records), 1)
        record = candidate_records[0]
        self.assertEqual(record.trace_id, candidate.trace_id)
        self.assertEqual(record.schema_version, candidate.schema_version)
        self.assertEqual(record.strategy_id, candidate.strategy_id)
        self.assertEqual(record.symbol, candidate.symbol)
        self.assertEqual(record.timeframe, candidate.timeframe)
        self.assertEqual(record.candidate_id, candidate.candidate_id)
        self.assertEqual(record.timestamp, candidate.timestamp.isoformat())
        self.assertEqual(record.scanner_observation_trace_id, observation.trace_id)

    def test_playbook_abstention_is_logged(self):
        registry = StrategyRegistry(playbook_classes=[DisabledByDefaultPlaybook])
        engine = StrategyEngine(registry, StrategyEngineConfig())
        observation = nominal_observation()
        self.handler.records.clear()

        engine.generate(observation, TIMEFRAME)

        abstention_records = [
            r for r in self.handler.records if r.msg == "strategy_engine.playbook_abstention"
        ]
        self.assertEqual(len(abstention_records), 1)
        self.assertEqual(abstention_records[0].reason, "disabled")
        self.assertEqual(abstention_records[0].strategy_id, "TEST_DISABLED_DEFAULT")

    def test_playbook_failure_is_logged_with_diagnostic_detail(self):
        registry = StrategyRegistry(playbook_classes=[ExplodingPlaybook])
        engine = StrategyEngine(registry, enabled_config("TEST_EXPLODES"))
        observation = nominal_observation()
        self.handler.records.clear()

        engine.generate(observation, TIMEFRAME)

        failure_records = [
            r for r in self.handler.records if r.msg == "strategy_engine.playbook_failure"
        ]
        self.assertEqual(len(failure_records), 1)
        record = failure_records[0]
        self.assertEqual(record.strategy_id, "TEST_EXPLODES")
        self.assertEqual(record.version, "1.0.0")
        self.assertEqual(record.trace_id, observation.trace_id)
        self.assertIn("simulated playbook implementation bug", record.error)

    def test_logging_never_alters_engine_output(self):
        registry = StrategyRegistry(playbook_classes=[AlwaysUpPlaybook])
        config = enabled_config("TEST_ALWAYS_UP")
        observation = nominal_observation()

        logger.removeHandler(self.handler)
        silent_engine = StrategyEngine(StrategyRegistry(playbook_classes=[AlwaysUpPlaybook]), config)
        silent_result = silent_engine.generate(observation, TIMEFRAME)

        logger.addHandler(self.handler)
        observed_engine = StrategyEngine(StrategyRegistry(playbook_classes=[AlwaysUpPlaybook]), config)
        observed_result = observed_engine.generate(observation, TIMEFRAME)

        self.assertEqual(silent_result, observed_result)

    def test_registry_initialization_logs_a_lifecycle_event(self):
        self.handler.records.clear()
        registry = StrategyRegistry(playbook_classes=[AlwaysUpPlaybook])

        lifecycle_records = [
            r for r in self.handler.records if r.msg == "strategy_engine.registry_initialized"
        ]
        self.assertEqual(len(lifecycle_records), 1)
        self.assertEqual(lifecycle_records[0].registered_ids, registry.registered_ids)


class TestNoHypothesisScanLogging(unittest.TestCase):
    """Remediation for the ADR-003 audit finding: a call that
    short-circuits on a non-nominal `data_quality_flag` previously left
    zero trace in logs or metrics, violating §12's "every playbook's
    abstention is logged" and its observability requirement."""

    def setUp(self):
        self.handler = _CapturingHandler()
        logger.addHandler(self.handler)
        logger.setLevel(logging.DEBUG)
        self.previous_propagate = logger.propagate
        logger.propagate = False

    def tearDown(self):
        logger.removeHandler(self.handler)
        logger.propagate = self.previous_propagate

    def test_non_nominal_observation_emits_exactly_one_no_hypothesis_scan_record(self):
        registry = StrategyRegistry(playbook_classes=[AlwaysUpPlaybook])
        engine = StrategyEngine(registry, enabled_config("TEST_ALWAYS_UP"))
        observation = warm_up_observation()
        self.handler.records.clear()

        candidates = engine.generate(observation, TIMEFRAME)

        self.assertEqual(candidates, ())
        no_hypothesis_records = [
            r for r in self.handler.records if r.msg == "strategy_engine.no_hypothesis_scan"
        ]
        self.assertEqual(len(no_hypothesis_records), 1)

    def test_no_hypothesis_scan_record_carries_all_required_fields(self):
        registry = StrategyRegistry(playbook_classes=[AlwaysUpPlaybook])
        engine = StrategyEngine(registry, enabled_config("TEST_ALWAYS_UP"))
        observation = warm_up_observation()
        self.handler.records.clear()

        engine.generate(observation, TIMEFRAME)

        record = next(
            r for r in self.handler.records if r.msg == "strategy_engine.no_hypothesis_scan"
        )
        self.assertEqual(record.trace_id, observation.trace_id)
        self.assertEqual(record.schema_version, observation.schema_version)
        self.assertEqual(record.symbol, observation.symbol)
        self.assertEqual(record.timeframe, TIMEFRAME)
        self.assertEqual(record.data_quality_flag, observation.data_quality_flag.value)
        self.assertEqual(record.reason, "non_nominal_data_quality_flag")
        self.assertEqual(record.strategy_engine_version, STRATEGY_ENGINE_VERSION)
        self.assertEqual(record.candidates_generated, 0)

    def test_no_playbook_abstention_or_candidate_records_accompany_it(self):
        """No playbook may even run when data_quality_flag is non-nominal
        — confirmed here by the complete absence of any per-playbook log
        record alongside the single call-level one."""
        registry = StrategyRegistry(playbook_classes=[AlwaysUpPlaybook])
        engine = StrategyEngine(registry, enabled_config("TEST_ALWAYS_UP"))
        observation = warm_up_observation()
        self.handler.records.clear()

        engine.generate(observation, TIMEFRAME)

        self.assertEqual(len(self.handler.records), 1)
        self.assertEqual(self.handler.records[0].msg, "strategy_engine.no_hypothesis_scan")

    def test_no_hypothesis_scan_logging_never_alters_output(self):
        config = enabled_config("TEST_ALWAYS_UP")
        observation = warm_up_observation()

        logger.removeHandler(self.handler)
        silent_result = StrategyEngine(
            StrategyRegistry(playbook_classes=[AlwaysUpPlaybook]), config
        ).generate(observation, TIMEFRAME)

        logger.addHandler(self.handler)
        observed_result = StrategyEngine(
            StrategyRegistry(playbook_classes=[AlwaysUpPlaybook]), config
        ).generate(observation, TIMEFRAME)

        self.assertEqual(silent_result, observed_result)
        self.assertEqual(silent_result, ())

    def test_nominal_observation_never_emits_a_no_hypothesis_scan_record(self):
        registry = StrategyRegistry(playbook_classes=[AlwaysUpPlaybook])
        engine = StrategyEngine(registry, enabled_config("TEST_ALWAYS_UP"))
        observation = nominal_observation()
        self.handler.records.clear()

        candidates = engine.generate(observation, TIMEFRAME)

        self.assertEqual(len(candidates), 1)
        no_hypothesis_records = [
            r for r in self.handler.records if r.msg == "strategy_engine.no_hypothesis_scan"
        ]
        self.assertEqual(no_hypothesis_records, [])


if __name__ == "__main__":
    unittest.main()
