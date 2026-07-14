"""Tests for RuntimeAuditRecord completeness (Final Release Hardening,
requirement 4). Every new field records an already-computed value from
another engine's snapshot -- these tests verify population (present
once its stage is reached, absent/default before), and determinism of
the two hash fields, without duplicating any engine's own logic."""

from __future__ import annotations

import dataclasses
import unittest

from titan_protocol.compliance_engine.explainability import build_compliance_snapshot
from titan_protocol.compliance_engine.models import ComplianceDecision, ComplianceRuleId, LockRecommendation
from titan_protocol.evidence_engine.models import SessionName
from titan_protocol.risk_engine.models import PortfolioState
from titan_protocol.runtime.engine import RuntimeOrchestrator
from titan_protocol.runtime.models import SCHEMA_VERSION, CycleOutcome, CycleStage, TradingWindow
from tests.titan_protocol.risk_engine._fixtures import make_strategy_snapshot
from tests.titan_protocol.runtime._fixtures import (
    T0,
    make_account_state,
    make_bars,
    make_compliance_snapshot,
    make_config,
    make_market_safety_inputs,
    make_profile,
    make_qualified_strategy_snapshot,
    make_risk_snapshot,
    make_stub_bridge_submit,
    make_stub_compliance_engine,
    make_stub_evidence_engine,
    make_stub_mi_engine,
    make_stub_risk_engine,
    make_stub_strategy_engine,
)


def _run(evidence=None, mi=None, strategy=None, risk=None, compliance=None, bridge_submit=None, timeframe: str = "", profile=None):
    evidence_stub = make_stub_evidence_engine(evidence)
    mi_stub = make_stub_mi_engine(mi)
    strategy_stub = make_stub_strategy_engine(strategy)
    risk_stub = make_stub_risk_engine(risk)
    compliance_stub = make_stub_compliance_engine(compliance)
    bridge_submit = bridge_submit if bridge_submit is not None else make_stub_bridge_submit()
    orchestrator = RuntimeOrchestrator(
        make_config(), evidence_stub, mi_stub, strategy_stub, risk_stub, compliance_stub, bridge_submit,
        timeframe=timeframe,
    )
    return orchestrator.run_cycle_for_pair(
        "EURUSD", make_bars(), (), 1.0, 1.0, make_market_safety_inputs(),
        PortfolioState(), None, make_account_state(), profile or make_profile(), T0, "CYCLE-1",
    )


class TestDecisionIdAndConfigSchemaVersion(unittest.TestCase):
    def test_decision_id_is_populated_even_before_any_engine_is_called(self):
        record = _run()
        self.assertTrue(record.decision_id)
        self.assertIn("CYCLE-1", record.decision_id)
        self.assertIn("EURUSD", record.decision_id)

    def test_config_schema_version_matches_the_module_constant(self):
        record = _run()
        self.assertEqual(record.config_schema_version, SCHEMA_VERSION)


class TestTimeframeIsCarriedFromTheConstructor(unittest.TestCase):
    def test_timeframe_defaults_to_empty_string(self):
        record = _run()
        self.assertEqual(record.timeframe, "")

    def test_timeframe_reflects_the_constructor_argument(self):
        record = _run(timeframe="M15")
        self.assertEqual(record.timeframe, "M15")


class TestEvidenceAndMarketIntelligenceSummaries(unittest.TestCase):
    def test_both_summaries_empty_when_stopped_before_evidence(self):
        outside_window_profile = make_profile(trading_window=TradingWindow(start_hour_utc=0, end_hour_utc=1))
        record = _run(profile=outside_window_profile)
        self.assertEqual(record.outcome, CycleOutcome.OUTSIDE_TRADING_WINDOW)
        self.assertEqual(record.evidence_summary, "")
        self.assertEqual(record.market_intelligence_summary, "")

    def test_evidence_summary_present_but_mi_summary_empty_when_stopped_after_evidence(self):
        # Default evidence fixture reports SessionName.LONDON_NEW_YORK_OVERLAP --
        # restricting session_rules to LONDON alone forces SESSION_NOT_ALLOWED,
        # which stops the cycle right after Evidence, before MI is ever called.
        session_restricted_profile = make_profile(session_rules=(SessionName.LONDON,))
        record = _run(profile=session_restricted_profile)
        self.assertEqual(record.outcome, CycleOutcome.SESSION_NOT_ALLOWED)
        self.assertTrue(record.evidence_summary)
        self.assertEqual(record.market_intelligence_summary, "")

    def test_both_summaries_present_once_the_full_pipeline_runs(self):
        record = _run()
        self.assertEqual(record.outcome, CycleOutcome.SUBMITTED)
        self.assertTrue(record.evidence_summary)
        self.assertTrue(record.market_intelligence_summary)


class TestRiskReasons(unittest.TestCase):
    def test_empty_before_risk_stage(self):
        rejected_strategy = make_strategy_snapshot(rejected=True)
        record = _run(strategy=rejected_strategy)
        self.assertEqual(record.risk_reasons, ())

    def test_populated_once_risk_is_evaluated(self):
        risk_snapshot = dataclasses.replace(make_risk_snapshot(approved=False), reasons=("daily risk limit reached",))
        record = _run(strategy=make_qualified_strategy_snapshot(), risk=risk_snapshot)
        self.assertEqual(record.outcome, CycleOutcome.RISK_REJECTED)
        self.assertEqual(record.risk_reasons, ("daily risk limit reached",))


