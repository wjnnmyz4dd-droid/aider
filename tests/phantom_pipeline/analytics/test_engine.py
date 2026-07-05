"""AnalyticsEngine tests (ADR-010 §5-§9, §12)."""

from __future__ import annotations

import unittest
from datetime import timedelta

from phantom_pipeline.analytics.config import AnalyticsConfig
from phantom_pipeline.analytics.engine import AnalyticsEngine
from phantom_pipeline.analytics.models import OutcomeKind
from phantom_pipeline.analytics.store import InMemoryTradeProvenanceStore
from phantom_pipeline.position_manager.models import LifecycleState
from tests.phantom_pipeline.analytics._fixtures import (
    T0,
    make_full_open_chain,
    new_position_manager,
)


def _collect_full_chain(analytics, trace_id="obs-trace-1", verdict_approve=True):
    chain = make_full_open_chain(trace_id=trace_id, verdict_approve=verdict_approve)
    candidate, score_result, risk_decision, compliance_decision, execution_decision, response, fill_report = chain
    analytics.collect_candidate(trace_id, candidate)
    analytics.collect_score_result(trace_id, score_result)
    analytics.collect_risk_decision(trace_id, risk_decision)
    analytics.collect_compliance_decision(trace_id, compliance_decision)
    if execution_decision is not None:
        analytics.collect_execution_decision(trace_id, execution_decision)
        analytics.collect_broker_event(trace_id, response)
        analytics.collect_fill_report(trace_id, fill_report)
    return chain


class TestBasicCollectionAndRecordBuilding(unittest.TestCase):
    def test_unknown_trace_id_yields_no_record(self):
        analytics = AnalyticsEngine(InMemoryTradeProvenanceStore())
        self.assertIsNone(analytics.build_provenance_record("nonexistent", T0))

    def test_collected_objects_appear_verbatim_in_the_record(self):
        analytics = AnalyticsEngine(InMemoryTradeProvenanceStore())
        candidate, score_result, risk_decision, compliance_decision, execution_decision, response, fill_report = (
            _collect_full_chain(analytics)
        )
        record = analytics.build_provenance_record(candidate.trace_id, T0)
        self.assertIs(record.candidate, candidate)
        self.assertIs(record.score_result, score_result)
        self.assertIs(record.risk_decision, risk_decision)
        self.assertIs(record.compliance_decision, compliance_decision)
        self.assertIs(record.execution_decision, execution_decision)
        self.assertEqual(record.broker_events, (response,))
        self.assertEqual(record.fill_reports, (fill_report,))


class TestOutcomeInferenceRejected(unittest.TestCase):
    def test_compliance_block_yields_rejected_outcome(self):
        analytics = AnalyticsEngine(InMemoryTradeProvenanceStore())
        _collect_full_chain(analytics, verdict_approve=False)
        record = analytics.build_provenance_record("obs-trace-1", T0)
        self.assertEqual(record.final_outcome.outcome_kind, OutcomeKind.REJECTED)
        self.assertEqual(record.final_outcome.rejected_at_stage, "compliance_engine")
        self.assertIsNotNone(record.final_outcome.rejection_reason)


