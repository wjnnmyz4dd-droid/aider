"""Structured logging emission tests (ADR-009 §12)."""

from __future__ import annotations

import logging
import unittest

from phantom_pipeline.position_manager.config import PositionManagerConfig
from phantom_pipeline.position_manager.engine import PositionManager
from phantom_pipeline.position_manager.logging_sink import logger
from phantom_pipeline.position_manager.models import LifecycleState
from phantom_pipeline.position_manager.state_store import InMemoryPositionManagerStateStore
from tests.phantom_pipeline.position_manager._fixtures import ENTRY_PRICE, POSITION_ID, T0, TRACE_ID, nominal_kwargs


class _CapturingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


class TestPositionManagerLogging(unittest.TestCase):
    def setUp(self):
        self.handler = _CapturingHandler()
        logger.addHandler(self.handler)
        logger.setLevel(logging.DEBUG)
        self.previous_propagate = logger.propagate
        logger.propagate = False

    def tearDown(self):
        logger.removeHandler(self.handler)
        logger.propagate = self.previous_propagate

    def test_management_decision_emission_carries_required_fields(self):
        manager = PositionManager(InMemoryPositionManagerStateStore(), PositionManagerConfig(breakeven_trigger_distance=0.0010))
        self.handler.records.clear()

        decision, _, _ = manager.evaluate(**nominal_kwargs(lifecycle_state=LifecycleState.FILLED, current_price=ENTRY_PRICE + 0.01))

        decision_records = [r for r in self.handler.records if r.msg == "position_manager.management_decision"]
        self.assertEqual(len(decision_records), 1)
        record = decision_records[0]
        self.assertEqual(record.trace_id, decision.trace_id)
        self.assertEqual(record.position_id, decision.position_id)
        self.assertEqual(record.decision_reason, decision.decision_reason)
        self.assertIsNotNone(record.timestamp)

    def test_rule_evaluation_is_logged_at_a_distinct_granularity(self):
        manager = PositionManager(InMemoryPositionManagerStateStore(), PositionManagerConfig())
        self.handler.records.clear()

        manager.evaluate(**nominal_kwargs(lifecycle_state=LifecycleState.FILLED))

        rule_records = [r for r in self.handler.records if r.msg == "position_manager.rule_evaluation"]
        self.assertEqual(len(rule_records), 11)

    def test_position_update_is_logged(self):
        manager = PositionManager(InMemoryPositionManagerStateStore(), PositionManagerConfig())
        self.handler.records.clear()

        manager.evaluate(**nominal_kwargs(lifecycle_state=LifecycleState.FILLED))

        update_records = [r for r in self.handler.records if r.msg == "position_manager.position_update"]
        self.assertEqual(len(update_records), 1)

    def test_synchronization_result_is_logged(self):
        manager = PositionManager(InMemoryPositionManagerStateStore(), PositionManagerConfig())
        self.handler.records.clear()

        manager.resolve_synchronization(
            position_id=POSITION_ID, trace_id=TRACE_ID, broker_position_exists=True, after_reconnect=True, now=T0
        )

        sync_records = [r for r in self.handler.records if r.msg == "position_manager.synchronization_result"]
        self.assertEqual(len(sync_records), 1)

    def test_logging_never_alters_engine_output(self):
        kwargs = nominal_kwargs(lifecycle_state=LifecycleState.FILLED, current_price=ENTRY_PRICE + 0.01)

        logger.removeHandler(self.handler)
        silent_manager = PositionManager(InMemoryPositionManagerStateStore(), PositionManagerConfig(breakeven_trigger_distance=0.0010))
        d1, u1, r1 = silent_manager.evaluate(**kwargs)

        logger.addHandler(self.handler)
        observed_manager = PositionManager(InMemoryPositionManagerStateStore(), PositionManagerConfig(breakeven_trigger_distance=0.0010))
        d2, u2, r2 = observed_manager.evaluate(**kwargs)

        self.assertEqual(d1, d2)
        self.assertEqual(u1, u2)
        self.assertEqual(r1, r2)


if __name__ == "__main__":
    unittest.main()
