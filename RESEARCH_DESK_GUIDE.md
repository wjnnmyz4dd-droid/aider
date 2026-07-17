# Phantom AI Research Desk — Usage Guide

**Status: DEPRECATED.** Written for the pre-Titan-Protocol
`phantom_pipeline/research_desk/` package. The current Titan Protocol
Windows release (`deployment_windows/`) does not wire the Research Desk
or Knowledge/RAG subsystems into its live runtime, so this guide does
not describe anything reachable from a current deployment. Kept for
historical reference only.

How to wire `phantom_pipeline/research_desk/` (`ADR-021`) into a running
deployment. Like `KNOWLEDGE_DEPLOYMENT_GUIDE.md`, this is read-only
intelligence — it never affects trading behavior.

**This package sits on top of `phantom_pipeline.knowledge` (`ADR-020`),
not beside it.** Every RAG/search/dashboard capability is the same
`KnowledgeEngine` you already wired up for Knowledge — construct one
`KnowledgeEngine` for the whole deployment and hand it to whichever
Research Desk agents need it.

## 1. Market Research Agent

```python
from phantom_pipeline.research_desk import MarketResearchAgent

agent = MarketResearchAgent()
report = agent.generate_daily(
    report_id="mr-2026-07-06",
    now=now,
    observations=[("EURUSD", eurusd_observation), ("GBPUSD", gbpusd_observation)],
    news_state=news_calendar_state,  # optional; None if unavailable
)
```

`report.macro_news_summary`/`report.economic_calendar_summary` are
honest about Phantom's real data: both read the same
`NewsCalendarState.blackout_windows` feed — there is no richer macro-news
source to draw from yet.

## 2. Bull vs Bear Debate Agent

```python
from phantom_pipeline.research_desk import BullBearDebateAgent

thesis = BullBearDebateAgent().generate_thesis("debate-1", "EURUSD", observation, now)
print(thesis.final_summary)  # always ends "... Research only — not a trading signal."
```

## 3. Trade Thesis + AI Trade Journal

Both read the same already-produced `TradeProvenanceRecord`:

```python
from phantom_pipeline.research_desk import TradeThesisGenerator, AITradeJournal

record = orchestrator.analytics.build_provenance_record(trace_id, now)
thesis = TradeThesisGenerator().generate(record, now)
entry = AITradeJournal().create_entry(record, now)  # frozen; a correction is a new entry, never an edit
```

## 4. Index everything into the same Knowledge Engine

```python
from phantom_pipeline.knowledge import DocumentKind, KnowledgeDocument

doc = KnowledgeDocument(
    schema_version=1, document_id=f"thesis-{thesis.trace_id}", kind=DocumentKind.TRADE_JOURNAL,
    title=f"Trade thesis {thesis.trace_id}",
    content=f"{thesis.institutional_context} {thesis.expected_continuation}",
    source_path=None, content_hash="...", metadata={"trace_id": thesis.trace_id}, ingested_at=now,
)
knowledge_engine.ingest_document(doc)
```

No new `DocumentKind` was needed — `TRADE_JOURNAL`/`ANALYTICS_REPORT`/
`WEEKLY_REPORT`/`PRODUCTION_REPORT`/`STRATEGY_DOC` already cover every
Research Desk report type.

## 5. Strategy Research Agent

```python
from phantom_pipeline.research_desk import StrategyResearchAgent

agent = StrategyResearchAgent(analytics=orchestrator.analytics)
best_pair, worst_pair = agent.best_worst_pairs(records)
rule_findings = agent.analyze_rule_combinations(records)
sensitivity = agent.analyze_parameter_sensitivity("atr_period")
print(sensitivity.available)  # always False today -- no backtest/sweep module exists
```

## 6. Weekly Institutional Review

```python
from phantom_pipeline.research_desk import WeeklyInstitutionalReviewGenerator

period_report = report_generator.generate_weekly(records, now)
suggestions = knowledge_engine.suggest_research(period_report, now)
review = WeeklyInstitutionalReviewGenerator().generate(
    "review-2026-w27", period_report, now, market_research_report=report, research_recommendations=suggestions,
)
```

## 7. Explainable Decision Engine

```python
from phantom_pipeline.research_desk import ExplainableDecisionEngine

engine = ExplainableDecisionEngine(knowledge_engine.search_service)
results = engine.ask("why didn't EURUSD trade today?")
comparison = engine.compare_periods("c1", "last month", last_month_report, "this month", this_month_report, now)
delta = engine.what_changed_over("c2", 90, ninety_days_ago_report, current_report, now)
```

## 8. Knowledge Dashboard (Research Desk view)

```python
from phantom_pipeline.research_desk import ResearchDeskDashboardBuilder

knowledge_snapshot = knowledge_engine.render_dashboard_snapshot(now)
snapshot = ResearchDeskDashboardBuilder().build(
    now, knowledge_snapshot,
    research_summaries=["..."], learning_trends=["..."], strategy_evolution=["..."],
)
```

`dashboard/` (`ADR-012`) and `knowledge/` (`ADR-020`) are both untouched
— this is a wrapper, not a second implementation.

## 9. Safety, restated

Every finding/suggestion/thesis produced here is data. Nothing in this
codebase feeds a `ResearchSuggestion`, `RuleCombinationFinding`, or
`DebateThesis` back into Scanner/Strategy Engine/Scoring Engine/Risk
Engine/Compliance Engine/Execution Validator — a human reviews the
Research Desk's output and decides what, if anything, to change through
the normal RPI workflow.

## 10. Honest gaps

- No rich macro-news or economic-calendar feed exists — both
  `MarketResearchAgent` methods read the same narrow blackout-window
  calendar and say so.
- No backtest/parameter-sweep module exists — `analyze_parameter_sensitivity`
  always reports `available=False` rather than a fabricated number.
- No persistence — like `knowledge/`, everything here is in-process only
  until re-generated.
