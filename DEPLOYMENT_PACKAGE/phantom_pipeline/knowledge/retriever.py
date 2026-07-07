"""Retriever for the Knowledge & RAG subsystem (`ADR-020` §3) — embeds a
query, searches the vector store, and resolves each hit's `document_id`
back to a full `KnowledgeDocument` or `TradeMemoryRecord`. Holds no
storage of its own; every collaborator is injected, matching the
dependency-injection shape used throughout `phantom_pipeline`.
"""

from __future__ import annotations

from typing import Optional, Tuple

from .embeddings import EmbeddingProvider
from .ingestion import KnowledgeDocumentStore
from .memory import TradeMemoryStore
from .models import SearchQuery, SearchResult
from .vector_store import VectorStore


class Retriever:
    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        vector_store: VectorStore,
        document_store: KnowledgeDocumentStore,
        trade_memory_store: Optional[TradeMemoryStore] = None,
    ) -> None:
        self._embedding_provider = embedding_provider
        self._vector_store = vector_store
        self._document_store = document_store
        self._trade_memory_store = trade_memory_store

    def retrieve(self, query: SearchQuery) -> Tuple[SearchResult, ...]:
        query_vector = self._embedding_provider.embed(query.text)
        matches = self._vector_store.search(query_vector, top_k=query.top_k, filters=query.filters)

        results = []
        for rank, (document_id, score) in enumerate(matches, start=1):
            document = self._document_store.get(document_id)
            trade = None
            if document is None and self._trade_memory_store is not None:
                trade = self._trade_memory_store.get(document_id)
            results.append(SearchResult(document_id=document_id, score=score, rank=rank, document=document, trade=trade))
        return tuple(results)


__all__ = ["Retriever"]
