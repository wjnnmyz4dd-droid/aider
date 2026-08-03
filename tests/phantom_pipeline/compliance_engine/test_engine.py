"""ComplianceEngine.evaluate()/evaluate_batch() tests (ADR-006 §2-§18)."""

from __future__ import annotations

import unittest
from datetime import timedelta

from phantom_pipeline.compliance_engine.config import ComplianceEngineConfig
from phantom_pipeline.compliance_engine.engine import ComplianceEngine
from phantom_pipeline.compliance_engine.models import (
    CheckStatus,
    NewsBlackoutWindow,
    NewsCalendarState,
    OpenPosition,
    Verdict,
)
from phantom_pipeline.compliance_engine.state_store import InMemoryComplianceStateStore
from phantom_pipeline.scanner.models import Direction
from tests.phantom_pipeline.compliance_engine._fixtures import (
    SYMBOL,
    T0,
    make_account_state,
    make_candidate,
    make_market_snapshot,
    make_risk_decision,
    make_score_result,
)

NOMINAL_CONFIG = ComplianceEngineConfig(
    spread_thresholds={SYMBOL: 0.0005}, slippage_thresholds={SYMBOL: 0.0005}
)


def _nominal_engine():
    return ComplianceEngine(InMemoryComplianceStateStore(), NOMINAL_CONFIG)


def _nominal_inputs():
    candidate = make_candidate()
    score_result = make_score_result(candidate)
    risk_decision = make_risk_decision(candidate, score_result)
    account = make_account_state()
    snapshot = make_market_snapshot()
    news = NewsCalendarState(feed_stale=False, blackout_windows=())
    return risk_decision, candidate, score_result, account, snapshot, news


class TestNominalApproval(unittest.TestCase):
    def test_all_checks_pass_yields_approve(self):
        engine = _nominal_engine()
        result = engine.evaluate(*_nominal_inputs(), expected_slippage=0.0001)
        self.assertEqual(result.verdict, Verdict.APPROVE)
        self.assertEqual(result.blocking_rules, ())
        self.assertEqual(len(result.check_evaluations), 9)


class TestOneDecisionPerRiskDecision(unittest.TestCase):
    def test_evaluate_always_returns_exactly_one_decision(self):
        engine = _nominal_engine()
        result = engine.evaluate(*_nominal_inputs(), expected_slippage=0.0001)
        self.assertIsNotNone(result)

    def test_evaluate_batch_never_discards(self):
        engine = _nominal_engine()
        requests = [(*_nominal_inputs(), 0.0001) for _ in range(5)]
        results = engine.evaluate_batch(requests)
        self.assertEqual(len(results), 5)


class TestDeterminism(unittest.TestCase):
    def test_same_inputs_same_decision(self):
        engine = _nominal_engine()
        inputs = _nominal_inputs()
        first = engine.evaluate(*inputs, expected_slippage=0.0001)
        second = ComplianceEngine(InMemoryComplianceStateStore(), NOMINAL_CONFIG).evaluate(
            *inputs, expected_slippage=0.0001
        )
        self.assertEqual(first, second)

    def test_replay_determinism_across_fresh_engines(self):
        results = []
        for _ in range(3):
            engine = ComplianceEngine(InMemoryComplianceStateStore(), NOMINAL_CONFIG)
            results.append(engine.evaluate(*_nominal_inputs(), expected_slippage=0.0001))
        self.assertTrue(all(r == results[0] for r in results))


class TestTraceIdAndCandidateIdPropagation(unittest.TestCase):
    def test_trace_id_and_candidate_id_match_risk_decision(self):
        engine = _nominal_engine()
        risk_decision, candidate, score_result, account, snapshot, news = _nominal_inputs()
        result = engine.evaluate(risk_decision, candidate, score_result, account, snapshot, news)
        self.assertEqual(result.trace_id, risk_decision.trace_id)
        self.assertEqual(result.candidate_id, risk_decision.candidate_id)


class TestDailyDrawdownBlock(unittest.TestCase):
    def test_breach_blocks_and_latches_daily_lockout(self):
        engine = _nominal_engine()
        risk_decision, candidate, score_result, _, snapshot, news = _nominal_inputs()
        breached_account = make_account_state(daily_drawdown_pct=5.0)

        result = engine.evaluate(risk_decision, candidate, score_result, breached_account, snapshot, news)

        self.assertEqual(result.verdict, Verdict.BLOCK)
        self.assertIn("DAILY_DRAWDOWN", result.blocking_rules)

    def test_lockout_persists_across_subsequent_calls_same_day_even_if_drawdown_recovers(self):
        engine = _nominal_engine()
        risk_decision, candidate, score_result, _, snapshot, news = _nominal_inputs()
        breached_account = make_account_state(daily_drawdown_pct=5.0)
        engine.evaluate(risk_decision, candidate, score_result, breached_account, snapshot, news)

        recovered_account = make_account_state(daily_drawdown_pct=0.1)
        result = engine.evaluate(risk_decision, candidate, score_result, recovered_account, snapshot, news)
        self.assertEqual(result.verdict, Verdict.BLOCK)
        self.assertIn("DAILY_DRAWDOWN", result.blocking_rules)


