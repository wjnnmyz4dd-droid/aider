"""Transport-layer idempotency store tests (ADR-008 §7)."""

from __future__ import annotations

import unittest
from datetime import timedelta

from phantom_pipeline.mt5_bridge.idempotency_store import InMemoryTransportIdempotencyStore
from tests.phantom_pipeline.mt5_bridge._fixtures import T0


class TestInMemoryTransportIdempotencyStore(unittest.TestCase):
    def test_not_submitted_by_default(self):
        store = InMemoryTransportIdempotencyStore(3600.0)
        self.assertFalse(store.has_submitted("e1", T0))

    def test_recorded_submission_is_seen(self):
        store = InMemoryTransportIdempotencyStore(3600.0)
        store.record_submitted("e1", T0)
        self.assertTrue(store.has_submitted("e1", T0))

    def test_submission_pruned_after_ttl(self):
        store = InMemoryTransportIdempotencyStore(60.0)
        store.record_submitted("e1", T0)
        later = T0 + timedelta(seconds=120)
        self.assertFalse(store.has_submitted("e1", later))

    def test_acknowledged_filled_closed_flags_independent(self):
        store = InMemoryTransportIdempotencyStore(3600.0)
        store.record_submitted("e1", T0)
        self.assertFalse(store.has_acknowledged("e1"))
        self.assertFalse(store.has_filled("e1"))
        self.assertFalse(store.has_closed("e1"))

        store.record_acknowledged("e1")
        store.record_filled("e1")
        store.record_closed("e1")
        self.assertTrue(store.has_acknowledged("e1"))
        self.assertTrue(store.has_filled("e1"))
        self.assertTrue(store.has_closed("e1"))

    def test_pruning_submission_also_clears_derived_flags(self):
        store = InMemoryTransportIdempotencyStore(60.0)
        store.record_submitted("e1", T0)
        store.record_acknowledged("e1")
        store.record_filled("e1")
        later = T0 + timedelta(seconds=120)
        self.assertFalse(store.has_submitted("e1", later))
        self.assertFalse(store.has_acknowledged("e1"))
        self.assertFalse(store.has_filled("e1"))


if __name__ == "__main__":
    unittest.main()
