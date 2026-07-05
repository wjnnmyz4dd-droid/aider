"""Per-check unit tests (ADR-007 §6, §7)."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from phantom_pipeline.execution_validator import checks as c
from phantom_pipeline.execution_validator.config import ExecutionValidatorConfig
from phantom_pipeline.execution_validator.models import AccountState, BrokerState, CheckStatus
from phantom_pipeline.scanner.models import Direction
from tests.phantom_pipeline.execution_validator._fixtures import (
    PRICE,
    SYMBOL,
    T0,
    make_candidate,
    make_compliance_decision,
    make_market_snapshot,
    make_risk_decision,
    make_score_result,
)


def _chain():
    candidate = make_candidate()
    score_result = make_score_result(candidate)
    risk_decision = make_risk_decision(candidate, score_result)
    compliance_decision = make_compliance_decision(candidate, score_result, risk_decision)
    return candidate, score_result, risk_decision, compliance_decision


class TestComplianceApprovalValid(unittest.TestCase):
    def test_missing_is_unevaluable(self):
        result = c.compliance_approval_valid(None)
        self.assertEqual(result.status, CheckStatus.UNEVALUABLE)

    def test_approve_passes(self):
        _, _, _, compliance_decision = _chain()
        result = c.compliance_approval_valid(compliance_decision)
        self.assertEqual(result.status, CheckStatus.PASSED)

    def test_block_fails(self):
        _, _, _, compliance_decision = _chain()
        blocked = compliance_decision.__class__(
            **{**compliance_decision.__dict__, "verdict": compliance_decision.verdict.__class__.BLOCK}
        )
        result = c.compliance_approval_valid(blocked)
        self.assertEqual(result.status, CheckStatus.FAILED)


class TestRiskDecisionConsistent(unittest.TestCase):
    def test_missing_risk_decision_is_unevaluable(self):
        _, _, _, compliance_decision = _chain()
        result = c.risk_decision_consistent(None, compliance_decision)
        self.assertEqual(result.status, CheckStatus.UNEVALUABLE)

    def test_missing_compliance_decision_is_unevaluable(self):
        _, _, risk_decision, _ = _chain()
        result = c.risk_decision_consistent(risk_decision, None)
        self.assertEqual(result.status, CheckStatus.UNEVALUABLE)

    def test_consistent_passes(self):
        _, _, risk_decision, compliance_decision = _chain()
        result = c.risk_decision_consistent(risk_decision, compliance_decision)
        self.assertEqual(result.status, CheckStatus.PASSED)


class TestCandidateIntegrity(unittest.TestCase):
    def test_missing_risk_decision_is_unevaluable(self):
        candidate, score_result, _, _ = _chain()
        result = c.candidate_integrity(candidate, score_result, None)
        self.assertEqual(result.status, CheckStatus.UNEVALUABLE)

    def test_consistent_passes(self):
        candidate, score_result, risk_decision, _ = _chain()
        result = c.candidate_integrity(candidate, score_result, risk_decision)
        self.assertEqual(result.status, CheckStatus.PASSED)

    def test_mismatched_candidate_fails(self):
        candidate, score_result, risk_decision, _ = _chain()
        other = make_candidate(trace_id="different-trace")
        result = c.candidate_integrity(other, score_result, risk_decision)
        self.assertEqual(result.status, CheckStatus.FAILED)


class TestTradeNotStale(unittest.TestCase):
    def test_missing_risk_decision_is_unevaluable(self):
        result = c.trade_not_stale(None, T0, ExecutionValidatorConfig())
        self.assertEqual(result.status, CheckStatus.UNEVALUABLE)

    def test_naive_now_is_unevaluable(self):
        _, _, risk_decision, _ = _chain()
        result = c.trade_not_stale(risk_decision, datetime(2026, 7, 6, 10, 0, 1), ExecutionValidatorConfig())
        self.assertEqual(result.status, CheckStatus.UNEVALUABLE)

    def test_within_max_age_passes(self):
        _, _, risk_decision, _ = _chain()
        config = ExecutionValidatorConfig(max_order_age_seconds=5.0)
        now = risk_decision.timestamp + timedelta(seconds=1)
        result = c.trade_not_stale(risk_decision, now, config)
        self.assertEqual(result.status, CheckStatus.PASSED)

    def test_beyond_max_age_fails(self):
        _, _, risk_decision, _ = _chain()
        config = ExecutionValidatorConfig(max_order_age_seconds=5.0)
        now = risk_decision.timestamp + timedelta(seconds=10)
        result = c.trade_not_stale(risk_decision, now, config)
        self.assertEqual(result.status, CheckStatus.FAILED)

    def test_future_timestamp_is_unevaluable(self):
        _, _, risk_decision, _ = _chain()
        now = risk_decision.timestamp - timedelta(seconds=10)
        result = c.trade_not_stale(risk_decision, now, ExecutionValidatorConfig())
        self.assertEqual(result.status, CheckStatus.UNEVALUABLE)


class TestMarketOpen(unittest.TestCase):
    def test_missing_snapshot_is_unevaluable(self):
        result = c.market_open(None)
        self.assertEqual(result.status, CheckStatus.UNEVALUABLE)

    def test_open_passes(self):
        result = c.market_open(make_market_snapshot(market_status="OPEN"))
        self.assertEqual(result.status, CheckStatus.PASSED)

    def test_closed_fails(self):
        result = c.market_open(make_market_snapshot(market_status="CLOSED_WEEKEND"))
        self.assertEqual(result.status, CheckStatus.FAILED)


class TestSymbolTradable(unittest.TestCase):
    def test_missing_broker_state_is_unevaluable(self):
        result = c.symbol_tradable(None)
        self.assertEqual(result.status, CheckStatus.UNEVALUABLE)

    def test_tradable_passes(self):
        result = c.symbol_tradable(BrokerState(connected=True, symbol_tradable=True))
        self.assertEqual(result.status, CheckStatus.PASSED)

    def test_not_tradable_fails(self):
        result = c.symbol_tradable(BrokerState(connected=True, symbol_tradable=False))
        self.assertEqual(result.status, CheckStatus.FAILED)


class TestPriceValid(unittest.TestCase):
    def test_missing_price_is_unevaluable(self):
        result = c.price_valid(make_market_snapshot(price=None))
        self.assertEqual(result.status, CheckStatus.UNEVALUABLE)

    def test_positive_price_passes(self):
        result = c.price_valid(make_market_snapshot(price=1.1))
        self.assertEqual(result.status, CheckStatus.PASSED)

    def test_non_positive_price_fails(self):
        result = c.price_valid(make_market_snapshot(price=0.0))
        self.assertEqual(result.status, CheckStatus.FAILED)


class TestSpreadUnchanged(unittest.TestCase):
    def test_missing_spread_is_unevaluable(self):
        result = c.spread_unchanged(make_market_snapshot(spread=None), SYMBOL, ExecutionValidatorConfig())
        self.assertEqual(result.status, CheckStatus.UNEVALUABLE)

    def test_unconfigured_symbol_is_unevaluable(self):
        result = c.spread_unchanged(make_market_snapshot(), SYMBOL, ExecutionValidatorConfig())
        self.assertEqual(result.status, CheckStatus.UNEVALUABLE)

    def test_within_threshold_passes(self):
        config = ExecutionValidatorConfig(max_spread={SYMBOL: 0.0005})
        result = c.spread_unchanged(make_market_snapshot(spread=0.0001), SYMBOL, config)
        self.assertEqual(result.status, CheckStatus.PASSED)
        self.assertIsNone(result.warning)

    def test_near_threshold_passes_with_warning(self):
        config = ExecutionValidatorConfig(max_spread={SYMBOL: 0.0005}, warning_threshold_ratio=0.8)
        result = c.spread_unchanged(make_market_snapshot(spread=0.00045), SYMBOL, config)
        self.assertEqual(result.status, CheckStatus.PASSED)
        self.assertIsNotNone(result.warning)

    def test_above_threshold_fails(self):
        config = ExecutionValidatorConfig(max_spread={SYMBOL: 0.0005})
        result = c.spread_unchanged(make_market_snapshot(spread=0.001), SYMBOL, config)
        self.assertEqual(result.status, CheckStatus.FAILED)


class TestSlippageWithinLimits(unittest.TestCase):
    def test_missing_reference_price_is_unevaluable(self):
        result = c.slippage_within_limits(make_market_snapshot(), None, ExecutionValidatorConfig())
        self.assertEqual(result.status, CheckStatus.UNEVALUABLE)

    def test_no_drift_passes(self):
        config = ExecutionValidatorConfig(max_price_drift=0.001)
        result = c.slippage_within_limits(make_market_snapshot(price=1.1), 1.1, config)
        self.assertEqual(result.status, CheckStatus.PASSED)

    def test_drift_beyond_tolerance_fails(self):
        config = ExecutionValidatorConfig(max_price_drift=0.001)
        result = c.slippage_within_limits(make_market_snapshot(price=1.105), 1.1, config)
        self.assertEqual(result.status, CheckStatus.FAILED)

    def test_drift_near_tolerance_passes_with_warning(self):
        config = ExecutionValidatorConfig(max_price_drift=0.001, warning_threshold_ratio=0.8)
        result = c.slippage_within_limits(make_market_snapshot(price=1.10085), 1.1, config)
        self.assertEqual(result.status, CheckStatus.PASSED)
        self.assertIsNotNone(result.warning)


class TestOrderSynchronized(unittest.TestCase):
    def test_missing_decisions_is_unevaluable(self):
        candidate, _, _, _ = _chain()
        result = c.order_synchronized(candidate, None, None)
        self.assertEqual(result.status, CheckStatus.UNEVALUABLE)

    def test_synchronized_passes(self):
        candidate, _, risk_decision, compliance_decision = _chain()
        result = c.order_synchronized(candidate, risk_decision, compliance_decision)
        self.assertEqual(result.status, CheckStatus.PASSED)

    def test_direction_mismatch_fails(self):
        candidate, _, risk_decision, compliance_decision = _chain()
        mismatched = make_candidate(direction=Direction.DOWN)
        result = c.order_synchronized(mismatched, risk_decision, compliance_decision)
        self.assertEqual(result.status, CheckStatus.FAILED)


class TestAccountSynchronized(unittest.TestCase):
    def test_missing_equity_is_unevaluable(self):
        _, _, risk_decision, _ = _chain()
        result = c.account_synchronized(risk_decision, AccountState(equity=None, available_margin=None), ExecutionValidatorConfig())
        self.assertEqual(result.status, CheckStatus.UNEVALUABLE)

    def test_matching_equity_passes(self):
        _, _, risk_decision, _ = _chain()
        result = c.account_synchronized(
            risk_decision, AccountState(equity=10000.0, available_margin=5000.0), ExecutionValidatorConfig()
        )
        self.assertEqual(result.status, CheckStatus.PASSED)

    def test_drifted_equity_fails(self):
        _, _, risk_decision, _ = _chain()
        result = c.account_synchronized(
            risk_decision, AccountState(equity=1000.0, available_margin=500.0), ExecutionValidatorConfig()
        )
        self.assertEqual(result.status, CheckStatus.FAILED)


class TestSufficientMargin(unittest.TestCase):
    def test_missing_margin_is_unevaluable(self):
        _, _, risk_decision, _ = _chain()
        result = c.sufficient_margin(risk_decision, AccountState(equity=10000.0, available_margin=None))
        self.assertEqual(result.status, CheckStatus.UNEVALUABLE)

    def test_sufficient_margin_passes(self):
        _, _, risk_decision, _ = _chain()
        result = c.sufficient_margin(risk_decision, AccountState(equity=10000.0, available_margin=5000.0))
        self.assertEqual(result.status, CheckStatus.PASSED)

    def test_insufficient_margin_fails(self):
        _, _, risk_decision, _ = _chain()
        result = c.sufficient_margin(risk_decision, AccountState(equity=10000.0, available_margin=1.0))
        self.assertEqual(result.status, CheckStatus.FAILED)


class TestBrokerConnectionHealthy(unittest.TestCase):
    def test_missing_broker_state_is_unevaluable(self):
        result = c.broker_connection_healthy(None)
        self.assertEqual(result.status, CheckStatus.UNEVALUABLE)

    def test_connected_passes(self):
        result = c.broker_connection_healthy(BrokerState(connected=True, symbol_tradable=True))
        self.assertEqual(result.status, CheckStatus.PASSED)

    def test_disconnected_fails(self):
        result = c.broker_connection_healthy(BrokerState(connected=False, symbol_tradable=True))
        self.assertEqual(result.status, CheckStatus.FAILED)


class TestNoDuplicateRequest(unittest.TestCase):
    def test_first_attempt_passes(self):
        candidate, _, _, _ = _chain()
        result = c.no_duplicate_request(candidate, already_seen=False)
        self.assertEqual(result.status, CheckStatus.PASSED)

    def test_repeated_attempt_fails(self):
        candidate, _, _, _ = _chain()
        result = c.no_duplicate_request(candidate, already_seen=True)
        self.assertEqual(result.status, CheckStatus.FAILED)


class TestStopLossValid(unittest.TestCase):
    def test_missing_stop_loss_is_unevaluable(self):
        result = c.stop_loss_valid(Direction.UP, make_market_snapshot(), None)
        self.assertEqual(result.status, CheckStatus.UNEVALUABLE)

    def test_correct_side_for_up_passes(self):
        result = c.stop_loss_valid(Direction.UP, make_market_snapshot(price=1.1), 1.095)
        self.assertEqual(result.status, CheckStatus.PASSED)

    def test_wrong_side_for_up_fails(self):
        result = c.stop_loss_valid(Direction.UP, make_market_snapshot(price=1.1), 1.105)
        self.assertEqual(result.status, CheckStatus.FAILED)

    def test_correct_side_for_down_passes(self):
        result = c.stop_loss_valid(Direction.DOWN, make_market_snapshot(price=1.1), 1.105)
        self.assertEqual(result.status, CheckStatus.PASSED)

    def test_neutral_direction_is_unevaluable(self):
        result = c.stop_loss_valid(Direction.NEUTRAL, make_market_snapshot(price=1.1), 1.095)
        self.assertEqual(result.status, CheckStatus.UNEVALUABLE)


class TestTakeProfitValid(unittest.TestCase):
    def test_missing_take_profit_is_unevaluable(self):
        result = c.take_profit_valid(Direction.UP, make_market_snapshot(), None)
        self.assertEqual(result.status, CheckStatus.UNEVALUABLE)

    def test_correct_side_for_up_passes(self):
        result = c.take_profit_valid(Direction.UP, make_market_snapshot(price=1.1), 1.11)
        self.assertEqual(result.status, CheckStatus.PASSED)

    def test_wrong_side_for_up_fails(self):
        result = c.take_profit_valid(Direction.UP, make_market_snapshot(price=1.1), 1.09)
        self.assertEqual(result.status, CheckStatus.FAILED)


class TestMinimumRR(unittest.TestCase):
    def test_missing_levels_is_unevaluable(self):
        result = c.minimum_rr(Direction.UP, make_market_snapshot(price=1.1), None, None, ExecutionValidatorConfig())
        self.assertEqual(result.status, CheckStatus.UNEVALUABLE)

    def test_zero_risk_is_unevaluable(self):
        result = c.minimum_rr(Direction.UP, make_market_snapshot(price=1.1), 1.1, 1.11, ExecutionValidatorConfig())
        self.assertEqual(result.status, CheckStatus.UNEVALUABLE)

    def test_rr_above_minimum_passes(self):
        config = ExecutionValidatorConfig(min_risk_reward_ratio=1.5)
        result = c.minimum_rr(Direction.UP, make_market_snapshot(price=1.1), 1.095, 1.11, config)
        self.assertEqual(result.status, CheckStatus.PASSED)

    def test_rr_below_minimum_fails(self):
        config = ExecutionValidatorConfig(min_risk_reward_ratio=1.5)
        result = c.minimum_rr(Direction.UP, make_market_snapshot(price=1.1), 1.095, 1.1025, config)
        self.assertEqual(result.status, CheckStatus.FAILED)


class TestPositionSizingValid(unittest.TestCase):
    def test_missing_risk_decision_is_unevaluable(self):
        result = c.position_sizing_valid(None)
        self.assertEqual(result.status, CheckStatus.UNEVALUABLE)

    def test_nominal_sizing_passes(self):
        _, _, risk_decision, _ = _chain()
        result = c.position_sizing_valid(risk_decision)
        self.assertEqual(result.status, CheckStatus.PASSED)

    def test_zero_risk_amount_fails(self):
        _, _, risk_decision, _ = _chain()
        zeroed = risk_decision.__class__(**{**risk_decision.__dict__, "approved_risk_amount": 0.0})
        result = c.position_sizing_valid(zeroed)
        self.assertEqual(result.status, CheckStatus.FAILED)


class TestExistingPositionValidation(unittest.TestCase):
    def test_missing_account_state_is_unevaluable(self):
        result = c.existing_position_validation(None)
        self.assertEqual(result.status, CheckStatus.UNEVALUABLE)

    def test_present_account_state_passes(self):
        result = c.existing_position_validation(AccountState(equity=1.0, available_margin=1.0))
        self.assertEqual(result.status, CheckStatus.PASSED)


if __name__ == "__main__":
    unittest.main()