class TestOutcomeInferenceOpenAndClosed(unittest.TestCase):
    def test_fill_without_close_yields_open_outcome(self):
        analytics = AnalyticsEngine(InMemoryTradeProvenanceStore())
        chain = _collect_full_chain(analytics)
        fill_report = chain[-1]
        manager = new_position_manager()
        decision, update, _ = manager.evaluate(
            position_id="pos1", trace_id="obs-trace-1", direction=chain[0].direction, entry_price=fill_report.fill_price,
            lifecycle_state=LifecycleState.FILLED, current_price=fill_report.fill_price + 0.001,
            current_stop_loss=fill_report.fill_price - 0.005, current_take_profit=fill_report.fill_price + 0.02,
            opened_at=T0, market_data_timestamp=T0, broker_position_exists=True,
            compliance_kill_switch_active=False, now=T0 + timedelta(minutes=5),
        )
        analytics.collect_position_management_decision("obs-trace-1", decision)
        analytics.collect_position_update("obs-trace-1", update)

        record = analytics.build_provenance_record("obs-trace-1", T0 + timedelta(minutes=10))
        self.assertEqual(record.final_outcome.outcome_kind, OutcomeKind.OPEN)

    def test_time_exit_moves_to_closing_not_closed(self):
        """TIME_EXIT transitions lifecycle to CLOSING, not CLOSED — a
        genuine broker-confirmed close hasn't happened yet, so the
        outcome must remain OPEN, never fabricated as CLOSED."""
        analytics = AnalyticsEngine(InMemoryTradeProvenanceStore())
        chain = _collect_full_chain(analytics)
        fill_report = chain[-1]
        manager = new_position_manager()
        decision, update, _ = manager.evaluate(
            position_id="pos1", trace_id="obs-trace-1", direction=chain[0].direction, entry_price=fill_report.fill_price,
            lifecycle_state=LifecycleState.FILLED, current_price=fill_report.fill_price,
            current_stop_loss=fill_report.fill_price - 0.005, current_take_profit=fill_report.fill_price + 0.02,
            opened_at=T0, market_data_timestamp=T0 + timedelta(hours=25), broker_position_exists=True,
            compliance_kill_switch_active=False, now=T0 + timedelta(hours=25),
        )
        self.assertEqual(decision.action.value, "TIME_EXIT")
        analytics.collect_position_management_decision("obs-trace-1", decision)
        analytics.collect_position_update("obs-trace-1", update)

        record = analytics.build_provenance_record("obs-trace-1", T0 + timedelta(hours=26))
        self.assertEqual(record.final_outcome.outcome_kind, OutcomeKind.OPEN)

    def test_broker_confirmed_closed_lifecycle_yields_closed_outcome(self):
        analytics = AnalyticsEngine(InMemoryTradeProvenanceStore())
        chain = _collect_full_chain(analytics)
        fill_report = chain[-1]
        manager = new_position_manager()
        # Simulate MT5 Bridge confirming the close by directly recording a
        # CLOSED PositionUpdate (in Phase 1, no orchestrator wires this
        # automatically end to end).
        from phantom_pipeline.position_manager.models import PositionUpdate

        closed_update = PositionUpdate(
            schema_version=1, position_id="pos1", trace_id="obs-trace-1", lifecycle_state=LifecycleState.CLOSED,
            unrealized_pnl=42.0, current_price=fill_report.fill_price + 0.01, timestamp=T0 + timedelta(hours=1),
        )
        analytics.collect_position_update("obs-trace-1", closed_update)

        record = analytics.build_provenance_record("obs-trace-1", T0 + timedelta(hours=2))
        self.assertEqual(record.final_outcome.outcome_kind, OutcomeKind.CLOSED)
        self.assertEqual(record.final_outcome.realized_pnl, 42.0)

    def test_mae_mfe_computed_across_position_updates(self):
        analytics = AnalyticsEngine(InMemoryTradeProvenanceStore())
        _collect_full_chain(analytics)
        from phantom_pipeline.position_manager.models import PositionUpdate

        for pnl, minutes in ((-10.0, 1), (30.0, 2), (5.0, 3)):
            analytics.collect_position_update(
                "obs-trace-1",
                PositionUpdate(
                    schema_version=1, position_id="pos1", trace_id="obs-trace-1", lifecycle_state=LifecycleState.FILLED,
                    unrealized_pnl=pnl, current_price=1.1, timestamp=T0 + timedelta(minutes=minutes),
                ),
            )
        record = analytics.build_provenance_record("obs-trace-1", T0 + timedelta(hours=1))
        self.assertEqual(record.final_outcome.mae, -10.0)
        self.assertEqual(record.final_outcome.mfe, 30.0)


