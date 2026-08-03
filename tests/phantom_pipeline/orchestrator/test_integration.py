"""End-to-end Pipeline Orchestrator integration tests (Phase 2 system
integration task). Covers: successful trade path, blocked trade path,
rejected execution, MT5 acknowledgement, position management lifecycle,
analytics recording, watchdog observation, dashboard visibility, replay
determinism, pipeline restart, duplicate prevention, failure recovery,
and trace continuity across the entire pipeline.
"""

from __future__ import annotations

import unittest
from datetime import timedelta

from phantom_pipeline.compliance_engine.models import Verdict as ComplianceVerdict
from phantom_pipeline.execution_validator.models import Verdict as ExecutionVerdict
from phantom_pipeline.mt5_bridge.models import BrokerAcknowledgement, ConnectionState
from phantom_pipeline.position_manager.models import LifecycleState, ManagementAction, PositionAdjustmentRequest
from phantom_pipeline.watchdog.models import HealthState

from tests.phantom_pipeline.orchestrator._fixtures import (
    PRIMARY_TIMEFRAME,
    STOP_DISTANCE,
    SYMBOL,
    TIMEFRAME,
    build_orchestrator,
    feed_healthy_bars,
    make_broker_state,
    make_compliance_account_state,
    make_execution_account_state,
    make_news_state,
    make_risk_account_state,
    run_ready_cycle,
)


class TestSuccessfulTradePath(unittest.TestCase):
    def test_full_chain_reaches_broker_acknowledgement(self):
        orchestrator = build_orchestrator()
        result, now = run_ready_cycle(orchestrator)

        self.assertEqual(result.observation.symbol, SYMBOL)
        self.assertEqual(len(result.candidate_results), 1)
        candidate_result = result.candidate_results[0]

        self.assertEqual(candidate_result.compliance_decision.verdict, ComplianceVerdict.APPROVE)
        self.assertEqual(candidate_result.execution_decision.verdict, ExecutionVerdict.APPROVE)
        self.assertIsNone(candidate_result.submit_reject_reason)
        self.assertIsInstance(candidate_result.broker_response, BrokerAcknowledgement)


class TestBlockedTradePath(unittest.TestCase):
    def test_compliance_block_still_runs_every_downstream_stage(self):
        """A BLOCK never causes the orchestrator to skip Execution
        Validator or MT5 Bridge — each stage's own fail-closed check is
        what actually stops the trade (never bypassed, never
        duplicated)."""
        orchestrator = build_orchestrator()
        result, now = run_ready_cycle(orchestrator, compliance_approve=False)

        candidate_result = result.candidate_results[0]
        self.assertEqual(candidate_result.compliance_decision.verdict, ComplianceVerdict.BLOCK)
        # Execution Validator was still called and itself rejects.
        self.assertIsNotNone(candidate_result.execution_decision)
        self.assertEqual(candidate_result.execution_decision.verdict, ExecutionVerdict.REJECT)
        # MT5 Bridge was still called and itself refuses to submit.
        self.assertEqual(candidate_result.submit_reject_reason, "execution_decision_not_approved")
        self.assertIsNone(candidate_result.broker_response)


class TestRejectedExecution(unittest.TestCase):
    def test_execution_validator_rejects_independently_of_compliance_approval(self):
        """Compliance APPROVEs, but Execution Validator's own
        broker-connection-health check rejects independently — proving
        Execution Validator is a real, independent gate, not a rubber
        stamp on Compliance's verdict."""
        orchestrator = build_orchestrator()
        feed_healthy_bars(orchestrator.data_pipeline)
        # Deliberately do not connect/synchronize MT5 Bridge, and report
        # broker disconnected to Execution Validator.
        now = orchestrator.data_pipeline.get_snapshot(SYMBOL).timestamp
        entry_price = orchestrator.data_pipeline.get_snapshot(SYMBOL).price

        result = orchestrator.run_scan_cycle(
            symbol=SYMBOL,
            timeframes=(TIMEFRAME,),
            primary_timeframe=PRIMARY_TIMEFRAME,
            session_time=now,
            now=now,
            risk_account_state=make_risk_account_state(),
            compliance_account_state=make_compliance_account_state(approve=True),
            execution_account_state=make_execution_account_state(),
            broker_state=make_broker_state(connected=False, tradable=True),
            news_state=make_news_state(),
            stop_distance=STOP_DISTANCE,
            expected_slippage=0.0001,
            reference_price=entry_price,
            intended_stop_loss=entry_price - STOP_DISTANCE,
            intended_take_profit=entry_price + STOP_DISTANCE * 3,
        )
        candidate_result = result.candidate_results[0]
        self.assertEqual(candidate_result.compliance_decision.verdict, ComplianceVerdict.APPROVE)
        self.assertEqual(candidate_result.execution_decision.verdict, ExecutionVerdict.REJECT)
        self.assertIn("BROKER_CONNECTION_HEALTHY", candidate_result.execution_decision.blocking_reasons)
        self.assertEqual(candidate_result.submit_reject_reason, "execution_decision_not_approved")


