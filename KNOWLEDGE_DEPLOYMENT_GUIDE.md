# Knowledge & RAG Subsystem — Deployment Guide

**Status: DEPRECATED.** Written for the pre-Titan-Protocol
`phantom_pipeline/knowledge/` package. The current Titan Protocol Windows
release (`deployment_windows/`) does not wire the Knowledge/RAG or
Research Desk subsystems into its live runtime, so this guide does not
describe anything reachable from a current deployment. Kept for
historical reference only.

How to wire `phantom_pipeline/knowledge/` (`ADR-020`) into a running
deployment. This subsystem is read-only intelligence — it never affects
trading behavior; nothing in this guide changes anything described in
`LIVE_DEPLOYMENT_GUIDE.md`, `START_PHANTOM.md`, or `OPERATOR_CHECKLIST.md`.

## 1. Construct a `KnowledgeEngine`

```python
from phantom_pipeline.knowledge import KnowledgeEngine

knowledge_engine = KnowledgeEngine()  # HashingEmbeddingProvider + InMemoryVectorStore by default
```

For a VPS deployment that wants higher-quality semantic search, inject a
real embedding provider instead (requires `pip install
sentence-transformers`, an optional dependency — never required for this
package to import or for its tests to pass):

```python
from phantom_pipeline.knowledge import KnowledgeEngine, SentenceTransformerEmbeddingProvider

knowledge_engine = KnowledgeEngine(
    embedding_provider=SentenceTransformerEmbeddingProvider(model_name="all-MiniLM-L6-v2")
)
```

## 2. Prime it from repository documentation (one-time, or on a schedule)

```python
from datetime import datetime, timezone
from phantom_pipeline.knowledge import ingest_repository_documents

now = datetime.now(timezone.utc)
documents = ingest_repository_documents(repo_root=".", now=now)
knowledge_engine.ingest_documents(documents)
```

Safe to re-run on a schedule (e.g. after every deployment) — content-hash
deduplication means unchanged files are a no-op and only genuinely
changed/new files are (re-)indexed (`ADR-020` §2).

## 3. Record each completed trade

Call this once per `trace_id` after `PipelineOrchestrator.analytics`
has built a `TradeProvenanceRecord` — the same object
`paper_trading`/`dashboard` already read, never a new one:

```python
record = orchestrator.analytics.build_provenance_record(trace_id, now)
if record is not None:
    knowledge_engine.record_trade(record, now, replay_link=f"/replay/{trace_id}")
```

This never affects `record` itself, and never touches any pipeline
stage — it is a pure, additive read (`ADR-020` Hard Rules 1-2).

## 4. Search

```python
results = knowledge_engine.search("show every EURUSD winner")
for result in results:
    if result.trade is not None:
        print(result.trade.trace_id, result.trade.realized_pnl)

# Or the example-question-shaped convenience API:
winners = knowledge_engine.search_service.find_winners(symbol="EURUSD")
losers = knowledge_engine.search_service.find_losers(session="LONDON")
similar = knowledge_engine.search_service.find_similar_trades(trace_id, top_k=5)
bos_setups = knowledge_engine.search_service.find_by_setup_pattern("BOS")
```

## 5. Weekly review + research suggestions

Reuses `paper_trading.ReportGenerator`'s already-computed `PeriodReport`
— never a second statistics implementation:

```python
period_report = report_generator.generate_weekly(records, now)
period_report, suggestions = knowledge_engine.generate_weekly_review(period_report, now)
for suggestion in suggestions:
    print(suggestion.category.value, suggestion.description)
```

**`suggestions` is data only.** Nothing in this codebase (and nothing
this subsystem is authorized to add per `ADR-020` Hard Rule 3) ever
feeds a `ResearchSuggestion` back into Scanner, Strategy Engine, Scoring
Engine, Risk Engine, Compliance Engine, or Execution Validator. A human
reviews the queue and decides what, if anything, to act on manually
(likely as a config change reviewed through the normal RPI workflow).

## 6. Knowledge Dashboard

```python
snapshot = knowledge_engine.render_dashboard_snapshot(now)
# snapshot.recent_insights, snapshot.recent_trade_memory,
# snapshot.research_queue, snapshot.recent_ai_explanations
```

This is a separate, additive read type
(`phantom_pipeline.knowledge.models.KnowledgeDashboardSnapshot`) — it is
not one of Dashboard's ten `ViewName` views and does not require any
change to `dashboard/` (`ADR-020` Hard Rule 4). Render it alongside the
existing Dashboard views in whatever UI layer consumes them.

## 7. What this subsystem does not do

- It does not call an external LLM (Hard Rule 5) — every explanation is
  a deterministic template. An "assistant mode" LLM integration is a
  real, intended future amendment, not shipped here.
- It does not persist to disk — `InMemoryVectorStore`/
  `KnowledgeDocumentStore`/`TradeMemoryStore` are Phase 1, in-process
  only. Restarting the process loses the index; re-run steps 2-3 to
  rebuild it (cheap, since ingestion/indexing is fast and deterministic).
- It never blocks, delays, or observes a live trading decision — it is
  called only after the fact, from outside the pipeline, exactly like
  `paper_trading`'s own reporting calls.
