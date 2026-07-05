"""ScoreResult/ScoringFailureRecord/CandidateTrade immutability (ADR-004
§6)."""

from __future__ import annotations

import dataclasses
import unittest

from phantom_pipeline.scoring_engine.models import (
    FactorBreakdown,
    RuleContribution,
    RuleOutcome,
    ScoreResult,
    ScoringEvidence,
    ScoringFailureRecord,
)
from phantom_pipeline.scoring_engine.engine import ScoringEngine
from phantom_pipeline.scoring_engine.registry import ScoringRuleRegistry
from tests.phantom_pipeline.scoring_engine._fixtures import (
    T0,
    AlwaysAbstainsRule,
    FlatPointsRule,
    enabled_config,
    make_candidate,
)


def _score_result() -> ScoreResult:
    registry = ScoringRuleRegistry(rule_classes=[FlatPointsRule])
    engine = ScoringEngine(registry, enabled_config("TEST_FLAT"))
    result = engine.score(make_candidate())
    assert isinstance(result, ScoreResult)
    return result


class TestScoreResultImmutability(unittest.TestCase):
    def test_top_level_fields_cannot_be_reassigned(self):
        result = _score_result()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.overall_score = 999.0  # type: ignore[misc]

    def test_tuple_fields_are_coerced_to_tuples(self):
        result = ScoreResult(
            schema_version=1,
            trace_id="t",
            candidate_id="c",
            strategy_id="S",
            symbol="EURUSD",
            timeframe="M1",
            timestamp=T0,
            overall_score=1.0,
            factor_breakdown=[FactorBreakdown("f", 1.0, ["R1"])],
            rule_contributions=[
                RuleContribution("R1", "1.0.0", RuleOutcome.FIRED, 1.0, 1.0, [], "d")
            ],
            confidence_rationale="r",
            scoring_version="v",
        )
        self.assertIsInstance(result.factor_breakdown, tuple)
        self.assertIsInstance(result.rule_contributions, tuple)

    def test_trace_id_and_candidate_id_preserve_upstream_lineage(self):
        candidate = make_candidate()
        registry = ScoringRuleRegistry(rule_classes=[FlatPointsRule])
        engine = ScoringEngine(registry, enabled_config("TEST_FLAT"))
        result = engine.score(candidate)
        self.assertEqual(result.trace_id, candidate.trace_id)
        self.assertEqual(result.candidate_id, candidate.candidate_id)


class TestRuleContributionImmutability(unittest.TestCase):
    def test_frozen(self):
        contribution = RuleContribution("R1", "1.0.0", RuleOutcome.FIRED, 1.0, 1.0, (), "d")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            contribution.points = 5.0  # type: ignore[misc]

    def test_evidence_coerced_to_tuple(self):
        contribution = RuleContribution(
            "R1", "1.0.0", RuleOutcome.FIRED, 1.0, 1.0, [ScoringEvidence("f", "d")], "d"
        )
        self.assertIsInstance(contribution.evidence, tuple)


class TestFactorBreakdownImmutability(unittest.TestCase):
    def test_frozen(self):
        breakdown = FactorBreakdown("f", 1.0, ("R1",))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            breakdown.subtotal = 999.0  # type: ignore[misc]

    def test_rule_ids_coerced_to_tuple(self):
        breakdown = FactorBreakdown("f", 1.0, ["R1", "R2"])
        self.assertIsInstance(breakdown.rule_ids, tuple)


class TestScoringFailureRecordImmutability(unittest.TestCase):
    def test_frozen(self):
        record = ScoringFailureRecord(1, "t", "c", "S", "reason", "v")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            record.reason = "other"  # type: ignore[misc]


class TestCandidateTradeStillImmutableAtScoringBoundary(unittest.TestCase):
    def test_scoring_never_mutates_the_candidate(self):
        candidate = make_candidate()
        registry = ScoringRuleRegistry(rule_classes=[FlatPointsRule, AlwaysAbstainsRule])
        engine = ScoringEngine(registry, enabled_config("TEST_FLAT", "TEST_ABSTAINS"))

        before = candidate
        engine.score(candidate)
        self.assertEqual(candidate, before)

        with self.assertRaises(dataclasses.FrozenInstanceError):
            candidate.direction = None  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