class TestTotalDrawdownAndKillSwitchBlock(unittest.TestCase):
    def test_breach_blocks_via_total_drawdown_check(self):
        engine = _nominal_engine()
        risk_decision, candidate, score_result, _, snapshot, news = _nominal_inputs()
        breached_account = make_account_state(total_drawdown_pct=9.0)

        result = engine.evaluate(risk_decision, candidate, score_result, breached_account, snapshot, news)

        self.assertEqual(result.verdict, Verdict.BLOCK)
        self.assertIn("TOTAL_DRAWDOWN", result.blocking_rules)

    def test_breach_latches_permanent_kill_switch_for_subsequent_calls(self):
        engine = _nominal_engine()
        risk_decision, candidate, score_result, _, snapshot, news = _nominal_inputs()
        breached_account = make_account_state(total_drawdown_pct=9.0)
        engine.evaluate(risk_decision, candidate, score_result, breached_account, snapshot, news)

        recovered_account = make_account_state(total_drawdown_pct=0.1)
        result = engine.evaluate(risk_decision, candidate, score_result, recovered_account, snapshot, news)
        self.assertEqual(result.verdict, Verdict.BLOCK)
        self.assertIn("KILL_SWITCH", result.blocking_rules)


class TestNewsBlock(unittest.TestCase):
    def test_active_blackout_blocks(self):
        engine = _nominal_engine()
        risk_decision, candidate, score_result, account, snapshot, _ = _nominal_inputs()
        window = NewsBlackoutWindow(
            "USD", risk_decision.timestamp - timedelta(minutes=10), risk_decision.timestamp + timedelta(minutes=10)
        )
        news = NewsCalendarState(feed_stale=False, blackout_windows=(window,))

        result = engine.evaluate(risk_decision, candidate, score_result, account, snapshot, news)

        self.assertEqual(result.verdict, Verdict.BLOCK)
        self.assertIn("NEWS_RESTRICTION", result.blocking_rules)


class TestSessionBlock(unittest.TestCase):
    def test_outside_configured_windows_blocks(self):
        from phantom_pipeline.compliance_engine.config import SessionWindow

        config = ComplianceEngineConfig(
            spread_thresholds={SYMBOL: 0.0005},
            slippage_thresholds={SYMBOL: 0.0005},
            session_windows=(SessionWindow("ONLY", 1, 0, 2, 0),),
        )
        engine = ComplianceEngine(InMemoryComplianceStateStore(), config)
        risk_decision, candidate, score_result, account, snapshot, news = _nominal_inputs()

        result = engine.evaluate(risk_decision, candidate, score_result, account, snapshot, news)

        self.assertEqual(result.verdict, Verdict.BLOCK)
        self.assertIn("SESSION_RESTRICTION", result.blocking_rules)


class TestWeekendBlock(unittest.TestCase):
    def test_market_closed_blocks(self):
        engine = _nominal_engine()
        risk_decision, candidate, score_result, account, _, news = _nominal_inputs()
        closed_snapshot = make_market_snapshot(market_status="CLOSED_WEEKEND")

        result = engine.evaluate(risk_decision, candidate, score_result, account, closed_snapshot, news)

        self.assertEqual(result.verdict, Verdict.BLOCK)
        self.assertIn("WEEKEND_RESTRICTION", result.blocking_rules)


class TestSpreadBlock(unittest.TestCase):
    def test_wide_spread_blocks(self):
        engine = _nominal_engine()
        risk_decision, candidate, score_result, account, _, news = _nominal_inputs()
        wide_spread_snapshot = make_market_snapshot(spread=0.01)

        result = engine.evaluate(risk_decision, candidate, score_result, account, wide_spread_snapshot, news)

        self.assertEqual(result.verdict, Verdict.BLOCK)
        self.assertIn("SPREAD_VALIDATION", result.blocking_rules)


