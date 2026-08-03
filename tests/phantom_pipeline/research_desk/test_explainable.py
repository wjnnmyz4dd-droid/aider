"""ExplainableDecisionEngine tests — delegates existing Q&A shapes to
knowledge.SemanticSearchService (reused, not duplicated), and the new
compare_periods/what_changed_over methods (ADR-021 item 8)."""

from __future__ import annotations

import unittest

from phantom_pipeline.knowledge.embeddings import HashingEmbeddingProvider
from phantom_pipeline.knowledge.ingestion import KnowledgeDocumentStore
from phantom_pipeline.knowledge.memory import TradeMemoryStore
from phantom_pipeline.knowledge.retriever import Retriever
from phantom_pipeline.knowledge.search import SemanticSearchService
from phantom_pipeline.research_desk.explainable import ExplainableDecisionEngine

from tests.phantom_pipeline.research_desk._fixtures import NOW, make_forward_test_report, make_period_report


def _build_search_service():
    embedding_provider = HashingEmbeddingProvider(dimension=32)
    from phantom_pipeline.knowledge.vector_store import InMemoryVectorStore

    retriever = Retriever(embedding_provider, InMemoryVectorStore(), KnowledgeDocumentStore(), TradeMemoryStore())
    return SemanticSearchService(retriever, TradeMemoryStore())


class TestAskDelegatesToSemanticSearchService(unittest.TestCase):
    def test_ask_returns_empty_tuple_on_empty_index(self):
        engine = ExplainableDecisionEngine(_build_search_service())
        results = engine.ask("why didn't EURUSD trade today?")
        self.assertEqual(results, ())

    def test_ask_respects_top_k(self):
        engine = ExplainableDecisionEngine(_build_search_service())
        results = engine.ask("show every trade rejected by compliance", top_k=3)
        self.assertLessEqual(len(results), 3)


class TestComparePeriods(unittest.TestCase):
    def test_positive_deltas_reported_for_improvement(self):
        better_ftr = make_forward_test_report()
        worse_period = make_period_report(forward_test_report=make_forward_test_report())
        better_period = make_period_report(forward_test_report=better_ftr)

        engine = ExplainableDecisionEngine(_build_search_service())
        comparison = engine.compare_periods("c1", "last month", worse_period, "this month", better_period, NOW)

        self.assertIn("win_rate", comparison.metric_deltas)
        self.assertEqual(comparison.metric_deltas["win_rate"], 0.0)  # identical fixtures -> zero delta

    def test_narrative_names_both_periods(self):
        period = make_period_report()
        engine = ExplainableDecisionEngine(_build_search_service())
        comparison = engine.compare_periods("c1", "last month", period, "this month", period, NOW)
        self.assertIn("last month", comparison.narrative)
        self.assertIn("this month", comparison.narrative)

    def test_mutating_one_comparisons_deltas_never_affects_a_second_call(self):
        period = make_period_report()
        engine = ExplainableDecisionEngine(_build_search_service())
        comparison_a = engine.compare_periods("c1", "a", period, "b", period, NOW)
        comparison_a.metric_deltas["win_rate"] = 999.0

        comparison_b = engine.compare_periods("c1", "a", period, "b", period, NOW)
        self.assertEqual(comparison_b.metric_deltas["win_rate"], 0.0)


class TestWhatChangedOver(unittest.TestCase):
    def test_narrative_mentions_day_count(self):
        period = make_period_report()
        engine = ExplainableDecisionEngine(_build_search_service())
        comparison = engine.what_changed_over("c1", 90, period, period, NOW)
        self.assertIn("90 days", comparison.narrative)


if __name__ == "__main__":
    unittest.main()
