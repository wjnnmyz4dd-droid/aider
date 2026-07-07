"""Knowledge & RAG Subsystem (`ADR-020`).

**Not a 16th pipeline stage.** Exactly like the Watchdog (`ADR-011`) and
Dashboard (`ADR-012`), this package is a cross-cutting observer with no
position in the trading decision chain — it ingests already-produced,
immutable records after the fact and answers retrieval/explanation
questions about them. It holds no decision, execution, risk, compliance,
or scoring authority (`ADR-020` Hard Rules 1-2), and no pipeline-stage
package imports it (`scripts/check_architecture.py` enforces this).

See `docs/adr/ADR-020-knowledge-rag-subsystem.md` and
`docs/plans/knowledge-rag-subsystem.md` for the full research/plan
record.
"""

from __future__ import annotations

from .config import DEFAULT_CONFIG, KNOWLEDGE_VERSION, KnowledgeConfig
from .embeddings import EmbeddingProvider, HashingEmbeddingProvider, SentenceTransformerEmbeddingProvider
from .engine import ExplanationEngine, KnowledgeEngine
from .ingestion import (
    KNOWN_ROOT_DOCUMENTS,
    KnowledgeDocumentStore,
    build_statistical_risk_document,
    build_trade_memory_record,
    ingest_directory,
    ingest_markdown_file,
    ingest_repository_documents,
)
from .memory import TradeMemoryStore
from .metrics import KnowledgeMetrics
from .models import (
    SCHEMA_VERSION,
    DocumentKind,
    EmbeddingVector,
    KnowledgeDashboardSnapshot,
    KnowledgeDocument,
    ResearchCategory,
    ResearchSuggestion,
    SearchQuery,
    SearchResult,
    TradeMemoryRecord,
)
from .retriever import Retriever
from .search import SemanticSearchService, trade_to_text
from .vector_store import InMemoryVectorStore, VectorStore

__all__ = [
    "SCHEMA_VERSION",
    "KNOWLEDGE_VERSION",
    "KnowledgeConfig",
    "DEFAULT_CONFIG",
    "DocumentKind",
    "ResearchCategory",
    "KnowledgeDocument",
    "EmbeddingVector",
    "SearchQuery",
    "SearchResult",
    "TradeMemoryRecord",
    "ResearchSuggestion",
    "KnowledgeDashboardSnapshot",
    "EmbeddingProvider",
    "HashingEmbeddingProvider",
    "SentenceTransformerEmbeddingProvider",
    "VectorStore",
    "InMemoryVectorStore",
    "TradeMemoryStore",
    "KnowledgeDocumentStore",
    "KNOWN_ROOT_DOCUMENTS",
    "ingest_markdown_file",
    "ingest_directory",
    "ingest_repository_documents",
    "build_trade_memory_record",
    "build_statistical_risk_document",
    "Retriever",
    "SemanticSearchService",
    "trade_to_text",
    "ExplanationEngine",
    "KnowledgeEngine",
    "KnowledgeMetrics",
]
