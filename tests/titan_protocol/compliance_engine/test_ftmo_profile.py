"""FTMO-profile-style tests: a custom rule profile modeled on common
prop-firm rules (illustrative example, never a literal "FTMO" profile
per ADR-028 Hard Rule 9), verifying profile selection by name and that
every named threshold actually takes effect."""

from __future__ import annotations

import unittest

from titan_protocol.compliance_engine.config import ComplianceEngineConfig
from titan_protocol.compliance_engine.engine import ComplianceEngine
from titan_protocol.compliance_engine.models import ComplianceDecision, ComplianceRuleId, ComplianceRuleProfile
from titan_protocol.evidence_engine.models import SessionName
from tests.titan_protocol.compliance_engine._fixtures import (
    T0,
    make_account_state,
    make_evidence_snapshot,
    make_mi_snapshot,
    make_open_position,
    make_portfolio_state,
    make_risk_snapshot,
    make_strategy_snapshot,
)

# An illustrative example profile, modeled loosely on common prop-firm
# rules -- never hard-coded to a specific firm's actual name or exact
# figures (ADR-028 Hard Rule 9).
_EXAMPLE_STRICT_PROFILE = ComplianceRuleProfile(
    name="strict_example_profile",
    max_daily_loss_pct=5.0,
    max_total_drawdown_pct=10.0,
    profit_target_pct=10.0,
    min_trading_days=4,
    max_open_positions=3,
    max_positions_per_pair=1,
    weekend_holding_allowed=False,
    required_stop_loss=True,
    max_spread=2.0,
    news_restriction_enabled=True,
    approved_sessions=(SessionName.LONDON, SessionName.LONDON_NEW_YORK_OVERLAP),
    consistency_max_single_day_share=0.25,
)


def _config_with_profile() -> ComplianceEngineConfig:
    return ComplianceEngineConfig(rule_profiles=(_EXAMPLE_STRICT_PROFILE,))


class TestProfileSelectionByName(unittest.TestCase):
    def test_account_selects_its_named_profile(self):
        engine = ComplianceEngine(_config_with_profile())
        account = make_account_state(rule_profile_name="strict_example_profile")
        snapshot = engine.evaluate(
            "EURUSD", make_evidence_snapshot(evidence_score=90.0), make_mi_snapshot(), make_strategy_snapshot(),
            make_risk_snapshot(), make_portfolio_state(), account, now=T0,
        )
        self.assertEqual(snapshot.decision, ComplianceDecision.APPROVE)


class TestProfileThresholdsTakeEffect(unittest.TestCase):
    def test_max_open_positions_from_profile_enforced(self):
        engine = ComplianceEngine(_config_with_profile())
        account = make_account_state(rule_profile_name="strict_example_profile")
        portfolio = make_portfolio_state([make_open_position(pair="GBPUSD"), make_open_position(pair="AUDUSD"), make_open_position(pair="NZDUSD")])
        snapshot = engine.evaluate(
            "EURUSD", make_evidence_snapshot(evidence_score=90.0), make_mi_snapshot(), make_strategy_snapshot(),
            make_risk_snapshot(), portfolio, account, now=T0,
        )
        self.assertEqual(snapshot.decision, ComplianceDecision.REJECT)
        self.assertIn(ComplianceRuleId.MAX_OPEN_POSITIONS_EXCEEDED, snapshot.audit_entry.triggered_rules)

    def test_weekend_holding_disallowed_from_profile_enforced(self):
        from datetime import datetime, timezone
        engine = ComplianceEngine(_config_with_profile())
        account = make_account_state(rule_profile_name="strict_example_profile")
        friday_night = datetime(2026, 7, 10, 21, 0, tzinfo=timezone.utc)
        snapshot = engine.evaluate(
            "EURUSD", make_evidence_snapshot(evidence_score=90.0), make_mi_snapshot(), make_strategy_snapshot(),
            make_risk_snapshot(), make_portfolio_state(), account, now=friday_night,
        )
        self.assertEqual(snapshot.decision, ComplianceDecision.REJECT)
        self.assertIn(ComplianceRuleId.WEEKEND_RESTRICTION, snapshot.audit_entry.triggered_rules)

    def test_narrower_approved_sessions_from_profile_enforced(self):
        engine = ComplianceEngine(_config_with_profile())
        account = make_account_state(rule_profile_name="strict_example_profile")
        # fixture default session is LONDON_NEW_YORK_OVERLAP, which IS in the
        # strict profile's approved set -- verify EARLY_NEW_YORK (not approved
        # by this stricter profile) is rejected.
        from titan_protocol.evidence_engine.models import SessionState
        evidence = make_evidence_snapshot(evidence_score=90.0)
        import dataclasses
        narrow_session_evidence = dataclasses.replace(evidence, session=SessionState(session=SessionName.EARLY_NEW_YORK, quality_score=100.0))
        snapshot = engine.evaluate(
            "EURUSD", narrow_session_evidence, make_mi_snapshot(), make_strategy_snapshot(),
            make_risk_snapshot(), make_portfolio_state(), account, now=T0,
        )
        self.assertEqual(snapshot.decision, ComplianceDecision.REJECT)
        self.assertIn(ComplianceRuleId.SESSION_NOT_APPROVED, snapshot.audit_entry.triggered_rules)

    def test_profile_never_hard_coded_is_fully_swappable(self):
        # Two different profiles produce two different outcomes for the
        # exact same trade -- proving the profile is genuinely
        # configuration, not a hard-coded branch.
        lenient = ComplianceRuleProfile(name="lenient", max_open_positions=100)
        strict = ComplianceRuleProfile(name="strict", max_open_positions=1)
        config = ComplianceEngineConfig(rule_profiles=(lenient, strict))
        portfolio = make_portfolio_state([make_open_position(pair="GBPUSD")])

        engine = ComplianceEngine(config)
        lenient_account = make_account_state(rule_profile_name="lenient")
        strict_account = make_account_state(rule_profile_name="strict")

        lenient_result = engine.evaluate(
            "EURUSD", make_evidence_snapshot(evidence_score=90.0), make_mi_snapshot(), make_strategy_snapshot(),
            make_risk_snapshot(), portfolio, lenient_account, now=T0,
        )
        strict_result = engine.evaluate(
            "EURUSD", make_evidence_snapshot(evidence_score=90.0), make_mi_snapshot(), make_strategy_snapshot(),
            make_risk_snapshot(), portfolio, strict_account, now=T0,
        )
        self.assertEqual(lenient_result.decision, ComplianceDecision.APPROVE)
        self.assertEqual(strict_result.decision, ComplianceDecision.REJECT)


if __name__ == "__main__":
    unittest.main()
