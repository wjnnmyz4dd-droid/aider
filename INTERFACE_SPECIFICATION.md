# Phantom Interface Specification

**Status: Architecture phase complete. No object below has been
implemented.**

This document catalogs every shared object/interface defined across the
19 Accepted ADRs in `docs/adr/`. It is a **catalog, not a schema** — no
field types, no code, no pseudocode. Each ADR's own Outputs/Inputs
section remains the authoritative definition; this document indexes
them for cross-stage reference.

**Universal properties, true of every object below unless stated
otherwise:**

- **Immutable once produced** — no stage rewrites another stage's
  output; a later stage attaches its own object alongside, never in
  place of, an earlier one.
- **Carries `schema_version`** — additive, backward-compatible field
  changes only; a breaking change requires a new major version and an
  explicit migration note (`ADR-002` §8, `ADR-014` §9).
- **Carries the shared `trace_id`** — one chain, established at Data
  Pipeline/Scanner ingestion (`ADR-013` §14, `ADR-002` §8) and
  propagated through every subsequent trading-pipeline object. Two
  **separate** `trace_id` chains exist elsewhere and must never be
  confused with the trading chain or each other: Watchdog's own
  health-event chain (`ADR-011` §5) and Multi-Agent Governance's
  agent-action chain (`ADR-014` §11). `ADR-012` §7 already states the
  Dashboard must display both correctly attributed, never merged.
- **Structurally incapable of holding a forbidden field** — every
  object below has a dedicated boundary/type-level test requirement in
  its own ADR; see `VALIDATION_MATRIX.md`.
- **"Never fewer than one output per input"** — every stage in the
  linear pipeline produces exactly one output object per input received,
  even on failure (a zero-risk `RiskDecision`, a BLOCK `ComplianceDecision`,
  etc.) — never a silent drop.

---

## 1. The linear trading-pipeline object chain

| Producing stage | Object | Defined in | Consumed by |
|---|---|---|---|
| Data Pipeline | `NormalizedTick` | `ADR-013` §5 | Internal to Data Pipeline (bar construction) |
| Data Pipeline | `NormalizedBar` | `ADR-013` §5 | Scanner |
| Data Pipeline | `MarketSnapshot` | `ADR-013` §5 (Amendment 1 added a consumer) | Scanner, Compliance Engine, Execution Validator, MT5 Bridge, Replay & Certification Engine (shadow trading only, read-only, `ADR-013` Amendment 1) |
| Data Pipeline | `HistoricalSeries` | `ADR-013` §5 | Scanner (warm-up/backtesting), Replay & Certification Engine |
| Data Pipeline | `ReplaySeries` | `ADR-013` §5 | Replay & Certification Engine, Analytics, Research Agent (all read-only) |
| Data Pipeline | `DataQualityReport` | `ADR-013` §5 | Watchdog, Analytics |
| Data Pipeline | `PipelineHealth` | `ADR-013` §5 | Watchdog |
| Scanner | `ScannerObservation` (+ Amendment 1 structural fields) | `ADR-002` §8 | Strategy Engine, Risk Engine (structural reference only), Analytics |
| Strategy Engine | `CandidateTrade` | `ADR-003` §6 | Scoring Engine, Risk Engine (context only), Analytics |
| Scoring Engine | `ScoreResult` | `ADR-004` §6 | Risk Engine, Analytics |
| Risk Engine | `RiskDecision` | `ADR-005` §4 | Compliance Engine, Execution Validator (context), MT5 Bridge (sizing), Position Manager (context), Analytics, Portfolio Manager (read-only) |
| Compliance Engine | `ComplianceDecision` | `ADR-006` §4 | Execution Validator, Analytics, Portfolio Manager (read-only) |
| Execution Validator | `ExecutionDecision` | `ADR-007` §4 | MT5 Bridge, Analytics, Portfolio Manager (read-only) |
| MT5 Bridge | `BrokerRequest`, `BrokerAcknowledgement`, `ExecutionReceipt`, `BrokerError`, `FillReport`, `ConnectionStatus`, `SynchronizationStatus` | `ADR-008` §5 (Amendment 1 generalized the first four to also cover position-management requests) | Position Manager, Analytics, Watchdog (health) |
| Position Manager | `PositionManagementDecision`, `PositionUpdate`, `PositionCloseRequest`, `PositionAdjustmentRequest`, `PositionSynchronizationResult` | `ADR-009` §5 | Analytics; `PositionCloseRequest`/`PositionAdjustmentRequest` route back to MT5 Bridge (`ADR-008` Amendment 1) — the one reverse edge in the pipeline (`ADR-009` §9) |
| Analytics | `TradeProvenanceRecord`, Performance statistics, Replay input sets, Missing-event reports | `ADR-010` §5 | Human review, Dashboard, Replay & Certification Engine, Portfolio Manager, Research Agent (all read-only) |

