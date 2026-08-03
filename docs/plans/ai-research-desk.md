# Plan: Phantom AI Research Desk (`ADR-021`)

Status: Validated
Owner (Plan phase): AI Systems Engineer
Touched components: new `phantom_pipeline/research_desk` package,
`scripts/check_architecture.py` (generalized check) only

---

## Research

- **Affected files and their dependencies**: none of the 15 existing
  `phantom_pipeline` packages are modified — including
  `phantom_pipeline/knowledge/` (`ADR-020`) and `phantom_pipeline/dashboard/`
  (`ADR-012`), both explicitly reused rather than touched.
- **Duplicate-logic check performed before writing anything**
  (`CLAUDE.md` §1.4) — see `ADR-021` §2's reuse map in full. In summary:
  - Every requested "Knowledge Memory (RAG)" and "Explainable Decision
    Engine" capability that already exists in `phantom_pipeline.knowledge`
    (ingestion, vector search, `TradeMemoryRecord`, `ExplanationEngine`,
    `SemanticSearchService`) is reused wholesale via `knowledge`'s own
    `__init__.py` — no second vector store, no second document
    repository, no second explanation engine.
  - Every new report/thesis/journal-entry type converts to a
    `knowledge.KnowledgeDocument` using an *already-existing*
    `DocumentKind` value: `TRADE_JOURNAL` (journal entries and trade
    theses), `ANALYTICS_REPORT` (bull/bear debate summaries),
    `WEEKLY_REPORT`/`PRODUCTION_REPORT` (market research and
    institutional review reports), `STRATEGY_DOC` (strategy research
    findings) — confirmed by reading `knowledge/models.py`'s `DocumentKind`
    enum before writing anything; zero new enum values needed, zero
    modification to that file.
  - `knowledge.models.ResearchSuggestion` is reused verbatim by
    `StrategyResearchAgent` — no second "research finding" type defined.
  - `paper_trading.ReportGenerator`'s `PeriodReport` and
    `AnalyticsEngine.group_by_pair/session/regime` are read directly by
    `WeeklyInstitutionalReviewGenerator`/`StrategyResearchAgent` — never
    recomputed.
  - `KnowledgeDashboardSnapshot` (`ADR-020`) is held as a field on the
    new `ResearchDeskDashboardSnapshot`, never re-implemented.
- **Touched stages' ADR status**: no stage's ADR is touched. `ADR-020`
  is read-only input, not amended — confirmed no new `DocumentKind`
  value or `KnowledgeDashboardSnapshot` field was needed.
- **Genuine gaps, confirmed by repository search, not fabricated**:
  - No macro-news or economic-calendar module exists —
    `compliance_engine.models.NewsCalendarState.blackout_windows` is the
    only real feed, narrow by `ADR-006` §8's own design.
  - No backtest or optimization module exists anywhere in
    `phantom_pipeline` (`find -iname "*backtest*" -o -iname "*optimiz*"`
    returns nothing). `StrategyResearchAgent.analyze_parameter_sensitivity`
    therefore returns an explicit "insufficient data" result, never an
    invented number.
- **`python3 scripts/check_architecture.py` result (baseline, before
  this change)**: PASS — 15 packages, no cycles, no private-state
  access, no pipeline-stage → `knowledge` import.

## Plan

New package `phantom_pipeline/research_desk/`, 13 modules: `models.py`,
`config.py`, `market_research.py`, `debate.py`, `trade_thesis.py`,
`trade_journal.py`, `strategy_research.py`, `institutional_review.py`,
`explainable.py`, `dashboard.py`, `logging_sink.py`, `metrics.py`,
`__init__.py`.

Every agent takes its inputs by constructor/method injection (already-
produced `ScannerObservation`/`TradeProvenanceRecord`/`PeriodReport`/
`ComplianceEngineMetrics`/`ExecutionValidatorMetrics` sequences) and a
reference to a `KnowledgeEngine` instance for indexing its own outputs
— no agent constructs its own `KnowledgeEngine`, matching the
constructor-DI discipline used throughout `phantom_pipeline`.

`scripts/check_architecture.py`: the existing `find_knowledge_import_violations`
check is generalized to a `CROSS_CUTTING_OBSERVER_PACKAGES = {"knowledge",
"research_desk"}` set, so no pipeline-stage package may import either.

Tests: `tests/phantom_pipeline/research_desk/`, one file per module plus
a structural-boundary suite, targeting 100+ tests.

## Validation

`python3 -m compileall`, `python3 -m unittest discover -s
tests/phantom_pipeline`, `python3 validate.py`, `python3
scripts/check_architecture.py` — all four must stay green, package count
rising from 15 to 16, zero diff against any existing file except
`scripts/check_architecture.py`'s generalized check.
