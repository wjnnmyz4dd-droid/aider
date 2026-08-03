"""Deterministic, read-only ranking (ADR-004 §7, §9, §13)."""

from __future__ import annotations

import unittest

from phantom_pipeline.scoring_engine.config import ScoringEngineConfig
from phantom_pipeline.scoring_engine.engine import ScoringEngine
from phantom_pipeline.scoring_engine.ranking import rank_scores
from phantom_pipeline.scoring_engine.registry import ScoringRuleRegistry
from tests.phantom_pipeline.scoring_engine._fixtures import make_candidate


class TestRankingDeterminism(unittest.TestCase):
    def setUp(self):
        registry = ScoringRuleRegistry()
        config = ScoringEngineConfig(
            enabled_rules={rid: True for rid in registry.registered_ids}
        )
        self.engine = ScoringEngine(registry, config)

    def test_ranking_orders_by_overall_score_descending(self):
        high = make_candidate(strategy_id="HIGH", trace_id="t-high", n_evidence=5, n_supporting=5, n_reason=5)
        low = make_candidate(strategy_id="LOW", trace_id="t-low", n_evidence=0, n_supporting=0, n_reason=0)

        results = self.engine.score_batch([low, high])
        ranked = rank_scores(results)

        self.assertEqual([r.strategy_id for r in ranked], ["HIGH", "LOW"])

    def test_ranking_is_deterministic_regardless_of_input_order(self):
        a = make_candidate(strategy_id="A", trace_id="t-a", n_evidence=2)
        b = make_candidate(strategy_id="B", trace_id="t-b", n_evidence=1)
        c = make_candidate(strategy_id="C", trace_id="t-c", n_evidence=3)

        results_forward = self.engine.score_batch([a, b, c])
        results_reversed = self.engine.score_batch([c, b, a])

        ranked_forward = rank_scores(results_forward)
        ranked_reversed = rank_scores(results_reversed)

        self.assertEqual(
            [r.candidate_id for r in ranked_forward], [r.candidate_id for r in ranked_reversed]
        )

    def test_tied_scores_break_deterministically_by_candidate_id(self):
        a = make_candidate(strategy_id="A", trace_id="t-tie")
        b = make_candidate(strategy_id="B", trace_id="t-tie")
        results = self.engine.score_batch([a, b])
        self.assertEqual(results[0].overall_score, results[1].overall_score)  # same inputs, tied

        ranked_forward = rank_scores(results)
        ranked_reversed = rank_scores(tuple(reversed(results)))

        self.assertEqual(
            [r.candidate_id for r in ranked_forward], [r.candidate_id for r in ranked_reversed]
        )
        self.assertEqual(
            [r.candidate_id for r in ranked_forward], sorted(r.candidate_id for r in results)
        )

    def test_ranking_never_mutates_the_input_sequence(self):
        a = make_candidate(strategy_id="A", trace_id="t-a", n_evidence=1)
        b = make_candidate(strategy_id="B", trace_id="t-b", n_evidence=5)
        results = self.engine.score_batch([a, b])
        original_order = list(results)

        rank_scores(results)

        self.assertEqual(list(results), original_order)

    def test_ranking_never_alters_any_score_result_field(self):
        a = make_candidate(strategy_id="A", trace_id="t-a", n_evidence=1)
        b = make_candidate(strategy_id="B", trace_id="t-b", n_evidence=5)
        results = self.engine.score_batch([a, b])

        ranked = rank_scores(results)

        for original in results:
            match = next(r for r in ranked if r.candidate_id == original.candidate_id)
            self.assertEqual(match, original)

    def test_ranking_produces_a_new_tuple_not_a_view(self):
        a = make_candidate(strategy_id="A", trace_id="t-a")
        results = self.engine.score_batch([a])
        ranked = rank_scores(results)
        self.assertIsNot(ranked, results)
        self.assertIsInstance(ranked, tuple)


if __name__ == "__main__":
    unittest.main()