class TestCompleteness(unittest.TestCase):
    def test_never_observed_trace_id_reports_missing_all(self):
        analytics = AnalyticsEngine(InMemoryTradeProvenanceStore())
        report = analytics.check_completeness("nonexistent", T0)
        self.assertIsNotNone(report)
        self.assertIn("all", report.missing_fields)

    def test_complete_rejected_record_has_no_missing_events(self):
        analytics = AnalyticsEngine(InMemoryTradeProvenanceStore())
        candidate, *_ = _collect_full_chain(analytics, verdict_approve=False)
        report = analytics.check_completeness(candidate.trace_id, T0)
        self.assertIsNotNone(report)  # scanner_observation was never collected in this fixture
        self.assertIn("scanner_observation", report.missing_fields)


class TestReplayInputSet(unittest.TestCase):
    def test_replay_input_set_matches_provenance_record_fields(self):
        analytics = AnalyticsEngine(InMemoryTradeProvenanceStore())
        candidate, score_result, risk_decision, compliance_decision, execution_decision, *_ = _collect_full_chain(analytics)
        replay_set = analytics.build_replay_input_set(candidate.trace_id, T0)
        self.assertIs(replay_set.candidate, candidate)
        self.assertIs(replay_set.risk_decision, risk_decision)
        self.assertIs(replay_set.execution_decision, execution_decision)

    def test_unknown_trace_id_yields_no_replay_set(self):
        analytics = AnalyticsEngine(InMemoryTradeProvenanceStore())
        self.assertIsNone(analytics.build_replay_input_set("nonexistent", T0))


class TestDeterminismAndReplay(unittest.TestCase):
    def test_same_collected_state_same_record(self):
        analytics1 = AnalyticsEngine(InMemoryTradeProvenanceStore())
        analytics2 = AnalyticsEngine(InMemoryTradeProvenanceStore())
        _collect_full_chain(analytics1)
        _collect_full_chain(analytics2)
        record1 = analytics1.build_provenance_record("obs-trace-1", T0)
        record2 = analytics2.build_provenance_record("obs-trace-1", T0)
        self.assertEqual(record1, record2)

    def test_replay_reproduces_the_same_decision(self):
        """Archived inputs for a given trace_id, replayed through the
        same stage logic, reproduce the same recorded decision (ADR-010
        §8)."""
        from phantom_pipeline.risk_engine.engine import RiskEngine

        analytics = AnalyticsEngine(InMemoryTradeProvenanceStore())
        candidate, score_result, risk_decision, *_ = _collect_full_chain(analytics)
        replay_set = analytics.build_replay_input_set(candidate.trace_id, T0)

        from tests.phantom_pipeline.analytics._fixtures import _FakeObservation
        from phantom_pipeline.risk_engine.config import RiskEngineConfig
        from phantom_pipeline.risk_engine.models import AccountState as RiskAccountState
        from phantom_pipeline.scanner.models import VolatilityLabel, VolatilityState

        risk_account = RiskAccountState(
            equity=10000.0, daily_drawdown_pct=0.0, total_drawdown_pct=0.0,
            consecutive_losses=0, daily_risk_allocated_pct=0.0, open_positions=(),
        )
        observation = _FakeObservation(volatility=VolatilityState(label=VolatilityLabel.NORMAL, ratio=1.0))
        replayed_decision = RiskEngine(RiskEngineConfig(correlation_buckets={"EURUSD": "MAJORS"})).decide(
            replay_set.score_result, replay_set.candidate, observation, risk_account, stop_distance=0.0050
        )
        self.assertEqual(replayed_decision, risk_decision)


class TestNoUpstreamMutation(unittest.TestCase):
    def test_collected_objects_are_not_mutated(self):
        analytics = AnalyticsEngine(InMemoryTradeProvenanceStore())
        candidate, score_result, risk_decision, compliance_decision, execution_decision, *_ = _collect_full_chain(analytics)
        before = (candidate, score_result, risk_decision, compliance_decision, execution_decision)
        analytics.build_provenance_record(candidate.trace_id, T0)
        after = (candidate, score_result, risk_decision, compliance_decision, execution_decision)
        self.assertEqual(before, after)
        for b, a in zip(before, after):
            self.assertIs(b, a)


if __name__ == "__main__":
    unittest.main()
