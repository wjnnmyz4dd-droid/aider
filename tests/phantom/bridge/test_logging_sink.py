"""`logging_sink.py` tests (Phase 1.5 hotfix).

`_safe_log` deliberately swallows any exception so a logging failure
never affects the bridge's own behavior -- but that same design means a
broken log call fails completely silently. `log_error_report` passed
`extra={"message": ...}` to `logging.Logger.log`, and `"message"`
collides with a reserved `logging.LogRecord` attribute, so
`Logger.makeRecord` raised `KeyError: "Attempt to overwrite 'message'
in LogRecord"` on every single call -- meaning no `ErrorReport` was
ever actually logged, discovered during Phase 1.5 observability
validation. These tests capture real log records to prove the event
now appears, and would have failed against the pre-fix code."""

from __future__ import annotations

import logging
import unittest

from phantom.bridge.logging_sink import log_emergency_stop, log_error_report
from phantom.bridge.models import EmergencyStopState, ErrorReport, SCHEMA_VERSION
from tests.phantom.bridge._fixtures import T0


class _CapturingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


class LoggingSinkTestCase(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger("phantom.bridge")
        self.previous_level = self.logger.level
        self.logger.setLevel(logging.DEBUG)
        self.handler = _CapturingHandler()
        self.logger.addHandler(self.handler)

    def tearDown(self):
        self.logger.removeHandler(self.handler)
        self.logger.setLevel(self.previous_level)


class TestLogErrorReport(LoggingSinkTestCase):
    def test_error_report_is_actually_logged(self):
        error = ErrorReport(
            schema_version=SCHEMA_VERSION, magic_number=20260709,
            error_code="MARKET_CLOSED_OR_NO_QUOTES", message="no quotes for EURUSD",
            context="ExecuteBuy", reported_at=T0,
        )
        log_error_report(error)
        matching = [r for r in self.handler.records if r.msg == "bridge.error_report"]
        self.assertEqual(len(matching), 1, "log_error_report produced no record -- the 'message' key collision regressed")
        self.assertEqual(matching[0].error_code, "MARKET_CLOSED_OR_NO_QUOTES")
        self.assertEqual(matching[0].error_message, "no quotes for EURUSD")

    def test_does_not_raise_for_any_message_content(self):
        # Guards against reintroducing any other LogRecord-reserved key
        # (message, msg, args, levelname, ...) in this function's extra dict.
        for message in ("", "plain", "with \"quotes\"", "unicode: café"):
            error = ErrorReport(
                schema_version=SCHEMA_VERSION, magic_number=20260709,
                error_code="X", message=message, context=None, reported_at=T0,
            )
            log_error_report(error)  # must never raise


class TestLogEmergencyStopSymmetry(LoggingSinkTestCase):
    def test_activation_and_deactivation_both_produce_records(self):
        log_emergency_stop(EmergencyStopState(active=True, reason="test", activated_at=T0))
        log_emergency_stop(EmergencyStopState(active=False, reason=None, activated_at=None))
        matching = [r for r in self.handler.records if r.msg == "bridge.emergency_stop"]
        self.assertEqual(len(matching), 2)
        self.assertTrue(matching[0].active)
        self.assertFalse(matching[1].active)


if __name__ == "__main__":
    unittest.main()
