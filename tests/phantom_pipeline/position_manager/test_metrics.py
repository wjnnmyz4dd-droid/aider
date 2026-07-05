"""Position-Manager-only metrics surface (ADR-009 §13) — export-only,
additive, zero effect on returned outputs."""

from __future__ import annotations

import unittest

from phantom_pipeline.position_manager.config import PositionManagerConfig
from phantom_pipeline.position_manager.engine import PositionManager
from phantom_pipeline.position_manager.metrics import PositionManagerMetrics
from phantom_pipeline.position_manager.models import LifecycleState
from phantom_pipeline.position_manager.state_store import InMemoryPositionManagerStateStore
from tests.phantom_pipeline.position_manager._fixtures import ENTRY_PRICE, POSITION_ID, T0, TRACE_ID, nominal_kwargs


class TestPositionManagerMetrics(unittest.TestCase):
    def test_action_counts_increment(self):
        metrics = PositionManagerMetrics()
        manager = PositionManager(
            InMemoryPositionManagerStateStore(), PositionManagerConfig(breakeven_trigger_distance=0.0010), metrics=metrics
        )

        decision, _, _ = manager.evaluate(**nominal_kwargs(lifecycle_state=LifecycleState.FILLED, current_price=ENTRY_PRICE + 0.01))

        self.assertEqual(metrics.action_counts.get(decision.action.value), 1)

    def test_positions_by_state_tracks_lifecycle(self):
        metrics = PositionManagerMetrics()
        manager = PositionManager(InMemoryPositionManagerStateStore(), PositionManagerConfig(), metrics=metrics)

        manager.evaluate(**nominal_kwargs(lifecycle_state=LifecycleState.FILLED))

        self.assertGreaterEqual(sum(metrics.positions_by_state.values()), 1)

    def test_recovered_vs_recovered_after_disconnect_are_split(self):
        metrics = PositionManagerMetrics()
        manager = PositionManager(InMemoryPositionManagerStateStore(), PositionManagerConfig(), metrics=metrics)

        manager.resolve_synchronization(POSITION_ID, TRACE_ID, True, after_reconnect=False, now=T0)
        manager.resolve_synchronization("p2", TRACE_ID, True, after_reconnect=True, now=T0)

        self.assertEqual(metrics.recovered_count, 1)
        self.assertEqual(metrics.recovered_after_disconnect_count, 1)

    def test_open_and_closed_position_tracking(self):
        metrics = PositionManagerMetrics()
        metrics.record_open_position(POSITION_ID)
        self.assertEqual(metrics.open_position_count, 1)

        metrics.record_closed_position(POSITION_ID, duration_seconds=3600.0)
        self.assertEqual(metrics.open_position_count, 0)
        self.assertEqual(metrics.average_position_duration_seconds, 3600.0)

    def test_recording_metrics_never_alters_returned_outputs(self):
        kwargs = nominal_kwargs(lifecycle_state=LifecycleState.FILLED, current_price=ENTRY_PRICE + 0.01)
        without_metrics = PositionManager(
            InMemoryPositionManagerStateStore(), PositionManagerConfig(breakeven_trigger_distance=0.0010)
        ).evaluate(**kwargs)
        with_metrics = PositionManager(
            InMemoryPositionManagerStateStore(),
            PositionManagerConfig(breakeven_trigger_distance=0.0010),
            metrics=PositionManagerMetrics(),
        ).evaluate(**kwargs)

        self.assertEqual(without_metrics, with_metrics)

    def test_snapshots_are_copies_not_live_views(self):
        metrics = PositionManagerMetrics()
        manager = PositionManager(InMemoryPositionManagerStateStore(), PositionManagerConfig(), metrics=metrics)
        manager.evaluate(**nominal_kwargs(lifecycle_state=LifecycleState.FILLED))

        snapshot = metrics.action_counts
        snapshot["INJECTED"] = 999
        self.assertNotIn("INJECTED", metrics.action_counts)


if __name__ == "__main__":
    unittest.main()
