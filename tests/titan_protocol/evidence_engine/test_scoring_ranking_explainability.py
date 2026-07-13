"""Unit tests for component scoring, composite evidence scoring,
ranking, and explainability."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from titan_protocol.evidence_engine.explainability import build_evidence_report
from titan_protocol.evidence_engine.models import (
    ComponentScore,
    EvidenceScore,
    LiquidityResult,
    MarketStructureResult,
    SessionName,
    SessionState,
    TrendClassification,
    VolatilityState,
)
from titan_protocol.evidence_engine.ranking import rank_pairs
from titan_protocol.evidence_engine.scoring import (
    compute_component_scores,
    compute_evidence_score,
    score_indicators,
    score_session,
    score_trend,
    score_volatility,
)
from tests.titan_protocol.evidence_engine._fixtures import make_config

T0 = datetime(2026, 7, 10, tzinfo=timezone.utc)


class TestComponentScores(unittest.TestCase):
    def test_every_component_score_carries_reason_weight_confidence(self):
        config = make_config()
        structure = MarketStructureResult((), (), TrendClassification.RANGE, (), ())
        liquidity = LiquidityResult((), ())
        volatility = VolatilityState(atr=0.01, is_expansion=False, is_compression=False, volatility_score=50.0)
        session = SessionState(SessionName.LONDON, 80.0)
        components = compute_component_scores(structure, liquidity, (), TrendClassification.RANGE, volatility, session, config)
        self.assertEqual(len(components), 7)
        for c in components:
            self.assertTrue(c.reason)
            self.assertTrue(0.0 <= c.weight <= 1.0)
            self.assertTrue(0.0 <= c.confidence <= 1.0)
            self.assertTrue(0.0 <= c.value <= 100.0)

    def test_trend_score_map_covers_every_classification(self):
        config = make_config()
        for trend in TrendClassification:
            score = score_trend(trend, config)
            self.assertTrue(0.0 <= score.value <= 100.0)

    def test_indicator_score_is_low_confidence_placeholder(self):
        score = score_indicators(make_config())
        self.assertEqual(score.value, 50.0)
        self.assertLess(score.confidence, 0.5)

    def test_session_score_matches_input_quality(self):
        config = make_config()
        state = SessionState(SessionName.LONDON_NEW_YORK_OVERLAP, 100.0)
        score = score_session(state, config)
        self.assertEqual(score.value, 100.0)


class TestCompositeEvidenceScore(unittest.TestCase):
    def test_composite_is_exact_weighted_sum(self):
        config = make_config()
        structure = MarketStructureResult((), (), TrendClassification.RANGE, (), ())
        liquidity = LiquidityResult((), ())
        volatility = VolatilityState(atr=0.01, is_expansion=False, is_compression=False, volatility_score=50.0)
        session = SessionState(SessionName.LONDON, 80.0)
        components = compute_component_scores(structure, liquidity, (), TrendClassification.RANGE, volatility, session, config)
        evidence = compute_evidence_score(components)
        expected = sum(c.value * c.weight for c in components)
        self.assertAlmostEqual(evidence.composite, expected)
        self.assertTrue(0.0 <= evidence.composite <= 100.0)

    def test_composite_bounded_even_with_extreme_component_values(self):
        components = (
            ComponentScore("a", 100.0, 0.5, 1.0, "max"),
            ComponentScore("b", 0.0, 0.5, 1.0, "min"),
        )
        evidence = compute_evidence_score(components)
        self.assertTrue(0.0 <= evidence.composite <= 100.0)


class TestRanking(unittest.TestCase):
    def _report(self, symbol, composite):
        components = (ComponentScore("x", composite, 1.0, 0.5, "r"),)
        return build_evidence_report(symbol, T0, EvidenceScore(composite, components))

    def test_highest_score_ranked_first(self):
        reports = [self._report("EURUSD", 40.0), self._report("GBPUSD", 90.0), self._report("USDJPY", 60.0)]
        ranking = rank_pairs(reports)
        self.assertEqual([r.symbol for r in ranking], ["GBPUSD", "USDJPY", "EURUSD"])
        self.assertEqual([r.rank for r in ranking], [1, 2, 3])

    def test_ties_broken_alphabetically_for_determinism(self):
        reports = [self._report("ZARUSD", 50.0), self._report("AUDUSD", 50.0)]
        ranking = rank_pairs(reports)
        self.assertEqual([r.symbol for r in ranking], ["AUDUSD", "ZARUSD"])

    def test_empty_input_produces_empty_ranking(self):
        self.assertEqual(rank_pairs([]), ())


class TestExplainability(unittest.TestCase):
    def test_strengths_and_weaknesses_partition_by_threshold(self):
        components = (
            ComponentScore("strong", 85.0, 0.5, 0.9, "well above threshold"),
            ComponentScore("weak", 10.0, 0.5, 0.4, "well below threshold"),
        )
        report = build_evidence_report("EURUSD", T0, EvidenceScore(47.5, components))
        self.assertEqual(len(report.strengths), 1)
        self.assertIn("strong", report.strengths[0])
        self.assertEqual(len(report.weaknesses), 1)
        self.assertIn("weak", report.weaknesses[0])

    def test_confidence_explanation_names_the_weakest_component(self):
        components = (
            ComponentScore("solid", 60.0, 0.5, 0.9, "high confidence"),
            ComponentScore("shaky", 60.0, 0.5, 0.2, "low confidence"),
        )
        report = build_evidence_report("EURUSD", T0, EvidenceScore(60.0, components))
        self.assertIn("shaky", report.confidence_explanation)

    def test_report_symbol_and_timestamp_preserved(self):
        components = (ComponentScore("x", 50.0, 1.0, 0.5, "r"),)
        report = build_evidence_report("EURUSD", T0, EvidenceScore(50.0, components))
        self.assertEqual(report.symbol, "EURUSD")
        self.assertEqual(report.generated_at, T0)


if __name__ == "__main__":
    unittest.main()
