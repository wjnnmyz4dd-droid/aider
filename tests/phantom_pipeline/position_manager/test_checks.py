"""Per-gate and per-rule unit tests (ADR-009 §8, §10)."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from phantom_pipeline.position_manager import checks as c
from phantom_pipeline.position_manager.config import PositionManagerConfig
from phantom_pipeline.position_manager.models import LifecycleState, RuleStatus
from phantom_pipeline.scanner.models import Direction
from tests.phantom_pipeline.position_manager._fixtures import ENTRY_PRICE, T0


class TestManagementEligibility(unittest.TestCase):
    def test_open_position_is_eligible(self):
        result = c.management_eligibility(LifecycleState.FILLED)
        self.assertEqual(result.status, RuleStatus.NOT_TRIGGERED)

    def test_closed_position_blocks(self):
        result = c.management_eligibility(LifecycleState.CLOSED)
        self.assertEqual(result.status, RuleStatus.TRIGGERED)

    def test_closing_position_blocks(self):
        result = c.management_eligibility(LifecycleState.CLOSING)
        self.assertEqual(result.status, RuleStatus.TRIGGERED)


class TestStalePositionDetection(unittest.TestCase):
    def test_missing_timestamp_is_unevaluable(self):
        result = c.stale_position_detection(None, T0, PositionManagerConfig())
        self.assertEqual(result.status, RuleStatus.UNEVALUABLE)

    def test_naive_timestamp_is_unevaluable(self):
        result = c.stale_position_detection(datetime(2026, 7, 6, 10, 0, 0), T0, PositionManagerConfig())
        self.assertEqual(result.status, RuleStatus.UNEVALUABLE)

    def test_fresh_data_does_not_trigger(self):
        config = PositionManagerConfig(max_market_data_age_seconds=30.0)
        result = c.stale_position_detection(T0, T0 + timedelta(seconds=5), config)
        self.assertEqual(result.status, RuleStatus.NOT_TRIGGERED)

    def test_stale_data_triggers(self):
        config = PositionManagerConfig(max_market_data_age_seconds=30.0)
        result = c.stale_position_detection(T0, T0 + timedelta(seconds=60), config)
        self.assertEqual(result.status, RuleStatus.TRIGGERED)


class TestSynchronizationValidation(unittest.TestCase):
    def test_missing_is_unevaluable(self):
        result = c.synchronization_validation(None)
        self.assertEqual(result.status, RuleStatus.UNEVALUABLE)

    def test_broker_confirms_open_does_not_trigger(self):
        result = c.synchronization_validation(True)
        self.assertEqual(result.status, RuleStatus.NOT_TRIGGERED)

    def test_broker_does_not_show_position_triggers(self):
        result = c.synchronization_validation(False)
        self.assertEqual(result.status, RuleStatus.TRIGGERED)


class TestCooldownEnforcement(unittest.TestCase):
    def test_no_prior_action_does_not_trigger(self):
        result = c.cooldown_enforcement(None, T0, PositionManagerConfig())
        self.assertEqual(result.status, RuleStatus.NOT_TRIGGERED)

    def test_within_cooldown_triggers(self):
        config = PositionManagerConfig(cooldown_seconds=10.0)
        result = c.cooldown_enforcement(T0, T0 + timedelta(seconds=2), config)
        self.assertEqual(result.status, RuleStatus.TRIGGERED)

    def test_beyond_cooldown_does_not_trigger(self):
        config = PositionManagerConfig(cooldown_seconds=10.0)
        result = c.cooldown_enforcement(T0, T0 + timedelta(seconds=20), config)
        self.assertEqual(result.status, RuleStatus.NOT_TRIGGERED)


class TestDuplicateManagementPrevention(unittest.TestCase):
    def test_no_pending_request_does_not_trigger(self):
        result = c.duplicate_management_prevention(False)
        self.assertEqual(result.status, RuleStatus.NOT_TRIGGERED)

    def test_pending_request_triggers(self):
        result = c.duplicate_management_prevention(True)
        self.assertEqual(result.status, RuleStatus.TRIGGERED)


class TestBreakEven(unittest.TestCase):
    def test_missing_prices_is_unevaluable(self):
        result = c.break_even(LifecycleState.FILLED, Direction.UP, None, None, False, PositionManagerConfig())
        self.assertEqual(result.status, RuleStatus.UNEVALUABLE)

    def test_already_protected_does_not_retrigger(self):
        config = PositionManagerConfig(breakeven_trigger_distance=0.0010)
        result = c.break_even(LifecycleState.PROTECTED, Direction.UP, ENTRY_PRICE, ENTRY_PRICE + 0.01, False, config)
        self.assertEqual(result.status, RuleStatus.NOT_TRIGGERED)

    def test_already_taken_flag_prevents_retrigger(self):
        config = PositionManagerConfig(breakeven_trigger_distance=0.0010)
        result = c.break_even(LifecycleState.FILLED, Direction.UP, ENTRY_PRICE, ENTRY_PRICE + 0.01, True, config)
        self.assertEqual(result.status, RuleStatus.NOT_TRIGGERED)

    def test_below_trigger_distance_does_not_trigger(self):
        config = PositionManagerConfig(breakeven_trigger_distance=0.0050)
        result = c.break_even(LifecycleState.FILLED, Direction.UP, ENTRY_PRICE, ENTRY_PRICE + 0.0010, False, config)
        self.assertEqual(result.status, RuleStatus.NOT_TRIGGERED)

    def test_at_or_above_trigger_distance_triggers(self):
        config = PositionManagerConfig(breakeven_trigger_distance=0.0020)
        result = c.break_even(LifecycleState.FILLED, Direction.UP, ENTRY_PRICE, ENTRY_PRICE + 0.0025, False, config)
        self.assertEqual(result.status, RuleStatus.TRIGGERED)

    def test_down_direction_uses_inverted_distance(self):
        config = PositionManagerConfig(breakeven_trigger_distance=0.0020)
        result = c.break_even(LifecycleState.FILLED, Direction.DOWN, ENTRY_PRICE, ENTRY_PRICE - 0.0025, False, config)
        self.assertEqual(result.status, RuleStatus.TRIGGERED)


class TestTrailingStop(unittest.TestCase):
    def test_missing_prices_is_unevaluable(self):
        result = c.trailing_stop(Direction.UP, None, None, None, PositionManagerConfig())
        self.assertEqual(result.status, RuleStatus.UNEVALUABLE)

    def test_below_trailing_start_does_not_trigger(self):
        config = PositionManagerConfig(trailing_start_distance=0.0030)
        result = c.trailing_stop(Direction.UP, ENTRY_PRICE, ENTRY_PRICE + 0.0010, None, config)
        self.assertEqual(result.status, RuleStatus.NOT_TRIGGERED)

    def test_beyond_trailing_start_triggers_when_no_current_stop(self):
        config = PositionManagerConfig(trailing_start_distance=0.0030, trailing_distance=0.0020)
        result = c.trailing_stop(Direction.UP, ENTRY_PRICE, ENTRY_PRICE + 0.0040, None, config)
        self.assertEqual(result.status, RuleStatus.TRIGGERED)

    def test_never_moves_against_position_favor_for_up(self):
        """Stop already better than what trailing would propose -> no
        retrigger (never moves against favor)."""
        config = PositionManagerConfig(trailing_start_distance=0.0030, trailing_distance=0.0020)
        current_price = ENTRY_PRICE + 0.0040
        already_favorable_stop = current_price - 0.0005  # tighter than trailing_distance would propose
        result = c.trailing_stop(Direction.UP, ENTRY_PRICE, current_price, already_favorable_stop, config)
        self.assertEqual(result.status, RuleStatus.NOT_TRIGGERED)

    def test_improves_on_current_stop_triggers(self):
        config = PositionManagerConfig(trailing_start_distance=0.0030, trailing_distance=0.0020)
        current_price = ENTRY_PRICE + 0.0040
        stale_stop = ENTRY_PRICE - 0.0050  # far behind, trailing should improve it
        result = c.trailing_stop(Direction.UP, ENTRY_PRICE, current_price, stale_stop, config)
        self.assertEqual(result.status, RuleStatus.TRIGGERED)

    def test_down_direction_never_moves_against_favor(self):
        config = PositionManagerConfig(trailing_start_distance=0.0030, trailing_distance=0.0020)
        current_price = ENTRY_PRICE - 0.0040
        already_favorable_stop = current_price + 0.0005
        result = c.trailing_stop(Direction.DOWN, ENTRY_PRICE, current_price, already_favorable_stop, config)
        self.assertEqual(result.status, RuleStatus.NOT_TRIGGERED)


class TestStopLossAdjustment(unittest.TestCase):
    def test_no_request_does_not_trigger(self):
        result = c.stop_loss_adjustment(Direction.UP, ENTRY_PRICE, ENTRY_PRICE - 0.005, None)
        self.assertEqual(result.status, RuleStatus.NOT_TRIGGERED)

    def test_missing_current_price_is_unevaluable(self):
        result = c.stop_loss_adjustment(Direction.UP, None, ENTRY_PRICE - 0.005, ENTRY_PRICE - 0.006)
        self.assertEqual(result.status, RuleStatus.UNEVALUABLE)

    def test_wrong_side_is_unevaluable(self):
        result = c.stop_loss_adjustment(Direction.UP, ENTRY_PRICE, ENTRY_PRICE - 0.005, ENTRY_PRICE + 0.001)
        self.assertEqual(result.status, RuleStatus.UNEVALUABLE)

    def test_same_as_current_does_not_trigger(self):
        result = c.stop_loss_adjustment(Direction.UP, ENTRY_PRICE, ENTRY_PRICE - 0.005, ENTRY_PRICE - 0.005)
        self.assertEqual(result.status, RuleStatus.NOT_TRIGGERED)

    def test_valid_new_request_triggers(self):
        result = c.stop_loss_adjustment(Direction.UP, ENTRY_PRICE, ENTRY_PRICE - 0.005, ENTRY_PRICE - 0.003)
        self.assertEqual(result.status, RuleStatus.TRIGGERED)


class TestPartialClose(unittest.TestCase):
    def test_missing_prices_is_unevaluable(self):
        result = c.partial_close(Direction.UP, None, None, False, PositionManagerConfig())
        self.assertEqual(result.status, RuleStatus.UNEVALUABLE)

    def test_already_taken_does_not_retrigger(self):
        config = PositionManagerConfig(partial_close_trigger_distance=0.0010)
        result = c.partial_close(Direction.UP, ENTRY_PRICE, ENTRY_PRICE + 0.01, True, config)
        self.assertEqual(result.status, RuleStatus.NOT_TRIGGERED)

    def test_below_trigger_does_not_trigger(self):
        config = PositionManagerConfig(partial_close_trigger_distance=0.0050)
        result = c.partial_close(Direction.UP, ENTRY_PRICE, ENTRY_PRICE + 0.0010, False, config)
        self.assertEqual(result.status, RuleStatus.NOT_TRIGGERED)

    def test_at_or_above_trigger_triggers(self):
        config = PositionManagerConfig(partial_close_trigger_distance=0.0050)
        result = c.partial_close(Direction.UP, ENTRY_PRICE, ENTRY_PRICE + 0.0060, False, config)
        self.assertEqual(result.status, RuleStatus.TRIGGERED)


class TestTimeExit(unittest.TestCase):
    def test_missing_opened_at_is_unevaluable(self):
        result = c.time_exit(None, T0, PositionManagerConfig())
        self.assertEqual(result.status, RuleStatus.UNEVALUABLE)

    def test_within_max_duration_does_not_trigger(self):
        config = PositionManagerConfig(max_duration_seconds=86400.0)
        result = c.time_exit(T0, T0 + timedelta(hours=1), config)
        self.assertEqual(result.status, RuleStatus.NOT_TRIGGERED)

    def test_beyond_max_duration_triggers(self):
        config = PositionManagerConfig(max_duration_seconds=3600.0)
        result = c.time_exit(T0, T0 + timedelta(hours=2), config)
        self.assertEqual(result.status, RuleStatus.TRIGGERED)


class TestEmergencyClose(unittest.TestCase):
    def test_missing_is_unevaluable(self):
        result = c.emergency_close(None)
        self.assertEqual(result.status, RuleStatus.UNEVALUABLE)

    def test_not_active_does_not_trigger(self):
        result = c.emergency_close(False)
        self.assertEqual(result.status, RuleStatus.NOT_TRIGGERED)

    def test_active_triggers(self):
        result = c.emergency_close(True)
        self.assertEqual(result.status, RuleStatus.TRIGGERED)


if __name__ == "__main__":
    unittest.main()
