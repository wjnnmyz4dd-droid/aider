"""Attribution grouping tests (ADR-010 §9)."""

from __future__ import annotations

import unittest
from dataclasses import dataclass

from phantom_pipeline.analytics import attribution
from phantom_pipeline.analytics.models import TradeProvenanceRecord
from phantom_pipeline.scanner.models import RangeStructure, SessionState
from phantom_pipeline.strategy_engine.playbook import Playbook, PlaybookMetadata
from phantom_pipeline.strategy_engine.registry import StrategyRegistry
from tests.phantom_pipeline.analytics._fixtures import T0, make_candidate


def _playbook_class(strategy_id: str):
    metadata = PlaybookMetadata(strategy_id, "1.0.0", "test", (), (), (1,))

    class _P(Playbook):
        @property
        def metadata(self) -> PlaybookMetadata:
            return metadata

        def evaluate(self, observation, config):
            return ()

    _P.__name__ = f"P_{strategy_id}"
    return _P


@dataclass(frozen=True)
class _FakeScannerObservation:
    range_structure: RangeStructure
    session: SessionState


def _record(candidate=None, scanner_observation=None, risk_decision=None, trace_id="t1") -> TradeProvenanceRecord:
    return TradeProvenanceRecord(
        schema_version=1, trace_id=trace_id, scanner_observation=scanner_observation, candidate=candidate,
        score_result=None, risk_decision=risk_decision, compliance_decision=None, execution_decision=None,
        broker_events=(), fill_reports=(), position_management_decisions=(), position_updates=(),
        position_synchronization_results=(), account_snapshots=(), market_snapshots=(),
        final_outcome=None, analytics_version="1.0.0-phase1", collected_at=T0,
    )


class TestGroupByStrategy(unittest.TestCase):
    def test_groups_by_registered_strategy_id(self):
        registry = StrategyRegistry(playbook_classes=[_playbook_class("TEST_STRATEGY"), _playbook_class("OTHER")])
        r1 = _record(candidate=make_candidate(strategy_id="TEST_STRATEGY", trace_id="t1"), trace_id="t1")
        r2 = _record(candidate=make_candidate(strategy_id="OTHER", trace_id="t2"), trace_id="t2")
        groups = attribution.group_by_strategy([r1, r2], registry)
        self.assertEqual(set(groups.keys()), {"TEST_STRATEGY", "OTHER"})
        self.assertEqual(groups["TEST_STRATEGY"], (r1,))

    def test_unregistered_strategy_id_is_excluded_not_fabricated(self):
        registry = StrategyRegistry(playbook_classes=[_playbook_class("KNOWN")])
        r1 = _record(candidate=make_candidate(strategy_id="UNKNOWN_ROGUE_STRATEGY", trace_id="t1"), trace_id="t1")
        groups = attribution.group_by_strategy([r1], registry)
        self.assertEqual(groups, {})

    def test_records_without_candidate_are_excluded(self):
        registry = StrategyRegistry(playbook_classes=[_playbook_class("KNOWN")])
        groups = attribution.group_by_strategy([_record()], registry)
        self.assertEqual(groups, {})


class TestGroupByRegime(unittest.TestCase):
    def test_groups_by_range_structure(self):
        obs1 = _FakeScannerObservation(RangeStructure.EXPANSION, SessionState((), None))
        obs2 = _FakeScannerObservation(RangeStructure.COMPRESSION, SessionState((), None))
        r1 = _record(scanner_observation=obs1, trace_id="t1")
        r2 = _record(scanner_observation=obs2, trace_id="t2")
        groups = attribution.group_by_regime([r1, r2])
        self.assertEqual(set(groups.keys()), {"EXPANSION", "COMPRESSION"})

    def test_records_without_scanner_observation_are_excluded(self):
        groups = attribution.group_by_regime([_record()])
        self.assertEqual(groups, {})


class TestGroupBySession(unittest.TestCase):
    def test_groups_by_active_sessions_joined(self):
        obs = _FakeScannerObservation(RangeStructure.NEUTRAL, SessionState(("LONDON", "NEW_YORK"), 0.5))
        r1 = _record(scanner_observation=obs, trace_id="t1")
        groups = attribution.group_by_session([r1])
        self.assertIn("LONDON+NEW_YORK", groups)

    def test_no_active_sessions_groups_as_none(self):
        obs = _FakeScannerObservation(RangeStructure.NEUTRAL, SessionState((), None))
        r1 = _record(scanner_observation=obs, trace_id="t1")
        groups = attribution.group_by_session([r1])
        self.assertIn("NONE", groups)


class TestGroupByPair(unittest.TestCase):
    def test_groups_by_candidate_symbol(self):
        r1 = _record(candidate=make_candidate(symbol="EURUSD", trace_id="t1"), trace_id="t1")
        r2 = _record(candidate=make_candidate(symbol="GBPUSD", trace_id="t2"), trace_id="t2")
        groups = attribution.group_by_pair([r1, r2])
        self.assertEqual(set(groups.keys()), {"EURUSD", "GBPUSD"})

    def test_falls_back_to_risk_decision_symbol_when_no_candidate(self):
        candidate = make_candidate()
        from tests.phantom_pipeline.analytics._fixtures import make_risk_decision, make_score_result

        score_result = make_score_result(candidate)
        risk_decision = make_risk_decision(candidate, score_result)
        r1 = _record(risk_decision=risk_decision, trace_id="t1")
        groups = attribution.group_by_pair([r1])
        self.assertIn(risk_decision.symbol, groups)


if __name__ == "__main__":
    unittest.main()