class TestMT5Acknowledgement(unittest.TestCase):
    def test_broker_acknowledgement_carries_matching_execution_id(self):
        orchestrator = build_orchestrator()
        result, now = run_ready_cycle(orchestrator)
        candidate_result = result.candidate_results[0]

        self.assertIsNotNone(candidate_result.broker_request)
        self.assertEqual(candidate_result.broker_response.execution_id, candidate_result.broker_request.execution_id)
        self.assertEqual(candidate_result.broker_response.trace_id, candidate_result.candidate.trace_id)


class TestPositionManagementLifecycle(unittest.TestCase):
    def test_break_even_adjustment_routes_through_mt5_bridge(self):
        orchestrator = build_orchestrator()
        from phantom_pipeline.scanner.models import Direction
        from tests.phantom_pipeline.orchestrator._fixtures import T0

        orchestrator.mt5_bridge.connect(T0)
        # The FakeBrokerAdapter reports zero open positions by default;
        # matching `expected_position_ids` to that avoids a
        # synchronization discrepancy that would leave the connection at
        # CONNECTED rather than READY.
        orchestrator.mt5_bridge.synchronize(T0, expected_position_ids=())

        result = orchestrator.manage_position(
            position_id="pos-1",
            trace_id="trace-pos-1",
            direction=Direction.UP,
            entry_price=1.1000,
            lifecycle_state=LifecycleState.FILLED,
            current_price=1.1030,  # favorable_distance=0.0030 >= default breakeven trigger
            current_stop_loss=1.0950,
            current_take_profit=1.1100,
            opened_at=T0,
            market_data_timestamp=T0,
            broker_position_exists=True,
            compliance_kill_switch_active=False,
            now=T0,
        )

        self.assertEqual(result.decision.action, ManagementAction.MOVE_TO_BREAKEVEN)
        self.assertIsInstance(result.request, PositionAdjustmentRequest)
        self.assertIsNone(result.submit_reject_reason)
        self.assertIsNotNone(result.broker_response)


class TestAnalyticsRecording(unittest.TestCase):
    def test_provenance_record_reflects_the_full_chain(self):
        orchestrator = build_orchestrator()
        result, now = run_ready_cycle(orchestrator)
        candidate_result = result.candidate_results[0]

        record = orchestrator.analytics.build_provenance_record(result.observation.trace_id, now)

        self.assertIsNotNone(record)
        self.assertIs(record.scanner_observation, result.observation)
        self.assertIs(record.candidate, candidate_result.candidate)
        self.assertIs(record.score_result, candidate_result.score_result)
        self.assertIs(record.risk_decision, candidate_result.risk_decision)
        self.assertIs(record.compliance_decision, candidate_result.compliance_decision)
        self.assertIs(record.execution_decision, candidate_result.execution_decision)
        self.assertIn(candidate_result.broker_response, record.broker_events)


class TestWatchdogObservation(unittest.TestCase):
    def test_healthy_cycle_reports_every_stage_healthy(self):
        from phantom_pipeline.position_manager.models import LifecycleState
        from phantom_pipeline.scanner.models import Direction

        orchestrator = build_orchestrator()
        result, now = run_ready_cycle(orchestrator)
        # Exercise Position Manager too, so every one of the 10 pipeline
        # stages has a recorded heartbeat -- a stage genuinely never
        # touched this cycle is correctly UNKNOWN (fail-closed), not a
        # defect; this test demonstrates the fully-exercised case.
        orchestrator.manage_position(
            position_id="pos-1", trace_id="trace-pos-1", direction=Direction.UP,
            entry_price=1.1000, lifecycle_state=LifecycleState.FILLED,
            current_price=1.1000, current_stop_loss=1.0950, current_take_profit=1.1100,
            opened_at=now, market_data_timestamp=now, broker_position_exists=True,
            compliance_kill_switch_active=False, now=now,
        )

        system_health = orchestrator.evaluate_watchdog_health(now)

        self.assertEqual(system_health.overall_health, HealthState.HEALTHY)
        observed_components = {ch.component for ch in system_health.component_health}
        self.assertIn("mt5_bridge", observed_components)
        self.assertIn("position_manager", observed_components)
        mt5_health = next(ch for ch in system_health.component_health if ch.component == "mt5_bridge")
        self.assertEqual(mt5_health.state, HealthState.HEALTHY)
        self.assertEqual(orchestrator.mt5_bridge.state, ConnectionState.READY)


