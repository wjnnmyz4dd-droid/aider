"""Transport-integrity validation tests (`ADR-023` §3, §6)."""

from __future__ import annotations

import unittest
from datetime import timedelta

from phantom_pipeline.ea_bridge import validation
from phantom_pipeline.scanner.models import Direction
from tests.phantom_pipeline.ea_bridge._fixtures import T0, make_config


class TestCheckApiKey(unittest.TestCase):
    def test_missing_key_rejected(self):
        self.assertEqual(validation.check_api_key(None, make_config()), "missing_api_key")

    def test_wrong_key_rejected(self):
        self.assertEqual(validation.check_api_key("wrong", make_config()), "invalid_api_key")

    def test_correct_key_accepted(self):
        config = make_config()
        self.assertIsNone(validation.check_api_key(config.api_key, config))


class TestCheckMagicNumber(unittest.TestCase):
    def test_mismatch_rejected(self):
        self.assertEqual(validation.check_magic_number(1, make_config()), "magic_number_mismatch")

    def test_match_accepted(self):
        config = make_config()
        self.assertIsNone(validation.check_magic_number(config.magic_number, config))


class TestCheckSymbolAllowed(unittest.TestCase):
    def test_none_symbol_skipped(self):
        self.assertIsNone(validation.check_symbol_allowed(None, make_config()))

    def test_disallowed_symbol_rejected(self):
        self.assertEqual(validation.check_symbol_allowed("XAUUSD", make_config()), "symbol_not_allowed")

    def test_allowed_symbol_accepted(self):
        self.assertIsNone(validation.check_symbol_allowed("EURUSD", make_config()))


class TestCheckVolume(unittest.TestCase):
    def test_none_skipped(self):
        self.assertIsNone(validation.check_volume(None, make_config()))

    def test_zero_or_negative_rejected(self):
        self.assertEqual(validation.check_volume(0.0, make_config()), "invalid_volume")
        self.assertEqual(validation.check_volume(-1.0, make_config()), "invalid_volume")

    def test_over_max_rejected(self):
        self.assertEqual(validation.check_volume(10.0, make_config(max_lot_size=5.0)), "volume_exceeds_max")

    def test_within_bounds_accepted(self):
        self.assertIsNone(validation.check_volume(1.0, make_config()))


class TestCheckStopLossTakeProfit(unittest.TestCase):
    def test_negative_or_zero_stop_loss_rejected(self):
        self.assertEqual(validation.check_stop_loss_take_profit(0.0, None), "invalid_stop_loss")
        self.assertEqual(validation.check_stop_loss_take_profit(-1.0, None), "invalid_stop_loss")

    def test_negative_or_zero_take_profit_rejected(self):
        self.assertEqual(validation.check_stop_loss_take_profit(None, 0.0), "invalid_take_profit")

    def test_none_values_accepted(self):
        self.assertIsNone(validation.check_stop_loss_take_profit(None, None))

    def test_positive_values_accepted(self):
        self.assertIsNone(validation.check_stop_loss_take_profit(1.09, 1.11))


class TestCheckDirectionalSanity(unittest.TestCase):
    def test_no_reference_price_skips_check(self):
        self.assertIsNone(validation.check_directional_sanity(Direction.UP, 1.20, 1.05, None))

    def test_up_stop_loss_on_wrong_side_rejected(self):
        reason = validation.check_directional_sanity(Direction.UP, 1.11, 1.12, 1.10)
        self.assertEqual(reason, "stop_loss_wrong_side")

    def test_up_take_profit_on_wrong_side_rejected(self):
        reason = validation.check_directional_sanity(Direction.UP, 1.09, 1.09, 1.10)
        self.assertEqual(reason, "take_profit_wrong_side")

    def test_down_stop_loss_on_wrong_side_rejected(self):
        reason = validation.check_directional_sanity(Direction.DOWN, 1.09, 1.08, 1.10)
        self.assertEqual(reason, "stop_loss_wrong_side")

    def test_down_take_profit_on_wrong_side_rejected(self):
        reason = validation.check_directional_sanity(Direction.DOWN, 1.11, 1.11, 1.10)
        self.assertEqual(reason, "take_profit_wrong_side")

    def test_up_valid_sl_tp_accepted(self):
        self.assertIsNone(validation.check_directional_sanity(Direction.UP, 1.09, 1.11, 1.10))

    def test_down_valid_sl_tp_accepted(self):
        self.assertIsNone(validation.check_directional_sanity(Direction.DOWN, 1.11, 1.09, 1.10))


class TestCheckTimestampFresh(unittest.TestCase):
    def test_future_timestamp_rejected(self):
        reason = validation.check_timestamp_fresh(T0 + timedelta(seconds=5), T0, ttl_seconds=15.0)
        self.assertEqual(reason, "timestamp_in_future")

    def test_stale_timestamp_rejected(self):
        reason = validation.check_timestamp_fresh(T0, T0 + timedelta(seconds=20), ttl_seconds=15.0)
        self.assertEqual(reason, "stale_timestamp")

    def test_fresh_timestamp_accepted(self):
        reason = validation.check_timestamp_fresh(T0, T0 + timedelta(seconds=5), ttl_seconds=15.0)
        self.assertIsNone(reason)


class TestValidateInboundMessage(unittest.TestCase):
    def test_returns_first_failure_in_order(self):
        config = make_config()
        self.assertEqual(
            validation.validate_inbound_message(None, config.magic_number, config), "missing_api_key"
        )
        self.assertEqual(
            validation.validate_inbound_message(config.api_key, -1, config), "magic_number_mismatch"
        )
        self.assertEqual(
            validation.validate_inbound_message(config.api_key, config.magic_number, config, symbol="XAUUSD"),
            "symbol_not_allowed",
        )

    def test_all_checks_pass(self):
        config = make_config()
        self.assertIsNone(
            validation.validate_inbound_message(config.api_key, config.magic_number, config, symbol="EURUSD")
        )


class TestValidateCommandExecutionReport(unittest.TestCase):
    def test_missing_execution_id_rejected(self):
        config = make_config()
        self.assertEqual(
            validation.validate_command_execution_report("", config.magic_number, config),
            "missing_execution_id",
        )

    def test_magic_number_mismatch_rejected(self):
        config = make_config()
        self.assertEqual(
            validation.validate_command_execution_report("exec-1", -1, config), "magic_number_mismatch"
        )

    def test_valid_report_accepted(self):
        config = make_config()
        self.assertIsNone(
            validation.validate_command_execution_report("exec-1", config.magic_number, config)
        )


if __name__ == "__main__":
    unittest.main()
