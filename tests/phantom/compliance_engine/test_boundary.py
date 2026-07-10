"""Boundary tests: edge conditions at every configured limit (ADR-028)."""

from __future__ import annotations

import unittest

from phantom.compliance_engine.config import ComplianceEngineConfig
from phantom.compliance_engine.engine import ComplianceEngine
from phantom.compliance_engine.models import ComplianceDecision
from tests.phantom.compliance_engine._fixtures import (
    T0,
    make_account_state,
    make_config,
    make_evidence_snapshot,
    make_mi_snapshot,
    make_portfolio_state,
    make_risk_snapshot,
    make_strategy_snapshot,
)


class TestConfigBoundary(unittest.TestCase):
    def test_unknown_profile_name_raises(self):
        config = ComplianceEngineConfig()
        with self.assertRaises(ValueError):
            config.profile_for("nonexistent_profile")

    def test_default_bands_have_no_gaps(self):
        config = make_config()
        for bands in (config.daily_loss_bands, config.drawdown_bands):
            sorted_bands = sorted(bands, key=lambda b: b.min_pct)
            for i in range(len(sorted_bands) - 1):
                self.assertAlmostEqual(sorted_bands[i].max_pct, sorted_bands[i + 1].min_pct, places=6)


class TestZeroBalanceEdgeCases(unittest.TestCase):
    def test_zero_daily_starting_balance_does_not_crash(self):
        engine = ComplianceEngine(make_config())
        account = make_account_state(account_balance=0.0, daily_starting_balance=0.0, peak_balance=0.0)
        snapshot = engine.evaluate(
            "EURUSD", make_evidence_snapshot(evidence_score=90.0), make_mi_snapshot(), make_strategy_snapshot(),
            make_risk_snapshot(), make_portfolio_state(), account, now=T0,
        )
        self.assertIn(snapshot.decision, (ComplianceDecision.APPROVE, ComplianceDecision.REDUCE))


class TestExactBandBoundary(unittest.TestCase):
    def test_exactly_at_reject_band_floor_rejects(self):
        engine = ComplianceEngine(make_config())
        # 4.5% loss / 5% limit = exactly 90.0 -- the reject band's floor (inclusive)
        account = make_account_state(account_balance=95_500.0, daily_starting_balance=100_000.0)
        snapshot = engine.evaluate(
            "EURUSD", make_evidence_snapshot(evidence_score=100.0), make_mi_snapshot(), make_strategy_snapshot(score=100.0),
            make_risk_snapshot(), make_portfolio_state(), account, now=T0,
        )
        self.assertEqual(snapshot.decision, ComplianceDecision.REJECT)

    def test_just_below_reject_band_floor_still_reduces(self):
        engine = ComplianceEngine(make_config())
        # 4.49% loss / 5% limit = 89.8 -- just inside the 80-90% band
        account = make_account_state(account_balance=95_510.0, daily_starting_balance=100_000.0)
        snapshot = engine.evaluate(
            "EURUSD", make_evidence_snapshot(evidence_score=100.0), make_mi_snapshot(), make_strategy_snapshot(score=100.0),
            make_risk_snapshot(), make_portfolio_state(), account, now=T0,
        )
        self.assertNotEqual(snapshot.decision, ComplianceDecision.REJECT)


if __name__ == "__main__":
    unittest.main()