class TestSlippageBlock(unittest.TestCase):
    def test_high_expected_slippage_blocks(self):
        engine = _nominal_engine()
        result = engine.evaluate(*_nominal_inputs(), expected_slippage=0.01)

        self.assertEqual(result.verdict, Verdict.BLOCK)
        self.assertIn("SLIPPAGE_VALIDATION", result.blocking_rules)


class TestMaxPositionsBlock(unittest.TestCase):
    def test_at_limit_blocks(self):
        config = ComplianceEngineConfig(
            spread_thresholds={SYMBOL: 0.0005},
            slippage_thresholds={SYMBOL: 0.0005},
            max_positions_per_symbol=1,
        )
        engine = ComplianceEngine(InMemoryComplianceStateStore(), config)
        risk_decision, candidate, score_result, _, snapshot, news = _nominal_inputs()
        stacked_account = make_account_state(open_positions=(OpenPosition(SYMBOL, Direction.UP),))

        result = engine.evaluate(
            risk_decision, candidate, score_result, stacked_account, snapshot, news, expected_slippage=0.0001
        )

        self.assertEqual(result.verdict, Verdict.BLOCK)
        self.assertIn("MAX_POSITIONS", result.blocking_rules)


class TestKillSwitchBlockDirect(unittest.TestCase):
    def test_pre_triggered_store_blocks_immediately(self):
        store = InMemoryComplianceStateStore()
        store.trigger_kill_switch("manual_test_trigger", "prior-trace", T0)
        engine = ComplianceEngine(store, NOMINAL_CONFIG)

        result = engine.evaluate(*_nominal_inputs(), expected_slippage=0.0001)

        self.assertEqual(result.verdict, Verdict.BLOCK)
        self.assertIn("KILL_SWITCH", result.blocking_rules)


class TestMissingAccountState(unittest.TestCase):
    def test_missing_account_state_blocks(self):
        engine = _nominal_engine()
        risk_decision, candidate, score_result, _, snapshot, news = _nominal_inputs()

        result = engine.evaluate(risk_decision, candidate, score_result, None, snapshot, news)

        self.assertEqual(result.verdict, Verdict.BLOCK)
        blocked_checks = {e.check for e in result.check_evaluations if e.blocks}
        self.assertIn("DAILY_DRAWDOWN", blocked_checks)
        self.assertIn("TOTAL_DRAWDOWN", blocked_checks)
        self.assertIn("MAX_POSITIONS", blocked_checks)


class TestMissingBrokerMarketState(unittest.TestCase):
    def test_missing_market_snapshot_blocks(self):
        engine = _nominal_engine()
        risk_decision, candidate, score_result, account, _, news = _nominal_inputs()

        result = engine.evaluate(risk_decision, candidate, score_result, account, None, news)

        self.assertEqual(result.verdict, Verdict.BLOCK)
        blocked_checks = {e.check for e in result.check_evaluations if e.blocks}
        self.assertIn("WEEKEND_RESTRICTION", blocked_checks)
        self.assertIn("SPREAD_VALIDATION", blocked_checks)


class TestFailClosedBehavior(unittest.TestCase):
    def test_every_unevaluable_check_blocks_the_overall_decision(self):
        engine = ComplianceEngine(InMemoryComplianceStateStore(), ComplianceEngineConfig())
        risk_decision, candidate, score_result, account, snapshot, news = _nominal_inputs()

        result = engine.evaluate(risk_decision, candidate, score_result, account, snapshot, news)

        self.assertEqual(result.verdict, Verdict.BLOCK)
        statuses = {e.status for e in result.check_evaluations}
        self.assertIn(CheckStatus.UNEVALUABLE, statuses)


class TestNoRiskModification(unittest.TestCase):
    def test_risk_decision_is_untouched(self):
        engine = _nominal_engine()
        risk_decision, candidate, score_result, account, snapshot, news = _nominal_inputs()
        before = risk_decision
        engine.evaluate(risk_decision, candidate, score_result, account, snapshot, news, expected_slippage=0.0001)
        self.assertEqual(risk_decision, before)
        self.assertIs(risk_decision, before)


class TestMalformedRequest(unittest.TestCase):
    def test_mismatched_candidate_blocks_with_zero_checks(self):
        engine = _nominal_engine()
        risk_decision, candidate, score_result, account, snapshot, news = _nominal_inputs()
        other_candidate = make_candidate(trace_id="different-trace")

        result = engine.evaluate(risk_decision, other_candidate, score_result, account, snapshot, news)

        self.assertEqual(result.verdict, Verdict.BLOCK)
        self.assertEqual(result.blocking_rules, ("candidate_mismatch",))
        self.assertEqual(result.check_evaluations, ())


if __name__ == "__main__":
    unittest.main()
