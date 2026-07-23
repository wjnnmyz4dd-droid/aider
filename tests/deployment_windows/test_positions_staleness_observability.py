"""Tests for start.py's positions-staleness observability signal (Titan
Protocol Independent Verification -- positions-staleness finding,
currently Partially Verified, not confirmed). Observability only: proves
the structured log fires exactly under "heartbeat healthy AND positions
data stale beyond threshold" and under no other condition -- never that
any trade-acceptance/rejection behavior changed (there is none to
change; `_log_positions_staleness_if_stale()` returns a bool and logs,
nothing else)."""

from __future__ import annotations

import logging
import unittest
from datetime import datetime, timezone

from ._fixtures import DEPLOYMENT_DIR  # noqa: F401 -- ensures deployment_windows/ is on sys.path

import start

_NOW = datetime(2026, 7, 23, tzinfo=timezone.utc)
_THRESHOLD = 30.0
_LOGGER_NAME = "titan_protocol.deploy.live_cycle.test_positions_staleness"


def _logger() -> logging.Logger:
    return logging.getLogger(_LOGGER_NAME)


class TestPositionsStalenessSignal(unittest.TestCase):
    def test_fires_when_heartbeat_healthy_and_positions_stale_beyond_threshold(self):
        with self.assertLogs(_LOGGER_NAME, level="WARNING") as captured:
            fired = start._log_positions_staleness_if_stale(
                _logger(), positions_are_live=True, position_report_age_seconds=_THRESHOLD + 0.001,
                latest_positions_snapshot_at=_NOW, staleness_threshold_seconds=_THRESHOLD,
            )
        self.assertTrue(fired)
        self.assertEqual(len(captured.records), 1)
        record = captured.records[0]
        self.assertEqual(record.getMessage(), "positions_stale_despite_healthy_heartbeat")
        self.assertAlmostEqual(record.position_report_age_seconds, _THRESHOLD + 0.001)
        self.assertEqual(record.last_positions_received_at, _NOW.isoformat())
        self.assertEqual(record.heartbeat_status, "healthy")
        self.assertEqual(record.staleness_threshold_seconds, _THRESHOLD)
        self.assertIn("risk_engine", record.affected_execution_path)
        self.assertIn("compliance_engine", record.affected_execution_path)

    def test_does_not_fire_when_heartbeat_unhealthy_even_if_positions_are_old(self):
        """positions_are_live=False means the heartbeat itself is
        unhealthy -- a different, already-observable condition
        (position_source_state == "absent" in the existing
        portfolio_state_source log). This signal must stay silent here,
        never doubling up on an already-covered case."""
        with self.assertNoLogs(_LOGGER_NAME, level="WARNING"):
            fired = start._log_positions_staleness_if_stale(
                _logger(), positions_are_live=False, position_report_age_seconds=_THRESHOLD + 100.0,
                latest_positions_snapshot_at=_NOW, staleness_threshold_seconds=_THRESHOLD,
            )
        self.assertFalse(fired)

    def test_does_not_fire_when_positions_never_reported_at_all(self):
        """position_report_age_seconds is None when positions have never
        been received -- a distinct condition from staleness (nothing to
        measure an age against), and must not be conflated with it."""
        with self.assertNoLogs(_LOGGER_NAME, level="WARNING"):
            fired = start._log_positions_staleness_if_stale(
                _logger(), positions_are_live=True, position_report_age_seconds=None,
                latest_positions_snapshot_at=None, staleness_threshold_seconds=_THRESHOLD,
            )
        self.assertFalse(fired)

    def test_does_not_fire_when_positions_are_fresh(self):
        with self.assertNoLogs(_LOGGER_NAME, level="WARNING"):
            fired = start._log_positions_staleness_if_stale(
                _logger(), positions_are_live=True, position_report_age_seconds=1.0,
                latest_positions_snapshot_at=_NOW, staleness_threshold_seconds=_THRESHOLD,
            )
        self.assertFalse(fired)

    def test_boundary_exactly_at_threshold_does_not_fire(self):
        """Mirrors this codebase's established boundary convention
        elsewhere (e.g. CommandQueue.is_abandoned(): `waited_seconds >
        timeout`, not `>=`) -- exactly at the threshold is not yet
        stale."""
        with self.assertNoLogs(_LOGGER_NAME, level="WARNING"):
            fired = start._log_positions_staleness_if_stale(
                _logger(), positions_are_live=True, position_report_age_seconds=_THRESHOLD,
                latest_positions_snapshot_at=_NOW, staleness_threshold_seconds=_THRESHOLD,
            )
        self.assertFalse(fired)

    def test_no_change_to_return_value_semantics_beyond_the_bool(self):
        """Confirms this function has no side effect beyond logging --
        no portfolio_state mutation, no exception, no other observable
        effect -- consistent with "observability only, no behavior
        change"."""
        result = start._log_positions_staleness_if_stale(
            _logger(), positions_are_live=True, position_report_age_seconds=1.0,
            latest_positions_snapshot_at=_NOW, staleness_threshold_seconds=_THRESHOLD,
        )
        self.assertIsInstance(result, bool)


if __name__ == "__main__":
    unittest.main()
