"""PropFirmValidator tests — verifies this is advisory-only: every
method returns a `RuleFinding`, never blocks, sizes, or evaluates a
candidate."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from phantom_pipeline.compliance_engine import ComplianceEngineConfig
from phantom_pipeline.compliance_engine.models import CheckEvaluation, CheckStatus, ComplianceDecision
from phantom_pipeline.compliance_engine.models import Verdict as ComplianceVerdict
from phantom_pipeline.paper_trading.account_tracker import AccountSnapshot
from phantom_pipeline.paper_trading.prop_firm_validator import (
    FTMO_PROFILE,
    PropFirmProfile,
    PropFirmValidator,
    RuleStatus,
)
from phantom_pipeline.risk_engine import RiskEngineConfig
from phantom_pipeline.risk_engine.models import RiskDecision, RiskTier
from phantom_pipeline.scanner.models import Direction

T0 = datetime(2026, 7, 6, 10, 0, 0, tzinfo=timezone.utc)


def _snapshot(daily_dd=0.0, total_dd=0.0, total_dd_peak=0.0) -> AccountSnapshot:
    return AccountSnapshot(
        schema_version=1, equity=10000.0, day_start_equity=10000.0, initial_equity=10000.0,
        peak_equity=10000.0, daily_drawdown_pct=daily_dd, total_drawdown_pct=total_dd,
        total_drawdown_pct_from_peak=total_dd_peak, timestamp=T0,
    )


def _risk_decision(lot_size) -> RiskDecision:
    return RiskDecision(
        schema_version=1, trace_id="t1", candidate_id="c1", strategy_id="s1",
        symbol="EURUSD", timeframe="M1", timestamp=T0, direction=Direction.UP,
        approved_risk_percent=1.0, approved_risk_amount=100.0, lot_size=lot_size,
        risk_tier=RiskTier.NORMAL, limiting_constraint="none", constraint_evaluations=(),
        reason_codes=(), risk_engine_version="1.0.0-phase1",
    )


def _compliance_decision(check_evaluations) -> ComplianceDecision:
    return ComplianceDecision(
        schema_version=1, trace_id="t1", candidate_id="c1", strategy_id="s1", symbol="EURUSD",
        timeframe="M1", timestamp=T0, direction=Direction.UP, verdict=ComplianceVerdict.APPROVE,
        blocking_rules=(), reason_codes=(), check_evaluations=check_evaluations,
        compliance_engine_version="1.0.0-phase1",
    )


class TestConfigurationAudit(unittest.TestCase):
    def test_stricter_config_passes(self):
        validator = PropFirmValidator(FTMO_PROFILE)
        compliance_config = ComplianceEngineConfig(max_daily_drawdown_percent=3.0, max_total_drawdown_percent=8.0)
        findings = validator.audit_configuration(RiskEngineConfig(), compliance_config)
        self.assertTrue(all(f.status == RuleStatus.PASS for f in findings))

    def test_looser_config_breaches(self):
        validator = PropFirmValidator(FTMO_PROFILE)
        compliance_config = ComplianceEngineConfig(max_daily_drawdown_percent=6.0, max_total_drawdown_percent=8.0)
        findings = validator.audit_configuration(RiskEngineConfig(), compliance_config)
        daily = next(f for f in findings if f.rule_name == "DAILY_DRAWDOWN_CONFIG")
        self.assertEqual(daily.status, RuleStatus.BREACH)


class TestSnapshotEvaluation(unittest.TestCase):
    def test_none_snapshot_is_unevaluable(self):
        validator = PropFirmValidator(FTMO_PROFILE)
        findings = validator.evaluate_snapshot(None)
        self.assertTrue(all(f.status == RuleStatus.UNEVALUABLE for f in findings))

    def test_within_limit_passes(self):
        validator = PropFirmValidator(FTMO_PROFILE)
        findings = validator.evaluate_snapshot(_snapshot(daily_dd=1.0, total_dd=1.0))
        self.assertTrue(all(f.status == RuleStatus.PASS for f in findings))

    def test_approaching_limit_warns(self):
        validator = PropFirmValidator(FTMO_PROFILE)  # 5% daily limit
        findings = validator.evaluate_snapshot(_snapshot(daily_dd=4.2, total_dd=1.0))
        daily = next(f for f in findings if f.rule_name == "DAILY_DRAWDOWN_LIVE")
        self.assertEqual(daily.status, RuleStatus.WARNING)

    def test_at_or_above_limit_breaches(self):
        validator = PropFirmValidator(FTMO_PROFILE)
        findings = validator.evaluate_snapshot(_snapshot(daily_dd=5.0, total_dd=1.0))
        daily = next(f for f in findings if f.rule_name == "DAILY_DRAWDOWN_LIVE")
        self.assertEqual(daily.status, RuleStatus.BREACH)

    def test_peak_basis_used_when_profile_specifies_it(self):
        profile = PropFirmProfile(
            name="TRAILING", max_daily_drawdown_percent=5.0, max_total_drawdown_percent=10.0,
            total_drawdown_basis="PEAK",
        )
        validator = PropFirmValidator(profile)
        findings = validator.evaluate_snapshot(_snapshot(total_dd=0.0, total_dd_peak=11.0))
        total = next(f for f in findings if f.rule_name == "TOTAL_DRAWDOWN_LIVE")
        self.assertEqual(total.status, RuleStatus.BREACH)


class TestLotSizeAndPositionLimits(unittest.TestCase):
    def test_lot_size_unevaluable_when_profile_has_no_cap(self):
        validator = PropFirmValidator(FTMO_PROFILE)
        finding = validator.evaluate_lot_sizes([_risk_decision(5.0)])
        self.assertEqual(finding.status, RuleStatus.UNEVALUABLE)

    def test_lot_size_breach_when_exceeding_configured_cap(self):
        profile = PropFirmProfile(name="CAPPED", max_daily_drawdown_percent=5.0, max_total_drawdown_percent=10.0, max_lot_size=2.0)
        validator = PropFirmValidator(profile)
        finding = validator.evaluate_lot_sizes([_risk_decision(1.0), _risk_decision(3.0)])
        self.assertEqual(finding.status, RuleStatus.BREACH)

    def test_lot_size_never_modifies_the_risk_decision(self):
        profile = PropFirmProfile(name="CAPPED", max_daily_drawdown_percent=5.0, max_total_drawdown_percent=10.0, max_lot_size=2.0)
        validator = PropFirmValidator(profile)
        decision = _risk_decision(3.0)
        validator.evaluate_lot_sizes([decision])
        self.assertEqual(decision.lot_size, 3.0)  # unchanged - advisory only

    def test_position_limit_pass_warning_breach(self):
        profile = PropFirmProfile(name="P", max_daily_drawdown_percent=5.0, max_total_drawdown_percent=10.0, max_open_positions=3)
        validator = PropFirmValidator(profile)
        self.assertEqual(validator.evaluate_position_count(2).status, RuleStatus.PASS)
        self.assertEqual(validator.evaluate_position_count(3).status, RuleStatus.WARNING)
        self.assertEqual(validator.evaluate_position_count(4).status, RuleStatus.BREACH)


class TestRestrictionChecks(unittest.TestCase):
    def test_news_restriction_pass_when_check_passed(self):
        validator = PropFirmValidator(FTMO_PROFILE)
        decisions = [_compliance_decision((CheckEvaluation("NEWS_RESTRICTION", CheckStatus.PASSED, "no blackout"),))]
        news, _weekend = validator.evaluate_restriction_checks(decisions)
        self.assertEqual(news.status, RuleStatus.PASS)

    def test_news_restriction_breach_when_check_failed(self):
        validator = PropFirmValidator(FTMO_PROFILE)
        decisions = [_compliance_decision((CheckEvaluation("NEWS_RESTRICTION", CheckStatus.FAILED, "blackout active"),))]
        news, _weekend = validator.evaluate_restriction_checks(decisions)
        self.assertEqual(news.status, RuleStatus.BREACH)

    def test_unevaluable_when_no_decisions_recorded(self):
        validator = PropFirmValidator(FTMO_PROFILE)
        news, weekend = validator.evaluate_restriction_checks([])
        self.assertEqual(news.status, RuleStatus.UNEVALUABLE)
        self.assertEqual(weekend.status, RuleStatus.UNEVALUABLE)

    def test_unevaluable_when_not_required_by_profile(self):
        profile = PropFirmProfile(
            name="P", max_daily_drawdown_percent=5.0, max_total_drawdown_percent=10.0,
            requires_news_restriction=False, requires_weekend_restriction=False,
        )
        validator = PropFirmValidator(profile)
        news, weekend = validator.evaluate_restriction_checks([])
        self.assertEqual(news.status, RuleStatus.UNEVALUABLE)
        self.assertEqual(weekend.status, RuleStatus.UNEVALUABLE)


class TestBuildStatus(unittest.TestCase):
    def test_overall_status_is_worst_of_all_findings(self):
        validator = PropFirmValidator(FTMO_PROFILE)
        status = validator.build_status(
            risk_config=RiskEngineConfig(),
            compliance_config=ComplianceEngineConfig(max_daily_drawdown_percent=6.0, max_total_drawdown_percent=8.0),
            account_snapshot=_snapshot(daily_dd=1.0, total_dd=1.0),
            risk_decisions=[],
            open_position_count=0,
            compliance_decisions=[],
            now=T0,
        )
        self.assertEqual(status.overall_status, RuleStatus.BREACH)  # from the config audit
        self.assertEqual(status.profile_name, "FTMO")

    def test_all_pass_when_everything_within_limits(self):
        validator = PropFirmValidator(FTMO_PROFILE)
        status = validator.build_status(
            risk_config=RiskEngineConfig(),
            compliance_config=ComplianceEngineConfig(max_daily_drawdown_percent=3.0, max_total_drawdown_percent=8.0),
            account_snapshot=_snapshot(daily_dd=0.5, total_dd=0.5),
            risk_decisions=[],
            open_position_count=0,
            compliance_decisions=[],
            now=T0,
        )
        # Lot size / position limit / restriction checks are UNEVALUABLE for
        # this profile/inputs, never BREACH/WARNING - overall reflects only
        # genuine findings.
        self.assertIn(status.overall_status, (RuleStatus.PASS, RuleStatus.UNEVALUABLE))


if __name__ == "__main__":
    unittest.main()
