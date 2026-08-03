"""Logging tests (ADR-011 §12) — structured only, never `print()`, and a
logging failure never propagates."""

from __future__ import annotations

import logging
import unittest
from unittest.mock import patch

from phantom_pipeline.watchdog.logging_sink import log_alert, log_component_health, log_recovery_attempt
from phantom_pipeline.watchdog.models import (
    Alert,
    AlertClass,
    ComponentHealth,
    ComponentKind,
    HealthState,
    RecoveryActionType,
    RecoveryOutcome,
    RecoveryStatus,
)
from tests.phantom_pipeline.watchdog._fixtures import T0


class TestLoggingSink(unittest.TestCase):
    def test_log_component_health_does_not_raise(self):
        health = ComponentHealth("scanner", ComponentKind.PIPELINE_STAGE, HealthState.HEALTHY, "ok", T0)
        log_component_health("trace-1", health)

    def test_log_recovery_attempt_does_not_raise(self):
        status = RecoveryStatus("scanner", False, False, RecoveryActionType.RESTART_SERVICE, RecoveryOutcome.SUCCEEDED, 1, T0)
        log_recovery_attempt("trace-1", status, "recovery action RESTART_SERVICE succeeded")

    def test_log_alert_does_not_raise(self):
        alert = Alert(1, "trace-1", "scanner", AlertClass.CRITICAL, HealthState.CRITICAL, "down", 1, T0)
        log_alert(alert)

    def test_logging_failure_is_swallowed_not_propagated(self):
        health = ComponentHealth("scanner", ComponentKind.PIPELINE_STAGE, HealthState.HEALTHY, "ok", T0)
        with patch("phantom_pipeline.watchdog.logging_sink.logger.log", side_effect=RuntimeError("boom")):
            log_component_health("trace-1", health)  # must not raise


if __name__ == "__main__":
    unittest.main()
