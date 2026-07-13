"""Phase 3B daily protection validation: exercises the frozen
Compliance Engine's three graduated safety curves (ADR-028 SS5.1-5.3) --
Daily Loss, Total Drawdown, Daily Profit Protection -- against the
default `ComplianceRuleProfile` (max_daily_loss_pct=5.0,
max_total_drawdown_pct=10.0), both in isolation (the band-evaluation
functions themselves) and end to end through a real `ComplianceEngine`,
plus recovery and daily-reset semantics.

Leverages `titan_protocol.compliance_engine`'s own already-frozen unit tests
(`test_daily_loss.py`, `test_drawdown.py`, `test_profit_protection.py`)
as the source of truth for band boundaries -- this file adds the
cross-cutting, end-to-end, and reset/recovery angles Phase 3B asks for,
not a second copy of those unit tests.
"""

from __future__ import annotations

import unittest

from titan_protocol.compliance_engine.config import DEFAULT_RULE_PROFILE, ComplianceEngineConfig
from titan_protocol.compliance_engine.daily_loss import daily_loss_pct_consumed, evaluate_daily_loss_protection
from titan_protocol.compliance_engine.drawdown import evaluate_drawdown_protection, total_drawdown_pct_consumed
from titan_protocol.compliance_engine.engine import ComplianceEngine
from titan_protocol.compliance_engine.models import ComplianceDecision
from titan_protocol.compliance_engine.profit_protection import daily_profit_pct, evaluate_profit_protection
from titan_protocol.risk_engine.models import PortfolioState
from tests.titan_protocol.compliance_engine._fixtures import (
    T0,
    make_account_state,
    make_config,
    make_evidence_snapshot,
    make_mi_snapshot,
    make_risk_snapshot,
    make_strategy_snapshot,
)

_PROFILE = DEFAULT_RULE_PROFILE  # max_daily_loss_pct=5.0, max_total_drawdown_pct=10.0


def _balance_for_daily_loss_pct_consumed(pct_consumed: float, start: float = 100_000.0) -> float:
    loss_pct_of_equity = (pct_consumed / 100.0) * _PROFILE.max_daily_loss_pct
    return start * (1.0 - loss_pct_of_equity / 100.0)


def _balance_for_drawdown_pct_consumed(pct_consumed: float, peak: float = 100_000.0) -> float:
    drawdown_pct_of_equity = (pct_consumed / 100.0) * _PROFILE.max_total_drawdown_pct
    return peak * (1.0 - drawdown_pct_of_equity / 100.0)


class TestDailyLossCurve(unittest.TestCase):
    def test_normal_band_below_50pct_consumed_applies_no_reduction(self):
        account = make_account_state(account_balance=_balance_for_daily_loss_pct_consumed(20.0))
        evaluation = evaluate_daily_loss_protection(account, _PROFILE, ComplianceEngineConfig())
        self.assertEqual(evaluation.multiplier, 1.0)
        self.assertFalse(evaluation.hard_reject)

    def test_reduce_band_at_60pct_consumed_cuts_size(self):
        account = make_account_state(account_balance=_balance_for_daily_loss_pct_consumed(60.0))
        evaluation = evaluate_daily_loss_protection(account, _PROFILE, ComplianceEngineConfig())
        self.assertEqual(evaluation.multiplier, 0.6)
        self.assertFalse(evaluation.hard_reject)

    def test_elevated_band_at_75pct_consumed_requires_exceptional_evidence(self):
        account = make_account_state(account_balance=_balance_for_daily_loss_pct_consumed(75.0))
        config = ComplianceEngineConfig()
        rejected = evaluate_daily_loss_protection(account, _PROFILE, config, evidence_score=80.0, strategy_score=95.0)
        self.assertTrue(rejected.hard_reject)
        self.assertEqual(rejected.gate_kind, "evidence")

        allowed = evaluate_daily_loss_protection(account, _PROFILE, config, evidence_score=90.0, strategy_score=95.0)
        self.assertFalse(allowed.hard_reject)
        self.assertEqual(allowed.multiplier, 0.3)

    def test_no_new_trades_band_at_95pct_consumed_always_hard_rejects(self):
        account = make_account_state(account_balance=_balance_for_daily_loss_pct_consumed(95.0))
        evaluation = evaluate_daily_loss_protection(account, _PROFILE, ComplianceEngineConfig(), evidence_score=100.0, strategy_score=100.0)
        self.assertTrue(evaluation.hard_reject)
        self.assertEqual(evaluation.label, "no_new_trades")


