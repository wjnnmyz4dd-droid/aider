"""PositionManager.evaluate()/resolve_synchronization() tests (ADR-009 §6-§11)."""

from __future__ import annotations

import unittest
from datetime import timedelta

from phantom_pipeline.position_manager.config import PositionManagerConfig
from phantom_pipeline.position_manager.engine import PositionManager
from phantom_pipeline.position_manager.models import (
    LifecycleState,
    ManagementAction,
    PositionAdjustmentRequest,
    PositionCloseRequest,
    RuleStatus,
)
from phantom_pipeline.position_manager.state_store import InMemoryPositionManagerStateStore
from phantom_pipeline.scanner.models import Direction
from tests.phantom_pipeline.position_manager._fixtures import ENTRY_PRICE, POSITION_ID, T0, TRACE_ID, nominal_kwargs


def _manager(**config_overrides) -> PositionManager:
    return PositionManager(InMemoryPositionManagerStateStore(), PositionManagerConfig(**config_overrides))


class TestHoldNoAction(unittest.TestCase):
    def test_no_rule_triggered_yields_no_action(self):
        manager = _manager()
        decision, update, request = manager.evaluate(**nominal_kwargs(lifecycle_state=LifecycleState.FILLED))
        self.assertEqual(decision.action, ManagementAction.NO_ACTION)
        self.assertIsNone(request)
        self.assertEqual(len(decision.rule_evaluations), 11)

    def test_ineligible_lifecycle_state_forces_hold(self):
        manager = _manager()
        decision, update, request = manager.evaluate(**nominal_kwargs(lifecycle_state=LifecycleState.CLOSED))
        self.assertEqual(decision.action, ManagementAction.NO_ACTION)
        self.assertIn("MANAGEMENT_ELIGIBILITY", decision.decision_reason)
        self.assertIsNone(request)


class TestBreakEvenAction(unittest.TestCase):
    def test_break_even_produces_adjustment_and_protected_state(self):
        manager = _manager(breakeven_trigger_distance=0.0020)
        decision, update, request = manager.evaluate(
            **nominal_kwargs(lifecycle_state=LifecycleState.FILLED, current_price=ENTRY_PRICE + 0.0025)
        )
        self.assertEqual(decision.action, ManagementAction.MOVE_TO_BREAKEVEN)
        self.assertIsInstance(request, PositionAdjustmentRequest)
        self.assertEqual(update.lifecycle_state, LifecycleState.PROTECTED)

    def test_break_even_is_idempotent_once_protected(self):
        manager = _manager(breakeven_trigger_distance=0.0020, cooldown_seconds=0.0)
        kwargs = nominal_kwargs(lifecycle_state=LifecycleState.FILLED, current_price=ENTRY_PRICE + 0.0025)
        manager.evaluate(**kwargs)

        second_kwargs = nominal_kwargs(
            lifecycle_state=LifecycleState.PROTECTED,
            current_price=ENTRY_PRICE + 0.0030,
            now=T0 + timedelta(seconds=10),
        )
        decision2, _, request2 = manager.evaluate(**second_kwargs)
        self.assertNotEqual(decision2.action, ManagementAction.MOVE_TO_BREAKEVEN)


class TestTrailingStopAction(unittest.TestCase):
    def test_trailing_produces_adjustment_and_trailing_state(self):
        manager = _manager(trailing_start_distance=0.0030, trailing_distance=0.0020, breakeven_trigger_distance=100.0)
        decision, update, request = manager.evaluate(
            **nominal_kwargs(
                lifecycle_state=LifecycleState.PROTECTED,
                current_price=ENTRY_PRICE + 0.0040,
                current_stop_loss=ENTRY_PRICE - 0.005,
            )
        )
        self.assertEqual(decision.action, ManagementAction.TRAIL_STOP)
        self.assertIsInstance(request, PositionAdjustmentRequest)
        self.assertEqual(update.lifecycle_state, LifecycleState.TRAILING)

    def test_trailing_stop_only_ever_moves_in_favor(self):
        manager = _manager(trailing_start_distance=0.0030, trailing_distance=0.0020, breakeven_trigger_distance=100.0)
        already_favorable_stop = ENTRY_PRICE + 0.0040 - 0.0005
        decision, update, request = manager.evaluate(
            **nominal_kwargs(
                lifecycle_state=LifecycleState.PROTECTED,
                current_price=ENTRY_PRICE + 0.0040,
                current_stop_loss=already_favorable_stop,
            )
        )
        self.assertNotEqual(decision.action, ManagementAction.TRAIL_STOP)


