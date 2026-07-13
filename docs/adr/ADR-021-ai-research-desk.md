# ADR-021 — Titan Protocol AI Research Desk

Status: Accepted

Acceptance Date: 2026-07-06

Accepted By: User direction, this session (explicit, full subsystem
specification provided) — the same in-session approving authority
already used for `ADR-014` Amendments 1/2 and `ADR-020`.

Owner: AI Systems Engineer (Accountable per `.claude/agents/TEAM.md`
§1/§5 — trade memory, AI trade journal, explainable decisions, outcome
analytics, research assistant are this role's own named scope)

Reviewed by: Integration Engineer (interface-compatibility/circular-
import verification), Quant Validation Engineer (Consulted — Strategy
Research Agent's rule-combination/parameter-sensitivity output is
statistical-edge-adjacent, the same review posture already given to
paper trading's forward-test statistics)

Date: 2026-07-06

Depends on: `ADR-001` through `ADR-013` (Accepted — every stage read
from), `ADR-014` (Accepted, governance), `ADR-020-knowledge-rag-subsystem.md`
(Accepted — reused wholesale, not duplicated; see §2)

---

# Pipeline position

**Not part of the deterministic trading pipeline**, exactly like
Watchdog (`ADR-011`), Dashboard (`ADR-012`), and the Knowledge & RAG
subsystem (`ADR-020`). The Research Desk sits one layer further out
than Knowledge: Knowledge is a passive index/retrieval layer; the
Research Desk is a set of analysis *agents* built on top of it and on
top of the pipeline's own already-produced objects. Nothing in the
pipeline (`Data Pipeline` through `Position Manager`) depends on the
Research Desk; the Research Desk depends on the pipeline's and
Knowledge's already-produced outputs only.

---

# 1. Mission

**The Research Desk answers: "What does Titan Protocol's own history and the
current market tell us, and what might be worth investigating?"** It
never answers "what should we trade" — that remains the deterministic
pipeline's exclusive authority, unchanged since `ADR-001`.

---

# Hard Rules

1. **No decision, execution, risk, compliance, sizing, or scoring
   authority** — identical in force to `ADR-020` Hard Rules 1-2. No
   method anywhere in `phantom_pipeline/research_desk/` constructs a
   `RiskDecision`/`ComplianceDecision`/`ExecutionDecision`/
   `CandidateTrade`/`PositionManagementDecision`, and none accepts one as
   a *return* value it produces — only as a read-only input.
2. **Every recommendation is exported data, never applied
   automatically.** `StrategyResearchAgent`'s findings and every
   `ResearchSuggestion` (reused from `phantom_pipeline.knowledge`, never
   re-defined) require explicit human review before becoming a
   configuration change in any pipeline stage — this ADR grants no
   mechanism for automatic application, and none is built.
3. **`phantom_pipeline/knowledge/` (`ADR-020`) is reused, not
   duplicated.** The Research Desk does not build a second vector store,
   a second document repository, or a second dashboard-snapshot type
   for the same concern. Every new report/thesis/journal-entry type is
   converted to a `knowledge.KnowledgeDocument` using an *already-
   existing* `DocumentKind` value (`TRADE_JOURNAL`, `ANALYTICS_REPORT`,
   `WEEKLY_REPORT`, `PRODUCTION_REPORT`, `STRATEGY_DOC` already cover
   every new report type named in this ADR) — zero modification to
   `phantom_pipeline/knowledge/`'s own files. `ResearchDeskDashboardSnapshot`
   *wraps* the existing `KnowledgeDashboardSnapshot` (holds it as a
   field) rather than replacing or re-implementing it.
4. **`dashboard/` (`ADR-012`) is untouched** — same as `ADR-020` Hard
   Rule 4, restated for this ADR's own Knowledge Dashboard item (item 9
   of the originating request).
5. **No fabricated data.** Where the requested analysis needs an input
   Titan Protocol does not yet produce — a rich macro-news feed (only
   `compliance_engine.models.NewsCalendarState.blackout_windows`
   exists, a narrow blackout-window list per `ADR-006` §8, not a macro
   analysis feed), a full economic calendar (same field), or
   backtest/optimization sweep data (no such module exists anywhere in
   `phantom_pipeline` today) — the corresponding method returns an
   explicit "insufficient data" result or an empty tuple, documented
   inline, never an invented number or narrative.
6. **The Bull vs Bear Debate Agent's output is structurally incapable of
   being a trading signal.** `DebateThesis` has no `direction`/
   `lot_size`/`entry_price`/`stop_loss`/`take_profit` field, and no
   pipeline-stage package imports `research_desk` (§9, enforced by
   `scripts/check_architecture.py`).
7. **Journal entries are immutable.** `JournalEntry` is a frozen
   dataclass with no update method anywhere in `trade_journal.py` — a
   correction is a new entry, never an edit of history, mirroring
   `TradeProvenanceRecord`'s own "permanent historical record" posture
   (`ADR-010` §5).
8. **Trace ID propagation.** Every research-desk object tied to a
   specific trade (`TradeThesis`, `JournalEntry`) carries that trade's
   own `trace_id` verbatim; global reports (`MarketResearchReport`,
   `InstitutionalReviewReport`) carry their own `report_id` +
   `generated_at`, never a fabricated trace chain.
9. **No pipeline-stage package imports `research_desk` or `knowledge`.**
   `scripts/check_architecture.py`'s existing knowledge-import check
   (`ADR-020` Hard Rule 9) is generalized to cover both cross-cutting
   observer packages.

---

# 2. Reuse map (duplicate-logic check, `CLAUDE.md` §1.4)

| Requested item | Reused from | New in this ADR |
|---|---|---|
| Knowledge Memory (RAG) | `phantom_pipeline.knowledge` wholesale (`KnowledgeEngine`, vector store, document store) | Nothing — existing `DocumentKind` values already cover every new report type |
| Explainable Decision Engine (existing Q&A shapes) | `knowledge.search.SemanticSearchService`, `knowledge.engine.ExplanationEngine` | `compare_periods`/`what_changed_over` only (genuinely new query shapes) |
| Knowledge Dashboard | `knowledge.models.KnowledgeDashboardSnapshot` (wrapped, not re-implemented) | `ResearchDeskDashboardSnapshot`'s own additional fields (research summaries, learning trends, strategy evolution) |
| Best/worst pair/session/regime | `AnalyticsEngine.group_by_pair/session/regime`, `paper_trading.ReportGenerator` | rule-combination co-occurrence, parameter-sensitivity (flagged gap) |
| Weekly report skeleton | `paper_trading.ReportGenerator.generate_weekly`'s `PeriodReport` | executive-summary/risk/compliance/execution/market narrative sections, recurring-mistakes |
| `ResearchSuggestion` type | `knowledge.models.ResearchSuggestion` (reused verbatim) | none — no second suggestion type defined |

---

# 3. Interfaces (`phantom_pipeline/research_desk/`)

`models.py`, `config.py`, `market_research.py` (`MarketResearchAgent`),
`debate.py` (`BullBearDebateAgent`), `trade_thesis.py`
(`TradeThesisGenerator`), `trade_journal.py` (`AITradeJournal`),
`strategy_research.py` (`StrategyResearchAgent`),
`institutional_review.py` (`WeeklyInstitutionalReviewGenerator`),
`explainable.py` (`ExplainableDecisionEngine`), `dashboard.py`
(`ResearchDeskDashboardBuilder`), `logging_sink.py`, `metrics.py`,
`__init__.py`.

---

# 4. Testing

Per the task's own architecture requirements: unit tests per module,
integration tests tying agents together with `knowledge.KnowledgeEngine`
and `paper_trading.ReportGenerator`, and a dedicated structural-boundary
suite (no decision-verb method names, no pipeline-stage import of
`research_desk` or `knowledge`, `dashboard/`/`knowledge/` files
unmodified, `JournalEntry` has no update method, `DebateThesis` has no
signal-shaped field).

---

# 5. Acceptance criteria

- All Hard Rules verified by dedicated tests, not merely asserted.
- Full existing validation suite stays green; package count rises from
  15 to 16.
- Zero modification to `phantom_pipeline/knowledge/` or
  `phantom_pipeline/dashboard/`.

---

# 6. Explicitly out of scope (this ADR)

- A rich macro-news/economic-calendar analysis feed — Titan Protocol has no
  such data source; `MarketResearchAgent`'s macro/calendar methods
  operate only on `NewsCalendarState.blackout_windows` and say so.
- Backtest/optimization ingestion — no backtest or optimization module
  exists in `phantom_pipeline` yet (confirmed via repository search);
  `StrategyResearchAgent`'s parameter-sensitivity method returns an
  explicit "insufficient data" result rather than fabricating one.
- Any mechanism for a `ResearchSuggestion` (or any new finding type) to
  automatically become a configuration change — human approval is a
  Hard Rule (§Hard Rules 2), not a workflow this ADR designs.