class TestDashboardVisibility(unittest.TestCase):
    def test_views_reflect_the_cycle_via_prometheus_translation(self):
        from phantom_pipeline.position_manager.models import LifecycleState
        from phantom_pipeline.scanner.models import Direction

        orchestrator = build_orchestrator()
        result, now = run_ready_cycle(orchestrator)
        orchestrator.manage_position(
            position_id="pos-1", trace_id="trace-pos-1", direction=Direction.UP,
            entry_price=1.1000, lifecycle_state=LifecycleState.FILLED,
            current_price=1.1000, current_stop_loss=1.0950, current_take_profit=1.1100,
            opened_at=now, market_data_timestamp=now, broker_position_exists=True,
            compliance_kill_switch_active=False, now=now,
        )
        record = orchestrator.analytics.build_provenance_record(result.observation.trace_id, now)

        views = orchestrator.render_dashboard_snapshot(now, records=(record,))

        self.assertEqual(set(views.keys()), {
            "OVERVIEW", "TRADING", "RISK", "COMPLIANCE", "EXECUTION",
            "INFRASTRUCTURE", "ANALYTICS", "ALERTS", "RESEARCH", "AUDIT",
        })
        trading_components = {c.component for c in views["TRADING"].component_statuses}
        self.assertEqual(trading_components, {"scanner", "strategy_engine", "scoring_engine"})
        self.assertEqual(views["AUDIT"].trade_records, (record,))
        self.assertEqual(views["ALERTS"].alerts, ())  # nothing unhealthy -> no alerts


class TestReplayDeterminism(unittest.TestCase):
    def test_two_independent_orchestrators_produce_identical_results(self):
        orchestrator_a = build_orchestrator()
        orchestrator_b = build_orchestrator()

        result_a, _ = run_ready_cycle(orchestrator_a)
        result_b, _ = run_ready_cycle(orchestrator_b)

        self.assertEqual(result_a.observation, result_b.observation)
        self.assertEqual(len(result_a.candidate_results), len(result_b.candidate_results))
        for candidate_a, candidate_b in zip(result_a.candidate_results, result_b.candidate_results):
            self.assertEqual(candidate_a.candidate, candidate_b.candidate)
            self.assertEqual(candidate_a.score_result, candidate_b.score_result)
            self.assertEqual(candidate_a.risk_decision, candidate_b.risk_decision)
            self.assertEqual(candidate_a.compliance_decision, candidate_b.compliance_decision)
            self.assertEqual(candidate_a.execution_decision, candidate_b.execution_decision)


class TestPipelineRestart(unittest.TestCase):
    def test_fresh_orchestrator_starts_with_no_leaked_state(self):
        orchestrator_1 = build_orchestrator()
        run_ready_cycle(orchestrator_1)
        self.assertEqual(orchestrator_1.mt5_bridge.state, ConnectionState.READY)

        # A "restart" is simply building a fresh orchestrator: no global
        # or module-level state exists for it to inherit.
        orchestrator_2 = build_orchestrator()
        self.assertEqual(orchestrator_2.mt5_bridge.state, ConnectionState.DISCONNECTED)
        self.assertEqual(orchestrator_2.data_pipeline.get_historical_series(SYMBOL, TIMEFRAME).bars, ())

        result_2, _ = run_ready_cycle(orchestrator_2)
        self.assertEqual(len(result_2.candidate_results), 1)


