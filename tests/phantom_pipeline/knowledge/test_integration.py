"""End-to-end Knowledge & RAG integration tests: documentation indexing,
trade indexing, vector retrieval accuracy, replay determinism across two
independent engines, and a bounded performance check (ADR-020 §4)."""

from __future__ import annotations

import os
import time
import unittest

from phantom_pipeline.knowledge.engine import KnowledgeEngine
from phantom_pipeline.knowledge.ingestion import ingest_repository_documents
from phantom_pipeline.knowledge.models import DocumentKind

from tests.phantom_pipeline.knowledge._fixtures import T0, make_trade_provenance_record

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


class TestDocumentationIndexingEndToEnd(unittest.TestCase):
    def test_repository_documents_are_ingestible_and_searchable(self):
        engine = KnowledgeEngine()
        documents = ingest_repository_documents(REPO_ROOT, T0)
        self.assertGreater(len(documents), 5)

        added = engine.ingest_documents(documents)
        self.assertEqual(added, len(documents))
        self.assertEqual(engine.metrics.documents_indexed_count, len(documents))

        results = engine.search("watchdog recovery", top_k=5)
        self.assertGreater(len(results), 0)

    def test_re_ingesting_the_same_documents_is_fully_deduplicated(self):
        engine = KnowledgeEngine()
        documents = ingest_repository_documents(REPO_ROOT, T0)
        engine.ingest_documents(documents)

        added_again = engine.ingest_documents(documents)

        self.assertEqual(added_again, 0)
        self.assertEqual(engine.metrics.duplicate_documents_skipped_count, len(documents))


class TestTradeIndexingEndToEnd(unittest.TestCase):
    def test_many_trades_are_all_indexed_and_individually_retrievable(self):
        engine = KnowledgeEngine()
        for i in range(20):
            record = make_trade_provenance_record(f"trace-{i}", executed=(i % 2 == 0), realized_pnl=float(i))
            engine.record_trade(record, T0)

        self.assertEqual(engine.metrics.trades_indexed_count, 20)
        self.assertEqual(engine.trade_memory.count, 20)
        for i in range(20):
            self.assertIsNotNone(engine.trade_memory.get(f"trace-{i}"))


class TestVectorRetrievalAccuracy(unittest.TestCase):
    def test_query_matching_a_specific_trades_language_ranks_it_first(self):
        engine = KnowledgeEngine()
        engine.record_trade(make_trade_provenance_record("distinct-eurusd", executed=True), T0)
        # A second, differently-worded record to make ranking meaningful.
        other = make_trade_provenance_record("other-gbpusd", executed=False)
        engine.record_trade(other, T0)

        target = engine.trade_memory.get("distinct-eurusd")
        results = engine.search(target.why_trade_happened, top_k=2)

        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0].trade.trace_id, "distinct-eurusd")


class TestReplayDeterminism(unittest.TestCase):
    def test_two_independent_engines_produce_identical_trade_memory_for_identical_input(self):
        engine_a = KnowledgeEngine()
        engine_b = KnowledgeEngine()
        record = make_trade_provenance_record("trace-replay", executed=True)

        memory_a = engine_a.record_trade(record, T0)
        memory_b = engine_b.record_trade(record, T0)

        self.assertEqual(memory_a, memory_b)

    def test_two_independent_engines_produce_identical_search_ranking(self):
        engine_a = KnowledgeEngine()
        engine_b = KnowledgeEngine()
        for i in range(5):
            record = make_trade_provenance_record(f"trace-{i}", executed=True, realized_pnl=float(i))
            engine_a.record_trade(record, T0)
            engine_b.record_trade(record, T0)

        query = "won because trend aligned"
        results_a = engine_a.search(query, top_k=5)
        results_b = engine_b.search(query, top_k=5)

        self.assertEqual([r.document_id for r in results_a], [r.document_id for r in results_b])
        self.assertEqual([round(r.score, 9) for r in results_a], [round(r.score, 9) for r in results_b])


class TestBoundedPerformance(unittest.TestCase):
    def test_indexing_and_searching_200_trades_completes_quickly(self):
        engine = KnowledgeEngine()
        start = time.monotonic()
        for i in range(200):
            record = make_trade_provenance_record(f"perf-{i}", executed=(i % 2 == 0), realized_pnl=float(i))
            engine.record_trade(record, T0)
        engine.search("won because trend aligned", top_k=10)
        elapsed = time.monotonic() - start

        self.assertEqual(engine.trade_memory.count, 200)
        self.assertLess(elapsed, 10.0, "indexing + search of 200 trades should stay well under 10s")


if __name__ == "__main__":
    unittest.main()
