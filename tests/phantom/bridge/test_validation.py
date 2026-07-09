"""Transport-integrity validation tests (Phase 1)."""

from __future__ import annotations

import unittest
from datetime import timedelta

from phantom.bridge import validation
from phantom.bridge.models import ErrorCode
from tests.phantom.bridge._fixtures import T0, make_config


class TestCheckApiKey(unittest.TestCase):
    def test_missing_key_rejected(self):
        self.assertEqual(validation.check_api_key(None, make_config()), ErrorCode.MISSING_API_KEY)

    def test_wrong_key_rejected(self):
        self.assertEqual(validation.check_api_key("wrong", make_config()), ErrorCode.INVALID_API_KEY)

    def test_correct_key_accepted(self):
        config = make_config()
        self.assertIsNone(validation.check_api_key(config.api_key, config))


class TestCheckMagicNumber(unittest.TestCase):
    def test_mismatch_rejected(self):
        self.assertEqual(validation.check_magic_number(1, make_config()), ErrorCode.MAGIC_NUMBER_MISMATCH)

    def test_match_accepted(self):
        config = make_config()
        self.assertIsNone(validation.check_magic_number(config.magic_number, config))


class TestCheckSymbolAllowed(unittest.TestCase):
    def test_none_symbol_skipped(self):
        self.assertIsNone(validation.check_symbol_allowed(None, make_config()))

    def test_disallowed_symbol_rejected(self):
        self.assertEqual(validation.check_symbol_allowed("XAUUSD", make_config()), ErrorCode.SYMBOL_NOT_ALLOWED)

    def test_allowed_symbol_accepted(self):
        self.assertIsNone(validation.check_symbol_allowed("EURUSD", make_config()))


class TestCheckVolume(unittest.TestCase):
    def test_none_skipped(self):
        self.assertIsNone(validation.check_volume(None, make_config()))

    def test_zero_or_negative_rejected(self):
        self.assertEqual(validation.check_volume(0.0, make_config()), ErrorCode.INVALID_VOLUME)
        self.assertEqual(validation.check_volume(-1.0, make_config()), ErrorCode.INVALID_VOLUME)

    def test_over_max_rejected(self):
        self.assertEqual(validation.check_volume(10.0, make_config(max_lot_size=5.0)), ErrorCode.VOLUME_EXCEEDS_MAX)

    def test_within_bounds_accepted(self):
        self.assertIsNone(validation.check_volume(1.0, make_config()))


class TestCheckStopLossTakeProfit(unittest.TestCase):
    def test_negative_or_zero_stop_loss_rejected(self):
        self.assertEqual(validation.check_stop_loss_take_profit(0.0, None), ErrorCode.INVALID_STOP_LOSS)
        self.assertEqual(validation.check_stop_loss_take_profit(-1.0, None), ErrorCode.INVALID_STOP_LOSS)

    def test_negative_or_zero_take_profit_rejected(self):
        self.assertEqual(validation.check_stop_loss_take_profit(None, 0.0), ErrorCode.INVALID_TAKE_PROFIT)

    def test_none_values_accepted(self):
        self.assertIsNone(validation.check_stop_loss_take_profit(None, None))

    def test_positive_values_accepted(self):
        self.assertIsNone(validation.check_stop_loss_take_profit(1.09, 1.11))


class TestCheckTimestampFresh(unittest.TestCase):
    def test_future_timestamp_rejected(self):
        reason = validation.check_timestamp_fresh(T0 + timedelta(seconds=5), T0, ttl_seconds=15.0)
        self.assertEqual(reason, ErrorCode.TIMESTAMP_IN_FUTURE)

    def test_stale_timestamp_rejected(self):
        reason = validation.check_timestamp_fresh(T0, T0 + timedelta(seconds=20), ttl_seconds=15.0)
        self.assertEqual(reason, ErrorCode.STALE_TIMESTAMP)

    def test_fresh_timestamp_accepted(self):
        reason = validation.check_timestamp_fresh(T0, T0 + timedelta(seconds=5), ttl_seconds=15.0)
        self.assertIsNone(reason)


class TestValidateInboundMessage(unittest.TestCase):
    def test_returns_first_failure_in_order(self):
        config = make_config()
        self.assertEqual(
            validation.validate_inbound_message(None, config.magic_number, config), ErrorCode.MISSING_API_KEY
        )
        self.assertEqual(
            validation.validate_inbound_message(config.api_key, -1, config), ErrorCode.MAGIC_NUMBER_MISMATCH
        )
        self.assertEqual(
            validation.validate_inbound_message(config.api_key, config.magic_number, config, symbol="XAUUSD"),
            ErrorCode.SYMBOL_NOT_ALLOWED,
        )

    def test_all_checks_pass(self):
        config = make_config()
        self.assertIsNone(
            validation.validate_inbound_message(config.api_key, config.magic_number, config, symbol="EURUSD")
        )


class TestValidateCommandExecutionReport(unittest.TestCase):
    def test_missing_correlation_id_rejected(self):
        config = make_config()
        self.assertEqual(
            validation.validate_command_execution_report("", config.magic_number, config),
            ErrorCode.MISSING_CORRELATION_ID,
        )

    def test_magic_number_mismatch_rejected(self):
        config = make_config()
        self.assertEqual(
            validation.validate_command_execution_report("corr-1", -1, config), ErrorCode.MAGIC_NUMBER_MISMATCH
        )

    def test_valid_report_accepted(self):
        config = make_config()
        self.assertIsNone(
            validation.validate_command_execution_report("corr-1", config.magic_number, config)
        )


if __name__ == "__main__":
    unittest.main()
