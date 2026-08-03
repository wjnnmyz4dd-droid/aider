"""Tests for `select_winner()` (ADR-037 §6): score-alone ranking,
`<=`-inclusive tie tolerance, reject-on-tie -- a pure function, no
persistence, no side effects."""

from __future__ import annotations

import unittest

from titan_protocol.opportunity_selection_engine.models import OpportunityCandidate
from titan_protocol.opportunity_selection_engine.selection import select_winner
from titan_protocol.strategy_engine.models import TradeIntent


def _candidate(pair: str, score: float) -> OpportunityCandidate:
    return OpportunityCandidate(pair=pair, score=score, trade_intent=TradeIntent.BUY)


class TestEmptyCandidates(unittest.TestCase):
    def test_zero_candidates_produces_no_winner(self):
        outcome = select_winner((), tie_tolerance=0.5)
        self.assertIsNone(outcome.winner)
        self.assertEqual(outcome.reason, "no candidates")


class TestScoreAloneRanking(unittest.TestCase):
    def test_single_candidate_always_wins(self):
        outcome = select_winner((_candidate("EURUSD", 50.0),), tie_tolerance=0.5)
        self.assertEqual(outcome.winner, "EURUSD")

    def test_highest_score_wins_when_clear_of_tolerance(self):
        candidates = (_candidate("EURUSD", 80.0), _candidate("GBPUSD", 70.0))
        outcome = select_winner(candidates, tie_tolerance=0.5)
        self.assertEqual(outcome.winner, "EURUSD")

    def test_never_uses_confidence_liquidity_or_any_other_field(self):
        """`OpportunityCandidate` carries only `pair`/`score`/`trade_intent`
        -- there is no secondary criterion available to consult even by
        accident."""
        fields = {f.name for f in __import__("dataclasses").fields(OpportunityCandidate)}
        self.assertEqual(fields, {"pair", "score", "trade_intent"})


class TestTieToleranceBoundary(unittest.TestCase):
    def test_difference_exactly_at_tolerance_is_a_tie_inclusive_le(self):
        candidates = (_candidate("EURUSD", 80.0), _candidate("GBPUSD", 79.5))
        outcome = select_winner(candidates, tie_tolerance=0.5)
        self.assertIsNone(outcome.winner)
        self.assertEqual(outcome.reason, "tie within tolerance")

    def test_difference_just_above_tolerance_is_not_a_tie(self):
        candidates = (_candidate("EURUSD", 80.0), _candidate("GBPUSD", 79.49))
        outcome = select_winner(candidates, tie_tolerance=0.5)
        self.assertEqual(outcome.winner, "EURUSD")

    def test_three_way_tie_within_tolerance_produces_no_winner(self):
        candidates = (_candidate("EURUSD", 80.0), _candidate("GBPUSD", 79.7), _candidate("USDJPY", 79.6))
        outcome = select_winner(candidates, tie_tolerance=0.5)
        self.assertIsNone(outcome.winner)

    def test_zero_tolerance_requires_exact_equality_to_tie(self):
        candidates = (_candidate("EURUSD", 80.0), _candidate("GBPUSD", 80.0))
        outcome = select_winner(candidates, tie_tolerance=0.0)
        self.assertIsNone(outcome.winner)

    def test_zero_tolerance_with_distinct_scores_has_a_clear_winner(self):
        candidates = (_candidate("EURUSD", 80.0), _candidate("GBPUSD", 79.999999))
        outcome = select_winner(candidates, tie_tolerance=0.0)
        self.assertEqual(outcome.winner, "EURUSD")


if __name__ == "__main__":
    unittest.main()