class TestTotalDrawdownCurve(unittest.TestCase):
    def test_normal_band_below_50pct_consumed(self):
        account = make_account_state(peak_balance=100_000.0, account_balance=_balance_for_drawdown_pct_consumed(20.0))
        evaluation = evaluate_drawdown_protection(account, _PROFILE, ComplianceEngineConfig())
        self.assertEqual(evaluation.multiplier, 1.0)

    def test_significant_reduction_band_at_80pct_consumed(self):
        account = make_account_state(peak_balance=100_000.0, account_balance=_balance_for_drawdown_pct_consumed(80.0))
        evaluation = evaluate_drawdown_protection(account, _PROFILE, ComplianceEngineConfig())
        self.assertEqual(evaluation.multiplier, 0.25)
        self.assertFalse(evaluation.hard_reject)

    def test_hard_limit_band_at_95pct_consumed_always_hard_rejects(self):
        account = make_account_state(peak_balance=100_000.0, account_balance=_balance_for_drawdown_pct_consumed(95.0))
        evaluation = evaluate_drawdown_protection(account, _PROFILE, ComplianceEngineConfig())
        self.assertTrue(evaluation.hard_reject)
        self.assertEqual(evaluation.label, "hard_limit")


class TestDailyProfitCurve(unittest.TestCase):
    def test_below_2pct_profit_applies_no_reduction(self):
        account = make_account_state(daily_starting_balance=100_000.0, account_balance=101_000.0)
        evaluation = evaluate_profit_protection(account, ComplianceEngineConfig())
        self.assertEqual(evaluation.multiplier, 1.0)

    def test_between_3_and_4pct_profit_moderately_reduces(self):
        account = make_account_state(daily_starting_balance=100_000.0, account_balance=103_500.0)
        evaluation = evaluate_profit_protection(account, ComplianceEngineConfig())
        self.assertEqual(evaluation.multiplier, 0.5)

    def test_above_configured_stop_pct_hard_rejects_new_positions(self):
        account = make_account_state(daily_starting_balance=100_000.0, account_balance=106_000.0)
        config = ComplianceEngineConfig(profit_protection_stop_at_pct=5.0)
        evaluation = evaluate_profit_protection(account, config)
        self.assertTrue(evaluation.hard_reject)

    def test_profit_protection_can_be_disabled(self):
        account = make_account_state(daily_starting_balance=100_000.0, account_balance=110_000.0)
        config = ComplianceEngineConfig(profit_protection_enabled=False)
        self.assertIsNone(evaluate_profit_protection(account, config))


class TestGraduatedProtectionRecovery(unittest.TestCase):
    def test_account_recovering_toward_starting_balance_returns_to_the_normal_band(self):
        degraded = make_account_state(account_balance=_balance_for_daily_loss_pct_consumed(60.0))
        recovered = make_account_state(account_balance=99_800.0)  # most of the day's loss recovered
        config = ComplianceEngineConfig()
        degraded_eval = evaluate_daily_loss_protection(degraded, _PROFILE, config)
        recovered_eval = evaluate_daily_loss_protection(recovered, _PROFILE, config)
        self.assertEqual(degraded_eval.label, "reduce_max_position_size")
        self.assertEqual(recovered_eval.label, "normal")
        self.assertEqual(recovered_eval.multiplier, 1.0)

    def test_band_evaluation_has_no_hysteresis_or_hidden_state(self):
        """The graduated bands are a pure function of the current
        `AccountState` -- evaluating the same degraded state twice, or
        interleaved with a recovered state, never leaves a "sticky"
        penalty behind."""
        config = ComplianceEngineConfig()
        degraded = make_account_state(account_balance=_balance_for_daily_loss_pct_consumed(85.0))
        recovered = make_account_state(account_balance=100_000.0)
        first = evaluate_daily_loss_protection(degraded, _PROFILE, config, evidence_score=100.0, strategy_score=100.0)
        after_recovery = evaluate_daily_loss_protection(recovered, _PROFILE, config)
        second_degraded_check = evaluate_daily_loss_protection(degraded, _PROFILE, config, evidence_score=100.0, strategy_score=100.0)
        self.assertEqual(first, second_degraded_check)
        self.assertEqual(after_recovery.label, "normal")


