"""Tests for health_check.py's RUN STATUS panel (item 10) -- the
concise, single-location diagnostic view an operator reads to determine
why Titan is or is not trading, without cross-referencing several other
health.json fields or the log file."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout

from ._fixtures import DEPLOYMENT_DIR  # noqa: F401 -- ensures deployment_windows/ is on sys.path

import health_check


class TestFormatAge(unittest.TestCase):
    def test_none_is_never(self):
        self.assertEqual(health_check._format_age(None), "never")

    def test_seconds_formatted_to_one_decimal(self):
        self.assertEqual(health_check._format_age(3.456), "3.5s ago")

    def test_zero_is_formatted_not_treated_as_missing(self):
        self.assertEqual(health_check._format_age(0.0), "0.0s ago")


class TestPrintRunStatusPanel(unittest.TestCase):
    def _run(self, run_status):
        buf = io.StringIO()
        with redirect_stdout(buf):
            health_check._print_run_status_panel(run_status)
        return buf.getvalue()

    def test_none_prints_not_available(self):
        output = self._run(None)
        self.assertIn("RUN STATUS", output)
        self.assertIn("NOT AVAILABLE", output)

    def test_empty_dict_prints_not_available(self):
        output = self._run({})
        self.assertIn("NOT AVAILABLE", output)

    def test_full_payload_surfaces_every_field(self):
        run_status = {
            "communication_mode": "socket",
            "http_fallback_enabled": True,
            "bridge_connection_status": "connected",
            "runtime_status": "DEGRADED",
            "last_heartbeat_age_seconds": 2.5,
            "last_position_report_age_seconds": 4.1,
            "in_flight_command_count": 1,
            "open_positions_per_pair": {"EURUSD": 1},
            "configured_max_positions_per_pair": 1,
            "account_report_age_seconds": 3.2,
            "configured_max_account_state_age_seconds": 30.0,
            "account_state_fresh": True,
            "compliance_state": "BLOCKED",
            "compliance_block_reason": "daily loss limit reached",
            "last_submitted_correlation_id": "live-1:EURUSD",
            "pairs": {
                "EURUSD": {"outcome": "COMPLIANCE_REJECTED", "reason": "MAX_POSITIONS_PER_PAIR_EXCEEDED.", "correlation_id": None},
                "GBPUSD": {"outcome": "SUBMITTED", "reason": None, "correlation_id": "live-5:GBPUSD"},
            },
        }
        output = self._run(run_status)
        self.assertIn("socket", output)
        self.assertIn("enabled", output)
        self.assertIn("connected", output)
        self.assertIn("DEGRADED", output)
        self.assertIn("2.5s ago", output)
        self.assertIn("4.1s ago", output)
        self.assertIn("{'EURUSD': 1}", output)
        self.assertIn("BLOCKED (daily loss limit reached)", output)
        self.assertIn("live-1:EURUSD", output)
        self.assertIn("EURUSD: COMPLIANCE_REJECTED -- MAX_POSITIONS_PER_PAIR_EXCEEDED.", output)
        self.assertIn("GBPUSD: SUBMITTED (correlation_id=live-5:GBPUSD)", output)
        self.assertIn("3.2s ago (fresh)", output)
        self.assertIn("Configured max account age: 30.0s", output)

    def test_ready_state_omits_reason_parenthetical(self):
        output = self._run({"compliance_state": "READY", "compliance_block_reason": None})
        self.assertIn("Compliance state          : READY", output)

    def test_no_pairs_reports_none_evaluated(self):
        output = self._run({"pairs": {}})
        self.assertIn("no pairs evaluated yet", output)


class TestPrintRunStatusPanelAccountStateFreshness(unittest.TestCase):
    """ACCOUNT_STATE_STALE diagnostics (fix option (b))."""

    def _run(self, run_status):
        buf = io.StringIO()
        with redirect_stdout(buf):
            health_check._print_run_status_panel(run_status)
        return buf.getvalue()

    def test_stale_account_state_labeled_stale(self):
        output = self._run({
            "account_report_age_seconds": 45.0, "account_state_fresh": False,
            "configured_max_account_state_age_seconds": 30.0,
        })
        self.assertIn("45.0s ago (STALE)", output)

    def test_never_reported_labeled_unknown_not_stale(self):
        """account_state_fresh is None (never reported at all) --
        must not be mislabeled as either 'fresh' or 'STALE'."""
        output = self._run({"account_report_age_seconds": None, "account_state_fresh": None})
        self.assertIn("never (unknown)", output)


if __name__ == "__main__":
    unittest.main()
