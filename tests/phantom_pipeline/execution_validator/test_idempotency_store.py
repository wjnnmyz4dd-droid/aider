"""Idempotency store tests (ADR-007 §7)."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from phantom_pipeline.execution_validator.idempotency_store import InMemoryIdempotencyStore

T0 = datetime(2026, 7, 6, 10, 0, 0, tzinfo=timezone.utc)


class TestInMemoryIdempotencyStore(unittest.TestCase):
    def test_not_seen_by_default(self):
        store = InMemoryIdempotencyStore(ttl_seconds=300.0)
        self.assertFalse(store.has_seen("c1", T0))

    def test_recorded_id_is_seen(self):
        store = InMemoryIdempotencyStore(ttl_seconds=300.0)
        store.record("c1", T0)
        self.assertTrue(store.has_seen("c1", T0))

    def test_bounded_by_ttl_pruning(self):
        store = InMemoryIdempotencyStore(ttl_seconds=60.0)
        store.record("c1", T0)
        later = T0 + timedelta(seconds=120)
        self.assertFalse(store.has_seen("c1", later))

    def test_still_within_ttl_is_seen(self):
        store = InMemoryIdempotencyStore(ttl_seconds=60.0)
        store.record("c1", T0)
        soon = T0 + timedelta(seconds=30)
        self.assertTrue(store.has_seen("c1", soon))

    def test_pruning_does_not_affect_unrelated_unexpired_entries(self):
        store = InMemoryIdempotencyStore(ttl_seconds=60.0)
        store.record("old", T0)
        store.record("new", T0 + timedelta(seconds=50))
        later = T0 + timedelta(seconds=70)
        self.assertFalse(store.has_seen("old", later))
        self.assertTrue(store.has_seen("new", later))


if __name__ == "__main__":
    unittest.main()