class TestPartialCloseAction(unittest.TestCase):
    def test_partial_close_produces_close_request_and_scaling_state(self):
        manager = _manager(partial_close_trigger_distance=0.0050, partial_close_fraction=0.5, breakeven_trigger_distance=100.0)
        decision, update, request = manager.evaluate(
            **nominal_kwargs(lifecycle_state=LifecycleState.FILLED, current_price=ENTRY_PRICE + 0.0060)
        )
        self.assertEqual(decision.action, ManagementAction.PARTIAL_CLOSE)
        self.assertIsInstance(request, PositionCloseRequest)
        self.assertEqual(request.close_fraction, 0.5)
        self.assertEqual(update.lifecycle_state, LifecycleState.SCALING)

    def test_partial_close_does_not_retrigger(self):
        manager = _manager(
            partial_close_trigger_distance=0.0050, partial_close_fraction=0.5, breakeven_trigger_distance=100.0,
            cooldown_seconds=0.0,
        )
        manager.evaluate(**nominal_kwargs(lifecycle_state=LifecycleState.FILLED, current_price=ENTRY_PRICE + 0.0060))
        decision2, _, request2 = manager.evaluate(
            **nominal_kwargs(lifecycle_state=LifecycleState.SCALING, current_price=ENTRY_PRICE + 0.0070, now=T0 + timedelta(seconds=10))
        )
        self.assertNotEqual(decision2.action, ManagementAction.PARTIAL_CLOSE)


class TestFullClose(unittest.TestCase):
    def test_time_exit_produces_full_close(self):
        manager = _manager(max_duration_seconds=3600.0)
        later = T0 + timedelta(hours=2)
        decision, update, request = manager.evaluate(
            **nominal_kwargs(lifecycle_state=LifecycleState.FILLED, now=later, market_data_timestamp=later)
        )
        self.assertEqual(decision.action, ManagementAction.TIME_EXIT)
        self.assertIsInstance(request, PositionCloseRequest)
        self.assertEqual(request.close_fraction, 1.0)
        self.assertEqual(update.lifecycle_state, LifecycleState.CLOSING)

    def test_emergency_close_produces_full_close(self):
        manager = _manager()
        decision, update, request = manager.evaluate(
            **nominal_kwargs(lifecycle_state=LifecycleState.FILLED, compliance_kill_switch_active=True)
        )
        self.assertEqual(decision.action, ManagementAction.EMERGENCY_CLOSE)
        self.assertIsInstance(request, PositionCloseRequest)
        self.assertEqual(request.close_fraction, 1.0)


class TestPrecedence(unittest.TestCase):
    def test_emergency_close_outranks_everything(self):
        manager = _manager(breakeven_trigger_distance=0.0010, max_duration_seconds=3600.0)
        later = T0 + timedelta(hours=2)
        decision, _, _ = manager.evaluate(
            **nominal_kwargs(
                lifecycle_state=LifecycleState.FILLED,
                current_price=ENTRY_PRICE + 0.01,
                now=later,
                market_data_timestamp=later,
                compliance_kill_switch_active=True,
            )
        )
        self.assertEqual(decision.action, ManagementAction.EMERGENCY_CLOSE)

    def test_emergency_close_bypasses_cooldown(self):
        manager = _manager(cooldown_seconds=3600.0)
        # Force a recent action via a manual stop-loss request, then resolve
        # it (simulating MT5 Bridge confirming it), then immediately trigger
        # emergency close — isolating the cooldown-bypass behavior from
        # duplicate-management-prevention, which is a separate gate.
        manager.evaluate(**nominal_kwargs(lifecycle_state=LifecycleState.FILLED, requested_stop_loss=ENTRY_PRICE - 0.001))
        manager.state_store.resolve_pending(POSITION_ID)

        decision, _, request = manager.evaluate(
            **nominal_kwargs(
                lifecycle_state=LifecycleState.PROTECTED,
                compliance_kill_switch_active=True,
                now=T0 + timedelta(seconds=2),
            )
        )
        self.assertEqual(decision.action, ManagementAction.EMERGENCY_CLOSE)
        self.assertIsInstance(request, PositionCloseRequest)