class TestDuplicatePrevention(unittest.TestCase):
    def test_resubmitting_the_same_candidate_is_flagged_a_duplicate(self):
        orchestrator = build_orchestrator()
        result_1, now = run_ready_cycle(orchestrator)
        first = result_1.candidate_results[0]
        self.assertIsNone(first.submit_reject_reason)

        # Re-run the identical cycle (same bars already in the cache, same
        # `now`) without feeding new ticks -> Scanner/Strategy Engine
        # reproduce the identical trace_id/candidate_id deterministically,
        # so MT5 Bridge's own idempotency store must recognize the second
        # submission as a duplicate.
        entry_price = orchestrator.data_pipeline.get_snapshot(SYMBOL).price
        result_2 = orchestrator.run_scan_cycle(
            symbol=SYMBOL,
            timeframes=(TIMEFRAME,),
            primary_timeframe=PRIMARY_TIMEFRAME,
            session_time=now,
            now=now,
            risk_account_state=make_risk_account_state(),
            compliance_account_state=make_compliance_account_state(approve=True),
            execution_account_state=make_execution_account_state(),
            broker_state=make_broker_state(),
            news_state=make_news_state(),
            stop_distance=STOP_DISTANCE,
            expected_slippage=0.0001,
            reference_price=entry_price,
            intended_stop_loss=entry_price - STOP_DISTANCE,
            intended_take_profit=entry_price + STOP_DISTANCE * 3,
        )
        second = result_2.candidate_results[0]
        self.assertEqual(second.candidate.candidate_id, first.candidate.candidate_id)
        # Execution Validator's own idempotency layer (ADR-007 Sec7, a
        # second, independent layer from MT5 Bridge's own, ADR-008 Sec7 —
        # "either one failing alone must not produce a duplicate order")
        # catches the resubmission first: it rejects before MT5 Bridge's
        # own idempotency store ever gets a chance to.
        self.assertEqual(second.execution_decision.verdict, ExecutionVerdict.REJECT)
        self.assertIn("NO_DUPLICATE_REQUEST", second.execution_decision.blocking_reasons)
        self.assertEqual(second.submit_reject_reason, "execution_decision_not_approved")
        self.assertIsNone(second.broker_response)


class TestFailureRecovery(unittest.TestCase):
    def test_disconnected_mt5_bridge_reported_critical_then_recovers(self):
        orchestrator = build_orchestrator()
        result, now = run_ready_cycle(orchestrator)
        healthy = orchestrator.evaluate_watchdog_health(now)
        mt5_health = next(ch for ch in healthy.component_health if ch.component == "mt5_bridge")
        self.assertEqual(mt5_health.state, HealthState.HEALTHY)

        # Simulate a disconnect.
        orchestrator.mt5_bridge.disconnect(now)
        degraded = orchestrator.evaluate_watchdog_health(now + timedelta(seconds=1))
        mt5_degraded = next(ch for ch in degraded.component_health if ch.component == "mt5_bridge")
        self.assertEqual(mt5_degraded.state, HealthState.CRITICAL)
        self.assertEqual(degraded.overall_health, HealthState.CRITICAL)

        # Recover: reconnect + resynchronize.
        recover_time = now + timedelta(seconds=2)
        orchestrator.mt5_bridge.connect(recover_time)
        orchestrator.mt5_bridge.synchronize(recover_time, expected_position_ids=())
        recovered = orchestrator.evaluate_watchdog_health(recover_time)
        mt5_recovered = next(ch for ch in recovered.component_health if ch.component == "mt5_bridge")
        self.assertEqual(mt5_recovered.state, HealthState.HEALTHY)
        # Never fabricated: recovery reflects the real reconnect/
        # resynchronize sequence just performed, not an assumed-good
        # default (ADR-011 Hard Rules).
        self.assertEqual(orchestrator.mt5_bridge.state, ConnectionState.READY)


class TestTraceContinuity(unittest.TestCase):
    def test_trace_id_and_candidate_id_identical_across_every_stage(self):
        orchestrator = build_orchestrator()
        result, now = run_ready_cycle(orchestrator)
        candidate_result = result.candidate_results[0]

        trace_id = result.observation.trace_id
        candidate_id = candidate_result.candidate.candidate_id

        self.assertEqual(candidate_result.candidate.trace_id, trace_id)
        self.assertEqual(candidate_result.score_result.trace_id, trace_id)
        self.assertEqual(candidate_result.score_result.candidate_id, candidate_id)
        self.assertEqual(candidate_result.risk_decision.trace_id, trace_id)
        self.assertEqual(candidate_result.risk_decision.candidate_id, candidate_id)
        self.assertEqual(candidate_result.compliance_decision.trace_id, trace_id)
        self.assertEqual(candidate_result.compliance_decision.candidate_id, candidate_id)
        self.assertEqual(candidate_result.execution_decision.trace_id, trace_id)
        self.assertEqual(candidate_result.execution_decision.candidate_id, candidate_id)
        self.assertEqual(candidate_result.broker_response.trace_id, trace_id)

        # Version propagation: every stage's own version string travels
        # with its object, never invented by the orchestrator.
        self.assertTrue(candidate_result.risk_decision.risk_engine_version)
        self.assertTrue(candidate_result.compliance_decision.compliance_engine_version)
        self.assertTrue(candidate_result.execution_decision.execution_validator_version)


if __name__ == "__main__":
    unittest.main()
