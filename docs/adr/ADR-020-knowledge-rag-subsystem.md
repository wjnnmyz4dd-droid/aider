# ADR-020 — Knowledge & RAG Subsystem

Status: Accepted

Acceptance Date: 2026-07-06

Accepted By: User direction, this session (explicit: "Create a formal
ADR for the Knowledge/RAG subsystem. It's large enough to deserve its
own architecture document.") — the same in-session approving authority
already used to accept `ADR-014` Amendments 1/2 in this repository.

Owner: AI Systems Engineer (Accountable per `.claude/agents/TEAM.md`
§1/§5 — the role is explicitly hard-boundaried to AI-adjacent features
including "trade memory, AI trade journal, explainable decisions,
outcome analytics... research assistant," which is this ADR's entire
scope, and explicitly forbidden from ever generating a trade decision or
influencing any pipeline stage, which this ADR's Hard Rules make
structural rather than just a role description)

Reviewed by: Integration Engineer (post-hoc interface-compatibility and
circular-import verification, per `TEAM.md`'s RACI), Security Architect
(Consulted — this package reads every trade record and every
architecture document in the repository; confidentiality/exfiltration
posture warrants the same review given to Watchdog's restart surface)

Date: 2026-07-06

Depends on: `ADR-001-single-authority-architecture.md` (Accepted),
`ADR-002` through `ADR-010` (Accepted — every stage this package reads
from), `ADR-011-watchdog-recovery.md` (Accepted), `ADR-012-dashboard-observability.md`
(Accepted), `ADR-014-multi-agent-governance.md` (Accepted, Amendments 1-2)

---

# Pipeline position

**The Knowledge/RAG subsystem is not part of the deterministic trading
pipeline.** Exactly like the Watchdog (`ADR-011`) and Dashboard
(`ADR-012`), it is a cross-cutting service that observes the outputs of
every stage — Market Data through Analytics — without occupying a
position in the decision chain, and without the pipeline depending on it
for anything. Unlike Watchdog/Dashboard, it has no live "in the loop"
role at all: it ingests already-produced, immutable records after the
fact, and answers questions about them. Nothing in the pipeline ever
calls into this package; this package only ever calls out to already-
public methods of other packages (`AnalyticsEngine`, `ReportGenerator`,
etc.), exactly as `paper_trading` and `orchestrator.py` already do.

---

# 1. Mission

**The Knowledge/RAG subsystem answers exactly one question: "What does
Titan Protocol's own history and documentation say about X?"**

**It never answers:** Should we trade? Should we execute? Should we
modify a position? Should we change risk, compliance, or scoring? Those
remain each stage's own question, already answered by that stage's own
Accepted ADR. This subsystem's entire mandate is retrieval and
explanation over already-produced facts — it observes, it indexes, it
retrieves, and it explains in natural language; it never decides, never
sizes, never scores, and never executes.

---

# Hard Rules

1. **Read-only, structurally.** No class, method, or module in
   `phantom_pipeline/knowledge/` may accept a `RiskDecision`,
   `ComplianceDecision`, `ExecutionDecision`, `CandidateTrade`,
   `ScoreResult`, or any position-management/broker-request type as a
   *return* value it produces — it may only ever read them as inputs.
   No `set_*`/`submit_*`/`decide_*`/`approve_*`/`reject_*`/`execute_*`
   method exists anywhere in this package (mirrors `ADR-012` §4's own
   structural read-only guarantee for Dashboard, verified the same way:
   grep for forbidden verb fragments across every public method name).
2. **No decision, execution, risk, compliance, scoring, or sizing
   authority.** This package cannot approve, reject, size, or execute a
   trade, and holds no field or method capable of representing one
   (the same type-level guarantee every prior stage ADR establishes for
   its own forbidden concepts).
3. **`ResearchSuggestion` never reaches a pipeline stage.** It is a
   plain, inert data record. No pipeline-stage package (`scanner`
   through `position_manager`) imports anything from `knowledge/` —
   enforced by `scripts/check_architecture.py`'s existing circular-
   import/cross-package rule, which already fails the build if any
   pipeline package imports a non-`.models`/`.trace`/`.registry` path
   from another package, and which this ADR extends to also fail if any
   pipeline-stage package imports `knowledge` *at all* (§9).
4. **Additive to Dashboard, never a modification of it.** `dashboard.models.ViewName`
   remains the closed, ten-value enum `ADR-012` §5 defines — this
   package does not add an eleventh value to it, and does not import or
   modify any `dashboard/` file. `KnowledgeDashboardSnapshot`
   (`knowledge/models.py`) is a wholly separate, additive read type,
   mirroring `paper_trading.validation_dashboard.ValidationDashboardSnapshot`'s
   own precedent exactly.
5. **Deterministic explanation generation only, for Phase 1.** Every
   natural-language explanation is built from a fixed template populated
   with already-recorded fields (`reason_codes`, `blocking_rules`,
   `blocking_reasons`, `decision_reason`, verdicts) — never a call to an
   external LLM. This keeps every explanation byte-for-byte reproducible
   under replay (§8's testing requirement) and introduces no new
   secret/network/cost surface. An LLM-backed "assistant mode" is
   explicitly out of scope for this ADR (§10) — a real, flagged
   possibility for a future amendment, never silently built now.
6. **Embeddings are pluggable; the shipped default is dependency-free
   and deterministic.** `EmbeddingProvider` is a structural interface
   (`embeddings.py`); `HashingEmbeddingProvider` (the feature-hashing
   trick — no external dependency, no model download, no network,
   fully deterministic) is the default used by every test and by
   `DEV`/`CI`. A real neural embedding backend
   (`SentenceTransformerEmbeddingProvider`, lazily importing
   `sentence-transformers`, mirroring `MT5Adapter`'s own lazy-import-
   with-injectable-module pattern) is provided for VPS deployments that
   want higher retrieval quality — never required for this package to
   import cleanly or for its test suite to pass.
7. **No duplicate computation.** Every number this package surfaces
   (win rate, expectancy, best/worst pair/session/regime, drawdown,
   rule-blocking frequency) is read from `AnalyticsEngine`/
   `ReportGenerator`'s already-computed output, never recomputed by a
   second implementation (the same duplicate-logic discipline
   `paper_trading` already established for itself in
   `docs/plans/phase4-paper-trading.md`).
8. **Ingestion never mutates a source object.** Every `TradeProvenanceRecord`,
   `PositionUpdate`, or documentation file this package reads is read
   verbatim; `TradeMemoryRecord` stores references/copies of already-
   produced values, never a rewritten version of the source.
9. **`scripts/check_architecture.py` enforced, extended.** No circular
   import; every cross-package import from `knowledge/` targets only
   another package's `.models`/`__init__.py` (never a private
   submodule); and (new, this ADR) no pipeline-stage package may import
   `knowledge` at all, in either direction.

---

# 2. What is ingested (Responsibilities)

Via `ingestion.py`, on an incremental, deduplicated basis
(content-hash-keyed — re-ingesting an unchanged file/record is a no-op):

- **Documentation**: every ADR (`docs/adr/*.md`), `TEAM.md`,
  `INTERFACE_SPECIFICATION.md`, `IMPLEMENTATION_PLAN.md`,
  `VALIDATION_MATRIX.md`, `CHANGELOG.md`, `docs/plans/*.md`, the
  deployment guides (`LIVE_DEPLOYMENT_GUIDE.md`, `VPS_SETUP_GUIDE.md`,
  `DISASTER_RECOVERY.md`, `OPERATOR_CHECKLIST.md`), strategy
  documentation (playbook docstrings).
- **Records**: every `TradeProvenanceRecord` (→ one `TradeMemoryRecord`
  each), every `PositionUpdate`, every generated `PeriodReport`
  (daily/weekly/monthly/production reports), every `ForwardTestReport`
  (paper trading), every replay/certification report reachable from
  `ADR-018`'s output (forward-referenced; ingested only once produced),
  every `ValidationDashboardSnapshot`/health report.

Never ingested: raw credentials, `.env` files, or anything under
`config/` — `ingestion.py` has no file-reading function that accepts a
path outside the explicit, named document set above; it does not walk
arbitrary directories.

---

# 3. Interfaces (`phantom_pipeline/knowledge/`)

`models.py` (types only), `config.py` (tunables), `embeddings.py`
(`EmbeddingProvider` + two implementations), `vector_store.py`
(`VectorStore` + `InMemoryVectorStore`), `memory.py`
(`TradeMemoryStore`), `ingestion.py` (document/trade → `KnowledgeDocument`/
`TradeMemoryRecord`), `retriever.py` (embed query → search → resolve),
`search.py` (`SemanticSearchService` — the example-question-shaped
convenience API), `engine.py` (`KnowledgeEngine` — the top-level
orchestrator: ingestion, explanation generation, weekly review, research
suggestions, dashboard snapshot), `logging_sink.py`, `metrics.py`,
`__init__.py`.

No pipeline-stage package's public interface changes. `orchestrator.py`
is not modified — a caller wanting to feed live records into
`KnowledgeEngine` does so the same way `paper_trading`/`deployment`
already call the orchestrator's existing public methods, from outside
`orchestrator.py` itself.

---

# 4. Testing (§14-equivalent)

Per the task's own stated target (100+ tests): determinism (identical
input → identical `TradeMemoryRecord`/explanation/embedding — including
under replay, mirroring every pipeline stage's own replay-determinism
test), search accuracy (a known query against a known small corpus
returns the expected top result), duplicate prevention (re-ingesting an
unchanged document/record is a no-op, verified via `metrics.py`'s
`duplicate_documents_skipped_count`), memory integrity (a
`TradeMemoryRecord`'s fields trace back to its source
`TradeProvenanceRecord` verbatim, never fabricated), thread safety
(concurrent `ingest`/`search` calls against `InMemoryVectorStore`/
`TradeMemoryStore` never corrupt state or raise), documentation/trade
indexing (each named source type in §2 is actually ingestible), vector
retrieval (cosine-similarity ranking is correct on a hand-constructed
example), and the structural boundary test (no pipeline-stage package
imports `knowledge`, verified via source scan).

---

# 5. Architectural invariants

- Zero modification to any of the 14 existing `phantom_pipeline`
  packages, `orchestrator.py`, or any existing test.
- `phantom_pipeline/knowledge/` becomes the 15th package;
  `scripts/check_architecture.py` must report 15 packages, no cycles,
  no cross-package private-state access, and (per Hard Rule 9) no
  pipeline-stage → `knowledge` import.
- `KnowledgeDashboardSnapshot` is additive; `dashboard/` is untouched.

---

# 6. Acceptance criteria

- All Hard Rules (above) hold, verified by dedicated tests, not merely
  asserted in prose.
- Full existing validation suite (`compileall`, `unittest discover`,
  `validate.py`, `scripts/check_architecture.py`) stays green.
- 100+ new tests, all passing.

---

# 7. Reference material — ideas only, not authority

The "Research mode"/`ResearchSuggestion` concept is deliberately modeled
on `ADR-019`'s own forward-declared self-evolving research agent
framing (suggestions as an export, never an autonomous trading-logic
change) — this ADR does not implement `ADR-019`, it only reuses the same
"suggest, never apply" shape for its own, narrower research-suggestion
feature.

---

# 8. Explicitly out of scope (this ADR)

- An LLM-backed "assistant mode" explanation generator (Hard Rule 5) —
  noted as a real, intended future amendment, not built here.
- A persistent (on-disk/external) vector database — `InMemoryVectorStore`
  is this ADR's Phase 1 store, the same "real in-memory store now, a
  persistence backend later" posture every other package's
  `InMemory*Store` already takes.
- Extending `dashboard.models.ViewName` — explicitly rejected in favor of
  the additive `KnowledgeDashboardSnapshot` approach (Hard Rule 4).
