"""Unit tests for the 6-step deterministic selection cascade."""

from __future__ import annotations

import unittest

from phantom.strategy_engine.models import QualificationResult, QualificationStatus, StrategyId
from phantom.strategy_engine.selection import select_winning_strategy
from tests.phantom.strategy_engine._fixtures import make_config, make_evidence_snapshot, make_mi_snapshot


def _result(strategy_id, status=QualificationStatus.QUALIFIED, score=50.0, confidence=0.5, reason="r"):
    return QualificationResult(
        strategy_id=strategy_id, pair="EURUSD", status=status, score=score,
        confidence=confidence, reason=reason, strengths=(), weaknesses=(),
    )


class TestSelectionStep1Score(unittest.TestCase):
    def test_highest_score_wins_outright(self):
        qualifications = [
            _result(StrategyId.TREND_CONTINUATION, score=80.0),
            _result(StrategyId.SESSION_BREAKOUT, score=60.0),
        ]
        winner = select_winning_strategy(qualifications, make_evidence_snapshot(), make_mi_snapshot(), make_config())
        self.assertEqual(winner.strategy_id, StrategyId.TREND_CONTINUATION)

    def test_no_qualified_candidates_returns_none(self):
        qualifications = [_result(StrategyId.TREND_CONTINUATION, status=QualificationStatus.NOT_QUALIFIED, score=0.0)]
        winner = select_winning_strategy(qualifications, make_evidence_snapshot(), make_mi_snapshot(), make_config())
        self.assertIsNone(winner)

    def test_not_eligible_never_competes(self):
        qualifications = [_result(StrategyId.TREND_CONTINUATION, status=QualificationStatus.NOT_ELIGIBLE, score=0.0)]
        winner = select_winning_strategy(qualifications, make_evidence_snapshot(), make_mi_snapshot(), make_config())
        self.assertIsNone(winner)


class TestSelectionStep2Confidence(unittest.TestCase):
    def test_tied_score_broken_by_confidence(self):
        qualifications = [
            _result(StrategyId.TREND_CONTINUATION, score=70.0, confidence=0.9),
            _result(StrategyId.SESSION_BREAKOUT, score=70.0, confidence=0.4),
        ]
        winner = select_winning_strategy(qualifications, make_evidence_snapshot(), make_mi_snapshot(), make_config())
        self.assertEqual(winner.strategy_id, StrategyId.TREND_CONTINUATION)


class TestSelectionFinalTieRejects(unittest.TestCase):
    def test_full_tie_through_every_step_rejects(self):
        # Identical score and confidence, same pair (so liquidity/news
        # are identical too) -- must reject, never pick arbitrarily.
        qualifications = [
            _result(StrategyId.TREND_CONTINUATION, score=70.0, confidence=0.8),
            _result(StrategyId.SESSION_BREAKOUT, score=70.0, confidence=0.8),
        ]
        winner = select_winning_strategy(qualifications, make_evidence_snapshot(), make_mi_snapshot(), make_config())
        self.assertIsNone(winner)

    def test_result_is_deterministic_across_repeated_calls(self):
        qualifications = [
            _result(StrategyId.TREND_CONTINUATION, score=70.0, confidence=0.8),
            _result(StrategyId.SESSION_BREAKOUT, score=70.0, confidence=0.8),
        ]
        evidence = make_evidence_snapshot()
        mi = make_mi_snapshot()
        config = make_config()
        results = [select_winning_strategy(qualifications, evidence, mi, config) for _ in range(20)]
        self.assertTrue(all(r is None for r in results))


class TestSelectionWithinTolerance(unittest.TestCase):
    def test_scores_within_tolerance_are_treated_as_tied(self):
        config = make_config(score_tie_tolerance=1.0)
        qualifications = [
            _result(StrategyId.TREND_CONTINUATION, score=70.0, confidence=0.8),
            _result(StrategyId.SESSION_BREAKOUT, score=70.5, confidence=0.8),
        ]
        winner = select_winning_strategy(qualifications, make_evidence_snapshot(), make_mi_snapshot(), config)
        self.assertIsNone(winner)  # both survive step 1, tie again at step 2

    def test_scores_outside_tolerance_are_not_tied(self):
        config = make_config(score_tie_tolerance=0.1)
        qualifications = [
            _result(StrategyId.TREND_CONTINUATION, score=70.0, confidence=0.8),
            _result(StrategyId.SESSION_BREAKOUT, score=71.0, confidence=0.8),
        ]
        winner = select_winning_strategy(qualifications, make_evidence_snapshot(), make_mi_snapshot(), config)
        self.assertEqual(winner.strategy_id, StrategyId.SESSION_BREAKOUT)


if __name__ == "__main__":
    unittest.main()
