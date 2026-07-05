"""Analytics-only metrics surface (ADR-010) — export-only, additive,
zero effect on returned outputs."""

from __future__ import annotations

import unittest

from phantom_pipeline.analytics.engine import AnalyticsEngine
from phantom_pipeline.analytics.metrics import AnalyticsMetrics
from phantom_pipeline.analytics.store import InMemoryTradeProvenanceStore
from tests.phantom_pipeline.analytics._fixtures import T0, make_candidate


class TestAnalyticsMetrics(unittest.TestCase):
    def test_collected_counts_increment_by_kind(self):
        metrics = AnalyticsMetrics()
        analytics = AnalyticsEngine(InMemoryTradeProvenanceStore(), metrics=metrics)
        candidate = make_candidate()

        analytics.collect_candidate(candidate.trace_id, candidate)

        self.assertEqual(metrics.collected_counts.get("candidate"), 1)

    def test_provenance_records_built_increments(self):
        metrics = AnalyticsMetrics()
        analytics = AnalyticsEngine(InMemoryTradeProvenanceStore(), metrics=metrics)
        candidate = make_candidate()
        analytics.collect_candidate(candidate.trace_id, candidate)

        analytics.build_provenance_record(candidate.trace_id, T0)

        self.assertEqual(metrics.provenance_records_built, 1)

    def test_missing_event_count_increments(self):
        metrics = AnalyticsMetrics()
        analytics = AnalyticsEngine(InMemoryTradeProvenanceStore(), metrics=metrics)
        candidate = make_candidate()
        analytics.collect_candidate(candidate.trace_id, candidate)

        analytics.check_completeness(candidate.trace_id, T0)

        self.assertEqual(metrics.missing_event_count, 1)

    def test_recording_metrics_never_alters_returned_outputs(self):
        candidate = make_candidate()

        without_metrics = AnalyticsEngine(InMemoryTradeProvenanceStore())
        without_metrics.collect_candidate(candidate.trace_id, candidate)
        record1 = without_metrics.build_provenance_record(candidate.trace_id, T0)

        with_metrics = AnalyticsEngine(InMemoryTradeProvenanceStore(), metrics=AnalyticsMetrics())
        with_metrics.collect_candidate(candidate.trace_id, candidate)
        record2 = with_metrics.build_provenance_record(candidate.trace_id, T0)

        self.assertEqual(record1, record2)

    def test_snapshots_are_copies_not_live_views(self):
        metrics = AnalyticsMetrics()
        analytics = AnalyticsEngine(InMemoryTradeProvenanceStore(), metrics=metrics)
        candidate = make_candidate()
        analytics.collect_candidate(candidate.trace_id, candidate)

        snapshot = metrics.collected_counts
        snapshot["INJECTED"] = 999
        self.assertNotIn("INJECTED", metrics.collected_counts)


if __name__ == "__main__":
    unittest.main()