---

## 2. Cross-cutting objects

| Producing agent | Object | Defined in | Consumed by |
|---|---|---|---|
| Watchdog | `SystemHealth` | `ADR-011` §5 | Dashboard (via Prometheus), human operators |
| Dashboard | *(no new output objects — a pure read/visualization layer)* | `ADR-012` §4 | Human viewers only |
| Portfolio Manager | `PortfolioState`, `PortfolioAllocation`, `PortfolioHealth`, `ExposureSummary`, `CorrelationSummary`, `CapitalBudget`, `PortfolioRecommendation`, `PortfolioMetrics` | `ADR-017` §5 | Human review (recommendations only — never a live feedback loop into Risk Engine or Compliance Engine, `ADR-017` §7) |
| Replay & Certification Engine | `ReplayResult`, `CertificationReport`, `PromotionRecommendation`, `EvidencePackage`, `ReplayMetrics`, `CertificationHistory` | `ADR-018` §5 | Human review (promotion decisions only, `ADR-018` §7) |
| AI News Intelligence | `NewsTheme` | `ADR-016` §4 | Analytics (contextual annotation only), human review — **never** an automated input to Compliance Engine's news guard (`ADR-016` §2) |
| Research Agent | `ResearchHypothesis`, `PatternObservation`, `StatisticalSummary`, `WeaknessReport`, `CandidateExperiment`, `BacktestRequest`/`WalkForwardRequest`/`MonteCarloRequest`, `HumanReviewRequest` | `ADR-019` §4 | Replay & Certification Engine (as "Research proposals," `ADR-018` §4), Human Review — every hypothesis terminates in a `HumanReviewRequest` regardless of validation depth |

---

## 3. Multi-Agent Governance's classification of the above (`ADR-014` §3)

| Agent class | Members | Objects produced above |
|---|---|---|
| Pipeline Agents | Data Pipeline, Scanner, Strategy Engine, Scoring Engine, Risk Engine, Compliance Engine, Execution Validator, MT5 Bridge, Position Manager, Analytics | Section 1's entire chain |
| Infrastructure Agents | Watchdog, Dashboard, **Portfolio Manager** (classified here by decision-authority criterion, `ADR-017` §12) | `SystemHealth`; none (Dashboard); Portfolio Manager's objects above |
| Governance Agents | The ten `TEAM.md` Council roles, **Replay & Certification Engine** (classified here, `ADR-018` §11) | Replay & Certification's objects above |
| Advisory Agents | AI News Intelligence | `NewsTheme` |
| Research Agents | Self-Evolving Research Agent | Research Agent's objects above |
| Human Review | The Phantom Engineering Council acting through a human | Accepts ADRs; approves promotions; no data object of its own |

---

## 4. Forbidden-field guarantee — summary

Every object in Sections 1–2 is structurally forbidden from holding
fields belonging to a different stage's authority (e.g. no object
before `RiskDecision` may hold a lot size; no object before
`ComplianceDecision` may hold an approval verdict; no object anywhere
outside `ADR-008`'s outputs may hold a broker order instruction). The
authoritative forbidden-field list for each object is its own ADR's
"Forbidden" subsection or "shall never" table — this document does not
restate them individually; see `VALIDATION_MATRIX.md` for the
corresponding boundary/type-level test per stage.

---

## 5. Adapter-layer interfaces (`ADR-015`)

Every vendor-facing adapter (Data Pipeline's MT5 Broker Feed/Calendar
ingestion, any future approved external market data source) is bound by
`ADR-015`'s **Adapter Forbidden Responsibilities**: translation only — no
business, strategy, scoring, risk, compliance, or AI-reasoning logic; no
mutation of a pipeline object; no bypass of a pipeline stage. This is an
interface-level constraint on every adapter in the system, not a
separate object.
