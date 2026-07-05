"""Boundary/type-level and immutability tests (ADR-010 §5, §12)."""

from __future__ import annotations

import dataclasses
import unittest

from phantom_pipeline.analytics.models import (
    FinalOutcome,
    MissingEventReport,
    OutcomeKind,
    PerformanceStatistics,
    ReplayInputSet,
    TradeProvenanceRecord,
)
from tests.phantom_pipeline.analytics._fixtures import T0

FORBIDDEN_FIELD_NAME_FRAGMENTS = ("modified_", "new_score", "new_risk", "verdict_override")


def _make_record(**overrides) -> TradeProvenanceRecord:
    kwargs = dict(
        schema_version=1, trace_id="t1", scanner_observation=None, candidate=None, score_result=None,
        risk_decision=None, compliance_decision=None, execution_decision=None, broker_events=(),
        fill_reports=(), position_management_decisions=(), position_updates=(),
        position_synchronization_results=(), account_snapshots=(), market_snapshots=(),
        final_outcome=None, analytics_version="1.0.0-phase1", collected_at=T0,
    )
    kwargs.update(overrides)
    return TradeProvenanceRecord(**kwargs)


class TestTradeProvenanceRecordImmutability(unittest.TestCase):
    def test_frozen(self):
        record = _make_record()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            record.trace_id = "other"  # type: ignore[misc]

    def test_broker_events_coerced_to_tuple(self):
        record = _make_record(broker_events=[])
        self.assertIsInstance(record.broker_events, tuple)

    def test_account_snapshots_coerced_to_tuple(self):
        record = _make_record(account_snapshots=[1, 2])
        self.assertIsInstance(record.account_snapshots, tuple)


class TestOtherOutputTypes(unittest.TestCase):
    def test_missing_event_report_frozen_and_coerced(self):
        report = MissingEventReport(trace_id="t1", missing_fields=["a", "b"], detail="x", timestamp=T0)
        self.assertIsInstance(report.missing_fields, tuple)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            report.detail = "y"  # type: ignore[misc]

    def test_final_outcome_frozen(self):
        outcome = FinalOutcome(OutcomeKind.OPEN, None, None, None, None, None, None)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            outcome.realized_pnl = 1.0  # type: ignore[misc]

    def test_performance_statistics_frozen(self):
        stats = PerformanceStatistics(0, None, None, None, None, None, None, None, None, T0, "1.0.0-phase1")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            stats.trade_count = 5  # type: ignore[misc]

    def test_replay_input_set_frozen_and_coerced(self):
        replay_set = ReplayInputSet("t1", None, None, None, None, None, None, [], T0)
        self.assertIsInstance(replay_set.market_snapshots, tuple)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            replay_set.trace_id = "other"  # type: ignore[misc]


class TestBoundaryTypeLevel(unittest.TestCase):
    def test_no_output_type_holds_a_forbidden_field(self):
        for cls in (TradeProvenanceRecord, MissingEventReport, FinalOutcome, PerformanceStatistics, ReplayInputSet):
            field_names = {f.name for f in dataclasses.fields(cls)}
            for fragment in FORBIDDEN_FIELD_NAME_FRAGMENTS:
                for name in field_names:
                    self.assertNotIn(fragment, name, f"forbidden fragment '{fragment}' found in '{cls.__name__}.{name}'")


if __name__ == "__main__":
    unittest.main()
