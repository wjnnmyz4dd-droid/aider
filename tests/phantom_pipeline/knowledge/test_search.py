"""SemanticSearchService tests — the example-question-shaped convenience
methods (ADR-020 §3)."""

from __future__ import annotations

import unittest

from phantom_pipeline.knowledge.embeddings import HashingEmbeddingProvider
from phantom_pipeline.knowledge.ingestion import KnowledgeDocumentStore
from phantom_pipeline.knowledge.memory import TradeMemoryStore
from phantom_pipeline.knowledge.models import TradeMemoryRecord
from phantom_pipeline.knowledge.retriever import Retriever
from phantom_pipeline.knowledge.search import SemanticSearchService, trade_to_text
from phantom_pipeline.knowledge.vector_store import InMemoryVectorStore
from phantom_pipeline.scanner.models import Direction

from tests.phantom_pipeline.knowledge._fixtures import T0


def _record(
    trace_id, symbol="EURUSD", session="LONDON", realized_pnl=50.0, why_happened="won because trend aligned BOS breakout",
) -> TradeMemoryRecord:
    return TradeMemoryRecord(
        schema_version=1, trace_id=trace_id, symbol=symbol, direction=Direction.UP,
        entry_price=1.1, exit_price=1.2, sessions=(session,), market_regime="MARKUP", strategy_id="ORB",
        score_total=75.0, risk_tier="NORMAL", compliance_verdict="APPROVE", execution_verdict="APPROVE",
        position_management_actions=(), realized_pnl=realized_pnl, mae=-10.0, mfe=60.0,
        why_trade_happened=why_happened, why_trade_skipped=None, rule_explanations=(),
        ai_explanation=why_happened, replay_link=None, collected_at=T0,
    )


def _build_service():
    embedding_provider = HashingEmbeddingProvider(dimension=64)
    vector_store = InMemoryVectorStore()
    document_store = KnowledgeDocumentStore()
    trade_memory_store = TradeMemoryStore()
    retriever = Retriever(embedding_provider, vector_store, document_store, trade_memory_store)
    service = SemanticSearchService(retriever, trade_memory_store)
    return service, trade_memory_store, embedding_provider, vector_store


def _index(trade_memory_store, vector_store, embedding_provider, record):
    trade_memory_store.add(record)
    vector_store.add(record.trace_id, embedding_provider.embed(trade_to_text(record)), metadata={"kind": "TRADE"})


class TestFindWinnersLosers(unittest.TestCase):
    def setUp(self):
        self.service, self.store, self.embed, self.vec = _build_service()
        _index(self.store, self.vec, self.embed, _record("t1", symbol="EURUSD", realized_pnl=50.0))
        _index(self.store, self.vec, self.embed, _record("t2", symbol="EURUSD", realized_pnl=-30.0))
        _index(self.store, self.vec, self.embed, _record("t3", symbol="GBPUSD", realized_pnl=20.0))

    def test_find_winners_all(self):
        winners = self.service.find_winners()
        self.assertEqual({r.trace_id for r in winners}, {"t1", "t3"})

    def test_find_winners_by_symbol(self):
        winners = self.service.find_winners(symbol="EURUSD")
        self.assertEqual({r.trace_id for r in winners}, {"t1"})

    def test_find_losers_all(self):
        losers = self.service.find_losers()
        self.assertEqual({r.trace_id for r in losers}, {"t2"})

    def test_find_losers_by_session(self):
        losers = self.service.find_losers(session="LONDON")
        self.assertEqual({r.trace_id for r in losers}, {"t2"})


class TestFindSimilarTrades(unittest.TestCase):
    def test_similar_trades_excludes_the_source_trade_itself(self):
        service, store, embed, vec = _build_service()
        _index(store, vec, embed, _record("t1", why_happened="won because trend aligned BOS breakout"))
        _index(store, vec, embed, _record("t2", why_happened="won because trend aligned BOS breakout"))

        similar = service.find_similar_trades("t1", top_k=5)

        self.assertNotIn("t1", {r.trace_id for r in similar})
        self.assertIn("t2", {r.trace_id for r in similar})

    def test_similar_trades_for_unknown_trace_id_returns_empty(self):
        service, _, _, _ = _build_service()
        self.assertEqual(service.find_similar_trades("nope"), ())


class TestFindBySetupPattern(unittest.TestCase):
    def test_matches_keyword_in_why_trade_happened(self):
        service, store, embed, vec = _build_service()
        _index(store, vec, embed, _record("t1", why_happened="entered on a liquidity sweep and BOS confirmation"))
        _index(store, vec, embed, _record("t2", why_happened="entered on a simple range reversal"))

        results = service.find_by_setup_pattern("liquidity sweep")

        self.assertEqual({r.trace_id for r in results}, {"t1"})

    def test_case_insensitive(self):
        service, store, embed, vec = _build_service()
        _index(store, vec, embed, _record("t1", why_happened="BOS confirmed entry"))

        results = service.find_by_setup_pattern("bos")

        self.assertEqual({r.trace_id for r in results}, {"t1"})

    def test_no_match_returns_empty(self):
        service, store, embed, vec = _build_service()
        _index(store, vec, embed, _record("t1", why_happened="simple trend entry"))

        self.assertEqual(service.find_by_setup_pattern("liquidity sweep"), ())


class TestFindDrawdownsOver(unittest.TestCase):
    def test_filters_by_injected_drawdown_accessor(self):
        service, store, embed, vec = _build_service()
        _index(store, vec, embed, _record("t1"))
        _index(store, vec, embed, _record("t2"))

        drawdowns = {"t1": 5.0, "t2": 1.0}
        results = service.find_drawdowns_over(3.0, lambda r: drawdowns.get(r.trace_id))

        self.assertEqual({r.trace_id for r in results}, {"t1"})

    def test_none_drawdown_never_matches(self):
        service, store, embed, vec = _build_service()
        _index(store, vec, embed, _record("t1"))

        results = service.find_drawdowns_over(0.0, lambda r: None)

        self.assertEqual(results, ())


if __name__ == "__main__":
    unittest.main()