class TestDailyReset(unittest.TestCase):
    def test_a_new_trading_day_resets_daily_loss_consumption_independent_of_drawdown(self):
        """Yesterday's losing balance becomes today's
        `daily_starting_balance` at the daily reset boundary -- daily
        loss consumption goes back to 0% even though `peak_balance`
        (and therefore total drawdown consumption) is untouched by the
        reset, since ADR-028 keeps the two curves independent."""
        yesterday_close = _balance_for_daily_loss_pct_consumed(80.0)  # a bad day
        config = ComplianceEngineConfig()

        end_of_yesterday = make_account_state(
            daily_starting_balance=100_000.0, account_balance=yesterday_close, peak_balance=100_000.0,
        )
        self.assertGreater(daily_loss_pct_consumed(end_of_yesterday, _PROFILE), 0.0)

        start_of_today = make_account_state(
            daily_starting_balance=yesterday_close, account_balance=yesterday_close, peak_balance=100_000.0,
        )
        self.assertEqual(daily_loss_pct_consumed(start_of_today, _PROFILE), 0.0)
        # Drawdown consumption survives the daily reset -- it is measured
        # against `peak_balance`, which the daily boundary never resets.
        self.assertGreater(total_drawdown_pct_consumed(start_of_today, _PROFILE), 0.0)
        self.assertEqual(
            total_drawdown_pct_consumed(start_of_today, _PROFILE),
            total_drawdown_pct_consumed(end_of_yesterday, _PROFILE),
        )

    def test_daily_profit_also_resets_against_the_new_daily_starting_balance(self):
        yesterday_close = 103_000.0  # yesterday ended up
        start_of_today = make_account_state(daily_starting_balance=yesterday_close, account_balance=yesterday_close)
        self.assertEqual(daily_profit_pct(start_of_today), 0.0)


class TestHardStopsPropagateToRealComplianceDecision(unittest.TestCase):
    """Proves the graduated curves aren't just isolated pure functions --
    a hard-reject band genuinely blocks a real end-to-end
    `ComplianceEngine.evaluate()` call, and a normal-band account
    genuinely gets approved."""

    def _evaluate(self, account_state):
        engine = ComplianceEngine(make_config())
        return engine.evaluate(
            "EURUSD", make_evidence_snapshot(), make_mi_snapshot(), make_strategy_snapshot(),
            make_risk_snapshot(), PortfolioState(), account_state, T0,
        )

    def test_daily_loss_hard_reject_band_blocks_the_real_compliance_decision(self):
        account = make_account_state(account_balance=_balance_for_daily_loss_pct_consumed(95.0))
        snapshot = self._evaluate(account)
        self.assertEqual(snapshot.decision, ComplianceDecision.REJECT)
        self.assertFalse(snapshot.ready_for_bridge)
        self.assertEqual(snapshot.approved_size_r, 0.0)

    def test_total_drawdown_hard_reject_band_blocks_the_real_compliance_decision(self):
        account = make_account_state(peak_balance=100_000.0, account_balance=_balance_for_drawdown_pct_consumed(95.0))
        snapshot = self._evaluate(account)
        self.assertEqual(snapshot.decision, ComplianceDecision.REJECT)
        self.assertFalse(snapshot.ready_for_bridge)

    def test_healthy_account_state_is_genuinely_approved(self):
        account = make_account_state()
        snapshot = self._evaluate(account)
        self.assertEqual(snapshot.decision, ComplianceDecision.APPROVE)
        self.assertTrue(snapshot.ready_for_bridge)
        self.assertGreater(snapshot.approved_size_r, 0.0)


if __name__ == "__main__":
    unittest.main()
