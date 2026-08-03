"""ADR-037 Production Activation Plan (bb8b4a6) Phase D: the mandatory
`start.py --dry-run` mechanism -- `bridge_submit=None` makes Bridge
submission structurally unreachable, and the dry-run-only
`--dry-run-orb-pairs` Gate A override is fail-closed (refused without
`--dry-run`), scoped to that one process, and never persisted anywhere
(the real `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` source constant, and the
shipped config files, are unaffected)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from ._fixtures import DEPLOYMENT_DIR, EXAMPLE_CONFIG_PATH, TEST_API_KEY_ENV_VAR, load_example_config

import start

from titan_protocol.strategy_engine.config import DEFAULT_APPROVED_PAIRS_BY_STRATEGY
from titan_protocol.strategy_engine.models import StrategyId


def _orb_gate_a_width() -> int:
    for sid, pairs in DEFAULT_APPROVED_PAIRS_BY_STRATEGY:
        if sid is StrategyId.OPENING_RANGE_BREAKOUT:
            return len(pairs)
    return 0


class TestDryRunOrbPairsFailsClosedWithoutDryRun(unittest.TestCase):
    """The override must never be usable to broaden a live-submitting
    process -- refused before any config is even loaded."""

    def test_run_foreground_refuses_when_dry_run_orb_pairs_given_without_dry_run(self):
        exit_code = start.run_foreground(
            Path("/nonexistent/does/not/matter.json"), dry_run=False, dry_run_orb_pairs=("EURUSD",),
        )
        self.assertEqual(exit_code, 2)

    def test_launch_and_report_refuses_when_dry_run_orb_pairs_given_without_dry_run(self):
        exit_code = start.launch_and_report(
            Path("/nonexistent/does/not/matter.json"), dry_run=False, dry_run_orb_pairs=("EURUSD",),
        )
        self.assertEqual(exit_code, 2)

    def test_main_cli_refuses_when_dry_run_orb_pairs_given_without_dry_run(self):
        argv = ["start.py", "--dry-run-orb-pairs=EURUSD,GBPUSD,USDJPY", "--config", str(EXAMPLE_CONFIG_PATH)]
        old_argv = sys.argv
        sys.argv = argv
        try:
            exit_code = start.main()
        finally:
            sys.argv = old_argv
        self.assertEqual(exit_code, 2)


class TestDryRunOrbPairsOverrideNeverTouchesTheRealSourceConstant(unittest.TestCase):
    """Before and after exercising the override (via a real subprocess
    boot, not merely a unit call), the actual
    `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` source constant this test
    process itself imported must show Gate A still closed for ORB --
    proving the override is genuinely process-local and never written
    back to source or any config file."""

    def test_gate_a_source_constant_unaffected_by_a_real_dry_run_boot(self):
        self.assertEqual(_orb_gate_a_width(), 0, "Gate A must be closed before this test runs")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = load_example_config()
            os.environ[TEST_API_KEY_ENV_VAR] = "test-key-value"
            config["bridge"]["api_key_env_var"] = TEST_API_KEY_ENV_VAR
            config["evidence_engine"]["opening_range_anchors"] = [
                {"session": "LONDON", "start_hour_utc": 8, "start_minute_utc": 0},
                {"session": "LONDON_NEW_YORK_OVERLAP", "start_hour_utc": 13, "start_minute_utc": 0},
                {"session": "EARLY_NEW_YORK", "start_hour_utc": 13, "start_minute_utc": 30},
            ]
            config["opportunity_selection_engine"]["cross_pair_selection_enabled"] = True
            config["opportunity_selection_engine"]["enabled_windows"] = [
                {"session": "LONDON", "anchor_hour_utc": 8, "anchor_minute_utc": 0, "enabled": True},
                {"session": "LONDON_NEW_YORK_OVERLAP", "anchor_hour_utc": 13, "anchor_minute_utc": 0, "enabled": True},
                {"session": "EARLY_NEW_YORK", "anchor_hour_utc": 13, "anchor_minute_utc": 30, "enabled": True},
            ]
            config["logging"] = {
                "log_dir": str(tmp_path / "logs"), "log_level": "INFO",
                "state_dir": str(tmp_path / "state"), "data_dir": str(tmp_path / "data"),
            }
            config_path = tmp_path / "titan_protocol_config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")

            env = dict(os.environ)
            proc = subprocess.Popen(
                [
                    sys.executable, "-u", str(DEPLOYMENT_DIR / "start.py"),
                    "--dry-run", "--dry-run-orb-pairs=EURUSD,GBPUSD,USDJPY",
                    "--foreground", "--config", str(config_path),
                ],
                cwd=str(DEPLOYMENT_DIR), env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            try:
                time.sleep(3.0)
                self.assertIsNone(proc.poll(), "the dry-run process exited early -- it should still be running")
            finally:
                proc.terminate()
                try:
                    output, _ = proc.communicate(timeout=5.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    output, _ = proc.communicate(timeout=5.0)

        self.assertIn("DRY RUN MODE ACTIVE", output)
        self.assertIn("dry_run_orb_pairs_override_active", output)
        self.assertIn("validated OK", output)
        self.assertIn("Bridge HTTP service listening", output)
        self.assertNotIn("FAILED", output)
        self.assertNotIn("Traceback", output)

        # The real, importable source constant this test process itself
        # loaded is still exactly as closed as it was before the
        # subprocess ran -- the override never escaped that one child
        # process.
        self.assertEqual(_orb_gate_a_width(), 0)


if __name__ == "__main__":
    unittest.main()
