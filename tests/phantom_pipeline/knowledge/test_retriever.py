"""Retriever tests — embed-search-resolve pipeline, ranked results,
document vs. trade resolution (ADR-020 §3)."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from phantom_pipeline.knowledge.embeddings import HashingEmbeddingProvider
from phantom_pipeline.knowledge.ingestion import KnowledgeDocumentStore
from phantom_pipeline.knowledge.memory import TradeMemoryStore
from phantom_pipeline.knowledge.models import DocumentKind, KnowledgeDocument, SearchQuery
from phantom_pipeline.knowledge.retriever import Retriever
from phantom_pipeline.knowledge.vector_store import InMemoryVectorStore
from phantom_pipeline.scanner.models import Direction

from tests.phantom_pipeline.knowledge._fixtures import T0


def _doc(document_id: str, content: str) -> KnowledgeDocument:
    return KnowledgeDocument(
        schema_version=1, document_id=document_id, kind=DocumentKind.ADR, title=document_id,
        content=content, source_path=None, content_hash="h", metadata={}, ingested_at=T0,
    )


class TestRetrieverDocuments(unittest.TestCase):
    def setUp(self):
        self.embedding_provider = HashingEmbeddingProvider(dimension=64)
        self.vector_store = InMemoryVectorStore()
        self.document_store = KnowledgeDocumentStore()
        self.retriever = Retriever(self.embedding_provider, self.vector_store, self.document_store)

        for document_id, content in [("d1", "risk engine capital preservation"), ("d2", "compliance blocked news window")]:
            document = _doc(document_id, content)
            self.document_store.add(document)
            self.vector_store.add(document_id, self.embedding_provider.embed(content))

    def test_retrieve_returns_ranked_search_results_with_resolved_document(self):
        results = self.retriever.retrieve(SearchQuery(text="risk engine capital preservation", top_k=2))

        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0].rank, 1)
        self.assertIsNotNone(results[0].document)
        self.assertEqual(results[0].document.document_id, "d1")

    def test_result_ranks_are_sequential(self):
        results = self.retriever.retrieve(SearchQuery(text="risk engine capital preservation", top_k=2))
        self.assertEqual([r.rank for r in results], list(range(1, len(results) + 1)))


class TestRetrieverTrades(unittest.TestCase):
    def test_falls_back_to_trade_memory_store_when_not_a_document(self):
        embedding_provider = HashingEmbeddingProvider(dimension=32)
        vector_store = InMemoryVectorStore()
        document_store = KnowledgeDocumentStore()
        trade_memory_store = TradeMemoryStore()

        from phantom_pipeline.knowledge.models import TradeMemoryRecord

        record = TradeMemoryRecord(
            schema_version=1, trace_id="t1", symbol="EURUSD", direction=Direction.UP,
            entry_price=1.1, exit_price=1.2, sessions=("LONDON",), market_regime="MARKUP",
            strategy_id="ORB", score_total=75.0, risk_tier="NORMAL", compliance_verdict="APPROVE",
            execution_verdict="APPROVE", position_management_actions=(), realized_pnl=50.0,
            mae=-10.0, mfe=60.0, why_trade_happened="won because trend aligned", why_trade_skipped=None,
            rule_explanations=(), ai_explanation="won because trend aligned", replay_link=None, collected_at=T0,
        )
        trade_memory_store.add(record)
        vector_store.add("t1", embedding_provider.embed("won because trend aligned EURUSD"))

        retriever = Retriever(embedding_provider, vector_store, document_store, trade_memory_store)
        results = retriever.retrieve(SearchQuery(text="won because trend aligned EURUSD", top_k=1))

        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0].document)
        self.assertIsNotNone(results[0].trade)
        self.assertEqual(results[0].trade.trace_id, "t1")


if __name__ == "__main__":
    unittest.main()
