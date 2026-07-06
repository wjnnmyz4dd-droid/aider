"""DeploymentValidator tests — the 10 named go-live checks, aggregation
into a readiness report with blockers, and the `emergency_stop_functional`
check driving PositionManager's own real `EMERGENCY_CLOSE` mechanism via
the existing orchestrator (never a second, invented kill switch)."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from phantom_pipeline.deployment.deployment_validator import REQUIRED_CHECK_NAMES, DeploymentValidator
from phantom_pipeline.deployment.models import DeploymentProfile
from phantom_pipeline.position_manager.models import LifecycleState, ManagementAction
from phantom_pipeline.scanner.models import Direction
from tests.phantom_pipeline.orchestrator._fixtures import T0, build_orchestrator

NOW = datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc)


def _all_pass_checks():
    return {name: (lambda: True) for name in REQUIRED_CHECK_NAMES}


class TestAllChecksPass(unittest.TestCase):
    def test_report_is_all_passed_with_no_blockers(self):
        validator = DeploymentValidator(_all_pass_checks())
        report = validator.run(DeploymentProfile.LIVE, NOW)

        self.assertTrue(report.all_passed)
        self.assertEqual(report.blockers, ())
        self.assertEqual(len(report.checks), len(REQUIRED_CHECK_NAMES))


class TestFailingCheck(unittest.TestCase):
    def test_a_failing_check_is_reported_as_a_blocker(self):
        checks = _all_pass_checks()
        checks["mt5_connected"] = lambda: False
        validator = DeploymentValidator(checks)

        report = validator.run(DeploymentProfile.LIVE, NOW)

        self.assertFalse(report.all_passed)
        self.assertIn("mt5_connected", report.blockers)

    def test_a_raising_probe_is_treated_as_a_failed_check_not_an_exception(self):
        checks = _all_pass_checks()

        def _raises():
            raise RuntimeError("dashboard unreachable")

        checks["dashboard_online"] = _raises
        validator = DeploymentValidator(checks)

        report = validator.run(DeploymentProfile.LIVE, NOW)

        self.assertFalse(report.all_passed)
        dashboard_check = next(c for c in report.checks if c.name == "dashboard_online")
        self.assertFalse(dashboard_check.passed)
        self.assertIn("probe raised", dashboard_check.detail)

    def test_missing_probe_is_a_failed_check(self):
        checks = _all_pass_checks()
        del checks["watchdog_active"]
        validator = DeploymentValidator(checks)

        report = validator.run(DeploymentProfile.LIVE, NOW)

        watchdog_check = next(c for c in report.checks if c.name == "watchdog_active")
        self.assertFalse(watchdog_check.passed)


class TestEmergencyStopFunctionalUsesRealMechanism(unittest.TestCase):
    def test_probe_backed_by_position_managers_own_emergency_close_path(self):
        orchestrator = build_orchestrator()

        def emergency_stop_probe() -> bool:
            result = orchestrator.manage_position(
                position_id="probe-position",
                trace_id="probe-trace",
                direction=Direction.UP,
                entry_price=1.1000,
                lifecycle_state=LifecycleState.FILLED,
                current_price=1.1000,
                current_stop_loss=1.0950,
                current_take_profit=1.1100,
                opened_at=T0,
                market_data_timestamp=T0,
                broker_position_exists=True,
                compliance_kill_switch_active=True,
                now=T0,
            )
            return result.decision.action == ManagementAction.EMERGENCY_CLOSE

        checks = _all_pass_checks()
        checks["emergency_stop_functional"] = emergency_stop_probe
        validator = DeploymentValidator(checks)

        report = validator.run(DeploymentProfile.LIVE, NOW)

        emergency_check = next(c for c in report.checks if c.name == "emergency_stop_functional")
        self.assertTrue(emergency_check.passed)

    def test_probe_fails_when_kill_switch_does_not_trigger_emergency_close(self):
        orchestrator = build_orchestrator()

        def broken_probe() -> bool:
            result = orchestrator.manage_position(
                position_id="probe-position",
                trace_id="probe-trace",
                direction=Direction.UP,
                entry_price=1.1000,
                lifecycle_state=LifecycleState.FILLED,
                current_price=1.1000,
                current_stop_loss=1.0950,
                current_take_profit=1.1100,
                opened_at=T0,
                market_data_timestamp=T0,
                broker_position_exists=True,
                compliance_kill_switch_active=False,  # kill switch NOT active
                now=T0,
            )
            return result.decision.action == ManagementAction.EMERGENCY_CLOSE

        checks = _all_pass_checks()
        checks["emergency_stop_functional"] = broken_probe
        validator = DeploymentValidator(checks)

        report = validator.run(DeploymentProfile.LIVE, NOW)

        emergency_check = next(c for c in report.checks if c.name == "emergency_stop_functional")
        self.assertFalse(emergency_check.passed)


if __name__ == "__main__":
    unittest.main()
