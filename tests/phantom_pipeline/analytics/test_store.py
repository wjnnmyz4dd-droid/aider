"""TradeProvenanceStore tests (ADR-010 §2, §4)."""

from __future__ import annotations

import unittest

from phantom_pipeline.analytics.store import InMemoryTradeProvenanceStore
from tests.phantom_pipeline.analytics._fixtures import make_candidate


class TestInMemoryTradeProvenanceStore(unittest.TestCase):
    def test_unknown_trace_id_bucket_is_none(self):
        store = InMemoryTradeProvenanceStore()
        self.assertIsNone(store.get_bucket("nonexistent"))

    def test_recording_a_candidate_creates_a_bucket(self):
        store = InMemoryTradeProvenanceStore()
        candidate = make_candidate()
        store.record_candidate(candidate.trace_id, candidate)
        bucket = store.get_bucket(candidate.trace_id)
        self.assertIsNotNone(bucket)
        self.assertIs(bucket.candidate, candidate)

    def test_known_trace_ids_reflects_recorded_buckets(self):
        store = InMemoryTradeProvenanceStore()
        store.record_candidate("t1", make_candidate(trace_id="t1"))
        store.record_candidate("t2", make_candidate(trace_id="t2"))
        self.assertEqual(set(store.known_trace_ids()), {"t1", "t2"})

    def test_repeated_events_of_the_same_kind_accumulate_in_order(self):
        store = InMemoryTradeProvenanceStore()
        store.record_broker_event("t1", "event-1")
        store.record_broker_event("t1", "event-2")
        bucket = store.get_bucket("t1")
        self.assertEqual(bucket.broker_events, ["event-1", "event-2"])

    def test_buckets_are_isolated_per_trace_id(self):
        store = InMemoryTradeProvenanceStore()
        store.record_candidate("t1", make_candidate(trace_id="t1"))
        self.assertIsNone(store.get_bucket("t2"))


if __name__ == "__main__":
    unittest.main()