class TestSynchronizationFailureFreezesManagement(unittest.TestCase):
    def test_broker_position_missing_freezes_management(self):
        manager = _manager(breakeven_trigger_distance=0.0010)
        decision, update, request = manager.evaluate(
            **nominal_kwargs(
                lifecycle_state=LifecycleState.FILLED, current_price=ENTRY_PRICE + 0.01, broker_position_exists=False
            )
        )
        self.assertEqual(decision.action, ManagementAction.NO_ACTION)
        self.assertIn("SYNCHRONIZATION_VALIDATION", decision.decision_reason)
        self.assertIsNone(request)

    def test_synchronization_failure_blocks_even_emergency_close(self):
        """Fail-closed applies uniformly — even the safety valve must not
        act on an unreconciled position (ADR-009 §10 Hard Rule)."""
        manager = _manager()
        decision, _, request = manager.evaluate(
            **nominal_kwargs(
                lifecycle_state=LifecycleState.FILLED, broker_position_exists=False, compliance_kill_switch_active=True
            )
        )
        self.assertEqual(decision.action, ManagementAction.NO_ACTION)
        self.assertIsNone(request)


class TestStalePositionHandling(unittest.TestCase):
    def test_stale_market_data_freezes_management(self):
        manager = _manager(breakeven_trigger_distance=0.0010, max_market_data_age_seconds=10.0)
        decision, update, request = manager.evaluate(
            **nominal_kwargs(
                lifecycle_state=LifecycleState.FILLED,
                current_price=ENTRY_PRICE + 0.01,
                market_data_timestamp=T0,
                now=T0 + timedelta(seconds=60),
            )
        )
        self.assertEqual(decision.action, ManagementAction.NO_ACTION)
        self.assertIn("STALE_POSITION_DETECTION", decision.decision_reason)
        self.assertIsNone(request)


class TestDuplicateManagementPrevention(unittest.TestCase):
    def test_second_evaluation_while_pending_is_suppressed(self):
        manager = _manager(breakeven_trigger_distance=0.0010, partial_close_trigger_distance=100.0, cooldown_seconds=0.0)
        first_decision, _, first_request = manager.evaluate(
            **nominal_kwargs(lifecycle_state=LifecycleState.FILLED, current_price=ENTRY_PRICE + 0.01)
        )
        self.assertEqual(first_decision.action, ManagementAction.MOVE_TO_BREAKEVEN)

        second_decision, _, second_request = manager.evaluate(
            **nominal_kwargs(
                lifecycle_state=LifecycleState.PROTECTED,
                current_price=ENTRY_PRICE + 0.02,
                now=T0 + timedelta(seconds=1),
            )
        )
        self.assertEqual(second_decision.action, ManagementAction.NO_ACTION)
        self.assertIn("DUPLICATE_MANAGEMENT_PREVENTION", second_decision.decision_reason)
        self.assertIsNone(second_request)


class TestCooldownEnforcement(unittest.TestCase):
    def test_second_action_within_cooldown_is_held(self):
        manager = _manager(breakeven_trigger_distance=0.0010, cooldown_seconds=60.0)
        manager.state_store.mark_pending  # no-op reference; ensure attribute exists
        first_decision, _, _ = manager.evaluate(
            **nominal_kwargs(lifecycle_state=LifecycleState.FILLED, current_price=ENTRY_PRICE + 0.01)
        )
        manager.state_store.resolve_pending(POSITION_ID)  # simulate the request having resolved

        second_decision, _, _ = manager.evaluate(
            **nominal_kwargs(
                lifecycle_state=LifecycleState.PROTECTED,
                current_price=ENTRY_PRICE + 0.02,
                now=T0 + timedelta(seconds=5),
            )
        )
        self.assertEqual(second_decision.action, ManagementAction.NO_ACTION)
        self.assertIn("COOLDOWN_ENFORCEMENT", second_decision.decision_reason)


