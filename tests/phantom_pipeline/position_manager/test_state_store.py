"""PositionManagerStateStore tests (ADR-009 §2, §7)."""

from __future__ import annotations

import unittest

from phantom_pipeline.position_manager.models import LifecycleState, ManagementAction
from phantom_pipeline.position_manager.state_store import InMemoryPositionManagerStateStore
from tests.phantom_pipeline.position_manager._fixtures import T0


class TestInMemoryPositionManagerStateStore(unittest.TestCase):
    def test_lifecycle_state_defaults_to_none(self):
        store = InMemoryPositionManagerStateStore()
        self.assertIsNone(store.get_lifecycle_state("p1"))

    def test_lifecycle_state_round_trips(self):
        store = InMemoryPositionManagerStateStore()
        store.set_lifecycle_state("p1", LifecycleState.PROTECTED)
        self.assertEqual(store.get_lifecycle_state("p1"), LifecycleState.PROTECTED)

    def test_last_action_at_defaults_to_none(self):
        store = InMemoryPositionManagerStateStore()
        self.assertIsNone(store.last_action_at("p1"))

    def test_record_action_sets_last_action_at(self):
        store = InMemoryPositionManagerStateStore()
        store.record_action("p1", T0)
        self.assertEqual(store.last_action_at("p1"), T0)

    def test_pending_request_lifecycle(self):
        store = InMemoryPositionManagerStateStore()
        self.assertFalse(store.has_pending_request("p1"))
        store.mark_pending("p1")
        self.assertTrue(store.has_pending_request("p1"))
        store.resolve_pending("p1")
        self.assertFalse(store.has_pending_request("p1"))

    def test_one_time_action_tracking_is_per_action(self):
        store = InMemoryPositionManagerStateStore()
        self.assertFalse(store.has_taken_one_time_action("p1", ManagementAction.MOVE_TO_BREAKEVEN))
        store.record_one_time_action("p1", ManagementAction.MOVE_TO_BREAKEVEN)
        self.assertTrue(store.has_taken_one_time_action("p1", ManagementAction.MOVE_TO_BREAKEVEN))
        self.assertFalse(store.has_taken_one_time_action("p1", ManagementAction.PARTIAL_CLOSE))

    def test_state_is_isolated_per_position(self):
        store = InMemoryPositionManagerStateStore()
        store.set_lifecycle_state("p1", LifecycleState.PROTECTED)
        self.assertIsNone(store.get_lifecycle_state("p2"))


if __name__ == "__main__":
    unittest.main()
