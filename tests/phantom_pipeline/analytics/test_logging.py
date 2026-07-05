"""Structured logging emission tests (ADR-010)."""

from __future__ import annotations

import logging
import unittest

from phantom_pipeline.analytics.engine import AnalyticsEngine
from phantom_pipeline.analytics.logging_sink import logger
from phantom_pipeline.analytics.store import InMemoryTradeProvenanceStore
from tests.phantom_pipeline.analytics._fixtures import T0, make_candidate


class _CapturingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


class TestAnalyticsLogging(unittest.TestCase):
    def setUp(self):
        self.handler = _CapturingHandler()
        logger.addHandler(self.handler)
        logger.setLevel(logging.DEBUG)
        self.previous_propagate = logger.propagate
        logger.propagate = False

    def tearDown(self):
        logger.removeHandler(self.handler)
        logger.propagate = self.previous_propagate

    def test_collection_is_logged_with_trace_id_and_kind(self):
        analytics = AnalyticsEngine(InMemoryTradeProvenanceStore())
        candidate = make_candidate()
        self.handler.records.clear()

        analytics.collect_candidate(candidate.trace_id, candidate)

        collected_records = [r for r in self.handler.records if r.msg == "analytics.collected"]
        self.assertEqual(len(collected_records), 1)
        self.assertEqual(collected_records[0].trace_id, candidate.trace_id)
        self.assertEqual(collected_records[0].kind, "candidate")

    def test_provenance_record_build_is_logged(self):
        analytics = AnalyticsEngine(InMemoryTradeProvenanceStore())
        candidate = make_candidate()
        analytics.collect_candidate(candidate.trace_id, candidate)
        self.handler.records.clear()

        analytics.build_provenance_record(candidate.trace_id, T0)

        record_logs = [r for r in self.handler.records if r.msg == "analytics.provenance_record"]
        self.assertEqual(len(record_logs), 1)
        self.assertEqual(record_logs[0].trace_id, candidate.trace_id)

    def test_missing_event_is_logged(self):
        analytics = AnalyticsEngine(InMemoryTradeProvenanceStore())
        candidate = make_candidate()
        analytics.collect_candidate(candidate.trace_id, candidate)
        self.handler.records.clear()

        analytics.check_completeness(candidate.trace_id, T0)

        missing_logs = [r for r in self.handler.records if r.msg == "analytics.missing_event"]
        self.assertEqual(len(missing_logs), 1)

    def test_logging_never_alters_engine_output(self):
        candidate = make_candidate()

        logger.removeHandler(self.handler)
        silent = AnalyticsEngine(InMemoryTradeProvenanceStore())
        silent.collect_candidate(candidate.trace_id, candidate)
        record1 = silent.build_provenance_record(candidate.trace_id, T0)

        logger.addHandler(self.handler)
        observed = AnalyticsEngine(InMemoryTradeProvenanceStore())
        observed.collect_candidate(candidate.trace_id, candidate)
        record2 = observed.build_provenance_record(candidate.trace_id, T0)

        self.assertEqual(record1, record2)


if __name__ == "__main__":
    unittest.main()