class TestSynchronizationRecovery(unittest.TestCase):
    def test_resolve_synchronization_after_discrepancy(self):
        manager = _manager()
        result = manager.resolve_synchronization(
            position_id=POSITION_ID, trace_id=TRACE_ID, broker_position_exists=True, after_reconnect=False, now=T0
        )
        self.assertEqual(result.lifecycle_state, LifecycleState.RECOVERED)
        self.assertEqual(manager.state_store.get_lifecycle_state(POSITION_ID), LifecycleState.RECOVERED)

    def test_resolve_synchronization_after_reconnect(self):
        manager = _manager()
        result = manager.resolve_synchronization(
            position_id=POSITION_ID, trace_id=TRACE_ID, broker_position_exists=True, after_reconnect=True, now=T0
        )
        self.assertEqual(result.lifecycle_state, LifecycleState.RECOVERED_AFTER_DISCONNECT)

    def test_recovery_clears_pending_flag(self):
        manager = _manager(breakeven_trigger_distance=0.0010)
        manager.evaluate(**nominal_kwargs(lifecycle_state=LifecycleState.FILLED, current_price=ENTRY_PRICE + 0.01))
        self.assertTrue(manager.state_store.has_pending_request(POSITION_ID))

        manager.resolve_synchronization(
            position_id=POSITION_ID, trace_id=TRACE_ID, broker_position_exists=True, after_reconnect=True, now=T0
        )
        self.assertFalse(manager.state_store.has_pending_request(POSITION_ID))


class TestManualStopLossAdjustment(unittest.TestCase):
    def test_manual_request_triggers_move_stop_loss(self):
        manager = _manager(breakeven_trigger_distance=100.0, trailing_start_distance=100.0)
        decision, update, request = manager.evaluate(
            **nominal_kwargs(lifecycle_state=LifecycleState.FILLED, requested_stop_loss=ENTRY_PRICE - 0.001)
        )
        self.assertEqual(decision.action, ManagementAction.MOVE_STOP_LOSS)
        self.assertIsInstance(request, PositionAdjustmentRequest)
        self.assertEqual(request.new_stop_loss, ENTRY_PRICE - 0.001)


class TestDeterminism(unittest.TestCase):
    def test_same_inputs_same_outputs(self):
        kwargs = nominal_kwargs(lifecycle_state=LifecycleState.FILLED, current_price=ENTRY_PRICE + 0.01)
        m1 = _manager(breakeven_trigger_distance=0.0010)
        m2 = _manager(breakeven_trigger_distance=0.0010)
        d1, u1, r1 = m1.evaluate(**kwargs)
        d2, u2, r2 = m2.evaluate(**kwargs)
        self.assertEqual(d1, d2)
        self.assertEqual(u1, u2)
        self.assertEqual(r1, r2)

    def test_replay_determinism_across_fresh_managers(self):
        kwargs = nominal_kwargs(lifecycle_state=LifecycleState.FILLED, current_price=ENTRY_PRICE + 0.01)
        results = []
        for _ in range(3):
            manager = _manager(breakeven_trigger_distance=0.0010)
            results.append(manager.evaluate(**kwargs))
        self.assertTrue(all(r == results[0] for r in results))


class TestNoUpstreamMutation(unittest.TestCase):
    def test_kwargs_untouched(self):
        manager = _manager(breakeven_trigger_distance=0.0010)
        kwargs = nominal_kwargs(lifecycle_state=LifecycleState.FILLED, current_price=ENTRY_PRICE + 0.01)
        before = dict(kwargs)
        manager.evaluate(**kwargs)
        self.assertEqual(kwargs, before)


class TestFullAuditTrailNeverShortCircuits(unittest.TestCase):
    def test_every_gate_and_rule_evaluated_even_when_blocked(self):
        manager = _manager()
        decision, _, _ = manager.evaluate(**nominal_kwargs(lifecycle_state=LifecycleState.CLOSED))
        self.assertEqual(len(decision.rule_evaluations), 11)
        rule_names = {e.rule for e in decision.rule_evaluations}
        self.assertIn("EMERGENCY_CLOSE", rule_names)
        self.assertIn("TIME_EXIT", rule_names)


if __name__ == "__main__":
    unittest.main()
