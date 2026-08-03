# Plan: Knowledge & RAG Subsystem (`ADR-020`)

Status: Validated
Owner (Plan phase): AI Systems Engineer
Touched components: new `phantom_pipeline/knowledge` package, new
`docs/adr/ADR-020-knowledge-rag-subsystem.md`, only

---

## Research

- **Affected files and their dependencies**: none of the 14 existing
  `phantom_pipeline` packages are modified. A new 15th package,
  `phantom_pipeline/knowledge/`, is added.
- **Duplicate-logic check performed before writing anything**
  (`CLAUDE.md` §1.4):
  - `AnalyticsEngine.group_by_pair/session/regime` and
    `compute_performance_statistics` already exist —
    `KnowledgeEngine.generate_weekly_review` reads `ReportGenerator`'s
    already-computed `PeriodReport` directly, never a second grouping
    or statistics implementation.
  - `ComplianceEngineMetrics.blocks_by_check`/
    `ExecutionValidatorMetrics.blocks_by_check` already exist —
    "what rule blocks trades most often" reads `PeriodReport`'s
    already-attributed `compliance_blocks_by_check`/
    `execution_blocks_by_check`, never a third counting pass.
  - `TradeProvenanceRecord` already carries every field the task's
    "long-term trade memory" list names (entry/exit via
    `fill_reports`/`final_outcome`, pair via `candidate.symbol`/
    `risk_decision.symbol`, direction, session via
    `scanner_observation.session`, regime via
    `scanner_observation.phase`, strategy via `candidate.strategy_id`,
    score via `score_result`, risk/compliance/execution decisions
    verbatim, position management history via
    `position_management_decisions`, PnL/MAE/MFE via `final_outcome`) —
    `TradeMemoryRecord` is built by reading these fields, never
    re-deriving them.
  - No existing package generates a natural-language explanation of a
    decision, performs semantic search, or maintains a vector index —
    genuinely new ground, not a duplicate.
  - `paper_trading.validation_dashboard.ValidationDashboardSnapshot`
    already establishes the "additive read type, never touch
    `dashboard.models.ViewName`" precedent this package's
    `KnowledgeDashboardSnapshot` follows exactly.
- **Touched stages' ADR status**: no stage's ADR is touched. `ADR-001`
  through `ADR-019` are all Accepted and read-only inputs to this
  package's design. `ADR-020` (this change) is drafted and accepted
  per explicit, in-session user direction, the same acceptance path
  already used for `ADR-014`'s two amendments.
- **User-directed design decisions** (this session, explicit):
  1. Formal ADR required (not skipped like Phase 3-5's tooling) —
     `ADR-020` drafted and accepted.
  2. Explanations: deterministic templates from existing
     `reason_codes`/decision fields now; an LLM-backed "assistant mode"
     is explicitly deferred, never built in this change.
  3. Embeddings: a real neural embedding model is the intended
     production backend on the VPS; a deterministic offline method
     (feature hashing — chosen over TF-IDF for corpus-order
     independence, see below) is the default for tests/CI. Both share
     one `EmbeddingProvider` interface.
  4. Dashboard: a separate, additive `KnowledgeDashboardSnapshot` —
     `dashboard/` is not modified.
- **Embeddings implementation note**: the plan initially proposed
  TF-IDF; implemented as feature hashing (the "hashing trick") instead,
  because TF-IDF's vocabulary/IDF statistics change as the corpus grows
  (each new ingested document could change every previously-computed
  vector), which conflicts with "Incremental indexing" and
  "Automatic deduplication" both needing a *stable* vector per document
  over time. Feature hashing produces the same vector for the same text
  regardless of corpus size or ingestion order — a stronger determinism
  guarantee, and a legitimate, well-established embedding technique
  (used at scale in e.g. Vowpal Wabbit), not a downgrade.
- **`python3 scripts/check_architecture.py` result (baseline, before
  this change)**: PASS — 14 packages, no cycles, no private-state
  access.

## Plan

New package `phantom_pipeline/knowledge/`, 12 modules exactly as
specified: `models.py`, `embeddings.py`, `vector_store.py`,
`retriever.py`, `ingestion.py`, `memory.py`, `search.py`, `engine.py`,
`logging_sink.py`, `metrics.py`, `config.py`, `__init__.py`.

- `models.py`: `DocumentKind`, `KnowledgeDocument`, `EmbeddingVector`,
  `SearchQuery`, `SearchResult`, `TradeMemoryRecord`,
  `ResearchCategory`/`ResearchSuggestion`, `KnowledgeDashboardSnapshot`.
- `config.py`: `KnowledgeConfig` (embedding dimension, default `top_k`,
  dedup toggle, dashboard recent-insights count).
- `embeddings.py`: `EmbeddingProvider` protocol,
  `HashingEmbeddingProvider` (default, deterministic, no dependency),
  `SentenceTransformerEmbeddingProvider` (real option, lazy-imports
  `sentence-transformers`, injectable model for tests — mirrors
  `MT5Adapter`'s own lazy-import pattern).
- `vector_store.py`: `VectorStore` protocol, `InMemoryVectorStore`
  (real Phase 1 store, cosine similarity, metadata filtering).
- `memory.py`: `TradeMemoryStore` (add/get/all/find_by, dedup by
  `trace_id`).
- `ingestion.py`: markdown/document ingestion (content-hash dedup),
  `TradeProvenanceRecord` → `TradeMemoryRecord` (reads existing fields
  only), directory walk restricted to the named document set (`ADR-020`
  §2).
- `retriever.py`: embed query → `VectorStore.search` → resolve IDs to
  `KnowledgeDocument`/`TradeMemoryRecord` → ranked `SearchResult` tuple.
- `search.py`: `SemanticSearchService` — `search`, `find_winners`,
  `find_losers`, `find_similar_trades`, `find_by_setup_pattern` (reads
  `ScannerObservation.structure`/`liquidity_events` already-recorded
  kinds, e.g. `StructureKind.BOS`), `find_drawdowns_over` (reads
  already-recorded `TradeProvenanceRecord.account_snapshots`).
- `engine.py`: `KnowledgeEngine` — `ingest_document`, `record_trade`
  (deterministic explanation templates: approved/blocked/reduced/
  rejected/failed/trailing-stop-moved, each populated from the relevant
  decision's own `reason_codes`/`blocking_rules`/`blocking_reasons`/
  `decision_reason`), `generate_weekly_review` (wraps an already-built
  `PeriodReport`, adds rule-combination/expectancy ranking and a
  `ResearchSuggestion` list), `suggest_research` (rule-based heuristics
  over already-computed statistics only), `render_dashboard_snapshot`.
- `logging_sink.py`/`metrics.py`: standard per-package logging and a
  `KnowledgeMetrics` object, matching every existing package's own
  `*Metrics` `@property` pattern.

Tests: `tests/phantom_pipeline/knowledge/`, one file per module plus a
structural-boundary test, targeting 100+ tests total.

## Validation

`python3 -m compileall`, `python3 -m unittest discover -s
tests/phantom_pipeline`, `python3 validate.py`, `python3
scripts/check_architecture.py` (extended per `ADR-020` Hard Rule 9 to
also fail on any pipeline-stage → `knowledge` import) — all four must
stay green, package count rising from 14 to 15, zero diff against any
existing file.