class TestComplianceTriggeredRulesAndLock(unittest.TestCase):
    def test_empty_before_compliance_stage(self):
        risk_snapshot = make_risk_snapshot(approved=False)
        record = _run(strategy=make_qualified_strategy_snapshot(), risk=risk_snapshot)
        self.assertEqual(record.compliance_triggered_rules, ())
        self.assertIsNone(record.compliance_lock_trigger)
        self.assertIsNone(record.compliance_lock_reason)

    def test_triggered_rules_and_lock_recommendation_are_recorded(self):
        compliance_snapshot = build_compliance_snapshot(
            pair="EURUSD", now=T0, decision=ComplianceDecision.REJECT,
            original_size_r=1.0, approved_size_r=0.0, reason="daily loss limit exceeded -- test",
            triggered_rules=(ComplianceRuleId.DAILY_LOSS_LIMIT_EXCEEDED,), warnings=(), compliance_score=10.0,
            lock_recommendation=LockRecommendation(trigger=True, reason="daily loss limit exceeded -- test"),
        )
        record = _run(strategy=make_qualified_strategy_snapshot(), compliance=compliance_snapshot)
        self.assertEqual(record.outcome, CycleOutcome.COMPLIANCE_REJECTED)
        self.assertEqual(record.compliance_triggered_rules, ("DAILY_LOSS_LIMIT_EXCEEDED",))
        self.assertTrue(record.compliance_lock_trigger)
        self.assertEqual(record.compliance_lock_reason, "daily loss limit exceeded -- test")

    def test_no_lock_recommendation_leaves_lock_fields_none_even_when_compliance_ran(self):
        record = _run()  # default fixture: APPROVE, lock_recommendation=None
        self.assertEqual(record.outcome, CycleOutcome.SUBMITTED)
        self.assertIsNone(record.compliance_lock_trigger)
        self.assertIsNone(record.compliance_lock_reason)


class TestBridgeCorrelationId(unittest.TestCase):
    def test_none_when_no_command_was_ever_built(self):
        risk_snapshot = make_risk_snapshot(approved=False)
        record = _run(strategy=make_qualified_strategy_snapshot(), risk=risk_snapshot)
        self.assertIsNone(record.bridge_correlation_id)

    def test_present_on_submission_and_matches_cycle_and_pair(self):
        record = _run()
        self.assertEqual(record.outcome, CycleOutcome.SUBMITTED)
        self.assertIsNotNone(record.bridge_correlation_id)
        self.assertIn("CYCLE-1", record.bridge_correlation_id)
        self.assertIn("EURUSD", record.bridge_correlation_id)


class TestSnapshotHashAndDecisionFingerprintDeterminism(unittest.TestCase):
    def test_identical_inputs_produce_identical_hashes(self):
        record_a = _run()
        record_b = _run()
        self.assertEqual(record_a.snapshot_hash, record_b.snapshot_hash)
        self.assertEqual(record_a.decision_fingerprint, record_b.decision_fingerprint)

    def test_hashes_are_non_empty(self):
        record = _run()
        self.assertTrue(record.snapshot_hash)
        self.assertTrue(record.decision_fingerprint)

    def test_different_outcomes_produce_different_decision_fingerprints(self):
        approved_record = _run()
        rejected_strategy = make_strategy_snapshot(rejected=True)
        rejected_record = _run(strategy=rejected_strategy)
        self.assertNotEqual(approved_record.decision_fingerprint, rejected_record.decision_fingerprint)

    def test_different_timeframes_produce_different_snapshot_hashes(self):
        record_m15 = _run(timeframe="M15")
        record_h1 = _run(timeframe="H1")
        self.assertNotEqual(record_m15.snapshot_hash, record_h1.snapshot_hash)


class TestLoggingSinkSurfacesNewFields(unittest.TestCase):
    def test_log_record_extra_contains_new_fields(self):
        """`run_cycle_for_pair` already calls `log_runtime_audit_record`
        internally on every return path -- attach the handler before
        running the cycle and observe that one real call, rather than
        invoking the sink a second time (which would double-log)."""
        import logging

        captured = []

        class _Handler(logging.Handler):
            def emit(self, record):
                captured.append(record)

        logger = logging.getLogger("titan_protocol.runtime")
        handler = _Handler()
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        try:
            record = _run(timeframe="M15")
        finally:
            logger.removeHandler(handler)

        self.assertEqual(len(captured), 1)
        log_record = captured[0]
        self.assertEqual(log_record.decision_id, record.decision_id)
        self.assertEqual(log_record.timeframe, "M15")
        self.assertEqual(log_record.snapshot_hash, record.snapshot_hash)
        self.assertEqual(log_record.decision_fingerprint, record.decision_fingerprint)
        self.assertEqual(log_record.bridge_correlation_id, record.bridge_correlation_id)


if __name__ == "__main__":
    unittest.main()
