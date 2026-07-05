"""Missing-event and schema-validation detection tests (ADR-010 §6, §12)."""

from __future__ import annotations

import unittest

from dataclasses import dataclass

from phantom_pipeline.analytics import checks as c
from phantom_pipeline.analytics.models import TradeProvenanceRecord
from tests.phantom_pipeline.analytics._fixtures import (
    T0,
    make_candidate,
    make_compliance_decision,
    make_risk_decision,
    make_score_result,
)


@dataclass(frozen=True)
class _FakeScannerObservation:
    """A minimal stand-in carrying only the `schema_version` attribute
    `checks.py`'s schema-validation logic reads — sufficient for tests
    that only need "a scanner observation was present," not its full
    field set."""

    schema_version: int = 1


def _record(**overrides) -> TradeProvenanceRecord:
    kwargs = dict(
        schema_version=1, trace_id="t1", scanner_observation=None, candidate=None, score_result=None,
        risk_decision=None, compliance_decision=None, execution_decision=None, broker_events=(),
        fill_reports=(), position_management_decisions=(), position_updates=(),
        position_synchronization_results=(), account_snapshots=(), market_snapshots=(),
        final_outcome=None, analytics_version="1.0.0-phase1", collected_at=T0,
    )
    kwargs.update(overrides)
    return TradeProvenanceRecord(**kwargs)


class TestDetectIssuesCompleteRecord(unittest.TestCase):
    def test_empty_record_has_no_issues(self):
        self.assertIsNone(c.detect_issues(_record(), T0))

    def test_full_approved_chain_up_to_score_result_has_no_issues(self):
        candidate = make_candidate()
        score_result = make_score_result(candidate)
        record = _record(candidate=candidate, score_result=score_result, scanner_observation=_FakeScannerObservation())
        self.assertIsNone(c.detect_issues(record, T0))


class TestMissingChainLinks(unittest.TestCase):
    def test_candidate_without_scanner_observation_is_flagged(self):
        candidate = make_candidate()
        record = _record(candidate=candidate)
        report = c.detect_issues(record, T0)
        self.assertIsNotNone(report)
        self.assertIn("scanner_observation", report.missing_fields)

    def test_score_result_without_candidate_is_flagged(self):
        candidate = make_candidate()
        score_result = make_score_result(candidate)
        record = _record(score_result=score_result)
        report = c.detect_issues(record, T0)
        self.assertIn("candidate", report.missing_fields)

    def test_risk_decision_without_score_result_is_flagged(self):
        candidate = make_candidate()
        score_result = make_score_result(candidate)
        risk_decision = make_risk_decision(candidate, score_result)
        record = _record(risk_decision=risk_decision)
        report = c.detect_issues(record, T0)
        self.assertIn("score_result", report.missing_fields)

    def test_compliance_decision_without_risk_decision_is_flagged(self):
        candidate = make_candidate()
        score_result = make_score_result(candidate)
        risk_decision = make_risk_decision(candidate, score_result)
        compliance_decision = make_compliance_decision(candidate, score_result, risk_decision)
        record = _record(compliance_decision=compliance_decision)
        report = c.detect_issues(record, T0)
        self.assertIn("risk_decision", report.missing_fields)

    def test_approved_compliance_without_execution_decision_is_flagged(self):
        candidate = make_candidate()
        score_result = make_score_result(candidate)
        risk_decision = make_risk_decision(candidate, score_result)
        compliance_decision = make_compliance_decision(candidate, score_result, risk_decision, verdict_approve=True)
        record = _record(
            candidate=candidate, score_result=score_result, risk_decision=risk_decision,
            compliance_decision=compliance_decision, scanner_observation=_FakeScannerObservation(),
        )
        report = c.detect_issues(record, T0)
        self.assertIsNotNone(report)
        self.assertIn("execution_decision", report.missing_fields)

    def test_blocked_compliance_without_execution_decision_is_not_flagged(self):
        candidate = make_candidate()
        score_result = make_score_result(candidate)
        risk_decision = make_risk_decision(candidate, score_result)
        compliance_decision = make_compliance_decision(candidate, score_result, risk_decision, verdict_approve=False)
        record = _record(
            candidate=candidate, score_result=score_result, risk_decision=risk_decision,
            compliance_decision=compliance_decision, scanner_observation=_FakeScannerObservation(),
        )
        self.assertIsNone(c.detect_issues(record, T0))

    def test_fill_reports_without_broker_events_is_flagged(self):
        record = _record(fill_reports=("fake-fill",))
        report = c.detect_issues(record, T0)
        self.assertIn("broker_events", report.missing_fields)

    def test_fill_reports_without_position_updates_is_flagged(self):
        record = _record(fill_reports=("fake-fill",), broker_events=("fake-ack",))
        report = c.detect_issues(record, T0)
        self.assertIn("position_updates", report.missing_fields)

    def test_multiple_gaps_are_all_reported_together(self):
        candidate = make_candidate()
        score_result = make_score_result(candidate)
        record = _record(candidate=candidate, score_result=score_result, fill_reports=("fake-fill",))
        report = c.detect_issues(record, T0)
        self.assertIn("scanner_observation", report.missing_fields)
        self.assertIn("broker_events", report.missing_fields)
        self.assertIn("position_updates", report.missing_fields)


class TestSchemaValidation(unittest.TestCase):
    def test_unsupported_schema_version_is_flagged(self):
        candidate = make_candidate()
        bad_candidate = candidate.__class__(**{**candidate.__dict__, "schema_version": 999})
        record = _record(candidate=bad_candidate, scanner_observation=_FakeScannerObservation())
        report = c.detect_issues(record, T0)
        self.assertIsNotNone(report)
        self.assertIn("candidate:unsupported_schema_version", report.missing_fields)

    def test_supported_schema_version_is_not_flagged(self):
        candidate = make_candidate()
        record = _record(candidate=candidate, scanner_observation=_FakeScannerObservation())
        self.assertIsNone(c.detect_issues(record, T0))


if __name__ == "__main__":
    unittest.main()
