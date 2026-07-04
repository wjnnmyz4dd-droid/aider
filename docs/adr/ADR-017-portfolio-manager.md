# ADR-017 — Portfolio Manager

Status: Proposed

Owner: Security Architect (per the Gap Audit's own recommendation,
`ARCHITECTURE-GAP-AUDIT-2026-07-04.md` §3's Missing Capability Matrix —
Portfolio Manager's Owning Council member is named there, not assigned
fresh here)

Reviewed by: Backend Architect (Consulted — data contracts/reliability,
matching the same role Risk Engine's own Accountable party plays for
adjacent capital/exposure concepts), Software Architect (mandatory — a
new cross-cutting stage requires this per `TEAM.md` §3)

Date: 2026-07-04

Depends on: `ADR-001-single-authority-architecture.md` (Accepted),
`ADR-005-risk-engine.md` (Accepted — §5/§9/§10/§11 already forward-
reference this ADR by number as the future cross-strategy portfolio
view; this ADR is that fulfillment, and must not contradict §5's
sizing-only/never-overrides-Compliance boundary), `ADR-006-compliance-
engine.md` (Accepted — §13's Maximum Positions blocking authority, which
this ADR does not duplicate or weaken), `ADR-009-position-manager.md`
(Accepted — this ADR "operates after" it, per the Position section
below), `ADR-010-analytics-decision-provenance.md` (Accepted — sole
owner of permanent trade history, §13; this ADR reads through it rather
than maintaining a second archive), `ADR-012-dashboard-observability.md`
(Accepted — already displays portfolio-level statistics attributed to
Analytics; §11 below flags a resulting gap rather than silently
resolving it), `docs/adr/ADR-014-multi-agent-governance.md` (Accepted —
classifies this ADR's own agent, §12 below)

---

# Pipeline position

**Portfolio Manager is not part of the deterministic, per-trade decision
pipeline.** `ADR-001`'s pipeline diagram (Market Data → … → Position
Manager → Analytics) is unchanged by this ADR — Portfolio Manager sits
alongside it, the same cross-cutting relationship Analytics, Watchdog,
Dashboard, and Multi-Agent Governance already have to the pipeline, not
a new stage inserted into the diagram. It operates **after** Position
Manager: it consumes the current portfolio state (already-open and
recently-closed positions) that Position Manager and Analytics have
already, independently, produced and recorded. **It never modifies a
historical decision, has no broker authority, and holds no MT5
credentials.**

---

# 1. Mission

**The Portfolio Manager answers exactly one question: "Given every
approved position, what is the safest allocation of capital across the
entire portfolio?"**

**It never answers:** Should we trade? Should we score? Should we
execute? Should we bypass Compliance? Should we bypass Risk? Should we
modify Scanner output? Those are, respectively, Strategy/Scoring
Engines', Execution Validator's/MT5 Bridge's, Compliance Engine's, Risk
Engine's, and Scanner's questions — each already answered by its own
Accepted ADR. Portfolio Manager evaluates the portfolio that already
exists; it never decides whether any individual trade happens.

---

# Hard Rules

These override any other requirement in this document if they ever
appear to conflict:

- **Portfolio Manager SHALL NEVER:** generate `CandidateTrade`s, modify
  `ScannerObservation`, modify Strategy output, modify `ScoreResult`,
  modify `RiskDecision`, modify `ComplianceDecision`, modify
  `ExecutionDecision`, execute trades, modify MT5 state, override
  Compliance, or override Human Review (§4).
- **Read-only toward the trading pipeline.** Every input in §5 is
  consumed read-only; Portfolio Manager produces its own, separate output
  objects (§6) and never rewrites anything it reads.
- **No live feedback loop.** A `PortfolioRecommendation` or
  `CapitalBudget` output is advisory only. It never automatically alters
  Risk Engine's sizing, Compliance Engine's limits, or any other stage's
  behavior — any actual change those recommendations might justify
  requires the same human-reviewed, versioned-configuration process
  `ADR-005`'s Hard Rules already require for any risk-behavior change
  ("no self-adjusting risk without versioned configuration ... never
  runtime adaptation"). This is the single most important boundary in
  this ADR — see §7.
- **No broker authority, no MT5 credentials, no execution capability**
  (§10).

---

# 2. Responsibilities

Portfolio Manager SHALL own:

- Portfolio heat (whole-portfolio aggregate view — distinct from
  `ADR-005` §9's per-candidate sizing use of the same underlying
  concept; see §7).
- Cross-symbol exposure, cross-currency exposure, sector exposure.
- Correlation budgets (reusing, not recomputing, `ADR-005` §11's
  correlation methodology — see §8).
- Maximum concurrent exposure (a monitored metric, never a blocking gate
  — `ADR-006` §13 retains that authority; see §7).
- Capital allocation, strategy allocation, account allocation.
- Risk concentration, drawdown budgeting, diversification rules.
- Portfolio health, portfolio statistics, portfolio snapshots.
- Portfolio recommendations (advisory only, §7).

---

# 3. The Portfolio Manager shall never

| Forbidden action | Owned instead by |
|---|---|
| Generate `CandidateTrade`s | Strategy Engine (`ADR-003`) |
| Modify `ScannerObservation` | Nobody — immutable (`ADR-002` §8) |
| Modify Strategy output | Nobody — immutable (`ADR-003` §6) |
| Modify `ScoreResult` | Nobody — immutable (`ADR-004` §6) |
| Modify `RiskDecision` | Nobody — immutable (`ADR-005` §4) |
| Modify `ComplianceDecision` | Nobody — immutable (`ADR-006` §4) |
| Modify `ExecutionDecision` | Nobody — immutable (`ADR-007` §4) |
| Execute trades | MT5 Bridge (`ADR-008`) |
| Modify MT5 state | MT5 Bridge (`ADR-008`) |
| Override Compliance | Compliance Engine (`ADR-006`) — including its Maximum Positions blocking authority, `ADR-006` §13, which this ADR's "maximum concurrent exposure" monitoring never substitutes for |
| Override Human Review | Human Review (`ADR-014` §7) |

---

# 4. Inputs

All read-only:

- **`RiskDecision`** (`ADR-005` §4), **`ComplianceDecision`** (`ADR-006`
  §4), **`ExecutionDecision`** (`ADR-007` §4), **`PositionManagementDecision`**
  (`ADR-009` §6) — read via the shared `trace_id` chain, for portfolio
  composition context, never re-decided.
- **Analytics history** (`ADR-010`) — the sole permanent historical
  record (`ADR-010` §13); Portfolio Manager reads it for trend/statistics
  purposes rather than maintaining a second archive.
- **Open positions, closed positions** — read from Position Manager's
  and Analytics' already-published current-state view (`PositionUpdate`,
  `ADR-009` §5, or Analytics' read-only query surface, `ADR-010` §5 /
  the same surface `ADR-012` §4 already reads for Dashboard), never a
  second, independently-maintained position ledger.
- **Account equity, account balance** — read from the same account-state
  signal Compliance Engine and Risk Engine already consume (`ADR-006`
  §2, `ADR-005` §2), never re-derived.
- **Portfolio configuration** — versioned, per `ADR-005`'s configuration-
  governance precedent — heat/exposure/correlation ceilings, allocation
  priorities, diversification targets.

---

# 5. Outputs

One record per evaluation cycle, never discarded — the same discipline
established at every prior stage.

- **`PortfolioState`** — the current composition of open positions
  across symbols, currencies, strategies, and (if applicable) accounts.
- **`PortfolioAllocation`** — the current capital-allocation breakdown
  (§9).
- **`PortfolioHealth`** — an aggregate health assessment (§10):
  diversification, concentration, correlation, drawdown, liquidity,
  capital utilization.
- **`ExposureSummary`** — per-symbol/currency/sector exposure totals.
- **`CorrelationSummary`** — portfolio-wide correlation-bucket exposure
  (§8), reusing `ADR-005` §11's methodology.
- **`CapitalBudget`** — a recommended allocation ceiling per symbol/
  strategy/currency (§9) — **advisory, never self-enforcing** (§7).
- **`PortfolioRecommendation`** — a human-facing recommendation (e.g.
  "correlation clustering in USD pairs suggests tightening Risk Engine's
  correlation-exposure ceiling") — **never an instruction any stage acts
  on automatically** (§7).
- **`PortfolioMetrics`** — the metrics in §14.

**Type-level guarantee:** none of these output types is structurally
capable of holding a trade instruction, a modified upstream decision
field, or an automatic-configuration-change instruction — the same
guarantee established for every prior stage's output type, verified by
a dedicated test (§15).

**Immutability:** every output type, once produced, is immutable — a
point-in-time record, superseded by the next evaluation cycle, never
rewritten in place.

---

# 6. Portfolio rules

Architecture only — no formulas, no specific thresholds, per the same
discipline `ADR-005` §6 already established for risk budgeting:

- Maximum portfolio heat, maximum symbol exposure, maximum currency
  exposure, maximum strategy exposure, maximum correlation —
  **monitored and reported here; enforced, if at all, only through
  Risk Engine's own versioned configuration (sizing) or Compliance
  Engine's own blocking rules (§7), never directly by this ADR.**
- Diversification targets, capital allocation priorities — advisory
  inputs to `CapitalBudget`/`PortfolioRecommendation` (§5), never
  self-executing.
- Multi-account support — Portfolio Manager may aggregate across more
  than one trading account if Phantom operates on multiple accounts;
  this is a scope note, not a new authority — every per-account
  constraint remains that account's own Risk Engine/Compliance Engine
  instance's responsibility.

---

# 7. The central boundary: monitoring/recommendation, never sizing or blocking

**This is the most important distinction in this ADR.** `ADR-005` §5,
§9, §10, and §11 already, explicitly, forward-reference this ADR while
drawing a precise boundary that this ADR must honor, not blur:

- **Risk Engine's portfolio-heat/currency-exposure/correlation-exposure
  checks (`ADR-005` §9–§11) are real-time, per-candidate sizing
  inputs** — evaluated fresh for every scored candidate, as part of the
  deterministic pipeline, and they can only reduce or zero that one
  candidate's risk (`ADR-005` Hard Rules).
- **This ADR's equivalent concepts (portfolio heat, cross-currency
  exposure, correlation budgets) are a periodic, whole-portfolio,
  post-hoc monitoring and recommendation function** — evaluated across
  every currently open position, entirely outside the deterministic
  pipeline's real-time path, producing `PortfolioHealth`/
  `CapitalBudget`/`PortfolioRecommendation` for human consumption.
- **Neither view substitutes for or overrides the other.** Risk Engine's
  per-candidate sizing continues exactly as `ADR-005` defines it,
  unaffected by anything this ADR produces in real time. This ADR's
  aggregate view may inform a **future, human-reviewed, versioned**
  configuration change to Risk Engine's ceilings — never an automatic
  one, and never a runtime read of this ADR's output by Risk Engine's
  live decision path. Introducing such a live read would violate
  `ADR-005`'s own Hard Rule ("no self-adjusting risk without versioned
  configuration ... never runtime adaptation") and would make this ADR a
  second, competing sizing authority — exactly what `ADR-001`'s
  single-authority principle forbids.
- **Compliance Engine's Maximum Positions (`ADR-006` §13) remains the
  sole blocking authority on position count/exposure.** This ADR's
  "maximum concurrent exposure" is a monitored metric surfaced in
  `ExposureSummary`/`PortfolioHealth` — it never blocks a trade, and it
  never becomes a second gate a candidate must pass.

---

# 8. Correlation

- **Correlation calculation ownership** — the underlying methodology
  (what counts as a correlation bucket, how correlated exposure is
  measured) belongs to Risk Engine (`ADR-005` §11, itself citing
  `phantom/guards.py`'s correlation-bucket concept as an idea). **This
  ADR reuses that same methodology and definitions, never a
  competing, independently-defined notion of correlation** — the same
  "shared methodology, different aggregation scope, not duplicated
  logic" relationship `ADR-013` §8 already established between Data
  Pipeline's ingestion-time validation and Scanner's own checks.
- **Correlation budgets, correlation limits** — Risk Engine applies
  these per-candidate (sizing-only); this ADR applies the same
  definitions across the whole current portfolio (monitoring-only, §7).
- **Portfolio concentration, cross-strategy concentration,
  cross-account concentration** — aggregate views built from the same
  underlying correlation/exposure data, never a new, separately-computed
  metric family.

---

# 9. Capital allocation

- **Portfolio budgets, strategy budgets, symbol budgets, currency
  budgets** — recommended allocations (`CapitalBudget`, §5), advisory
  only (§7).
- **Dynamic allocation, static allocation** — configuration concerns
  (which mode is active), architecture only, no formula.
- **Reserved capital, recovery capital** — a recommended buffer this ADR
  may suggest holding back from new allocation (e.g. during an elevated-
  drawdown period) — **a recommendation only.** Actual enforcement of
  any capital constraint remains Risk Engine's per-trade sizing (via its
  own versioned configuration) or Compliance Engine's drawdown/kill-
  switch blocking (`ADR-006` §7, §14) — never this ADR acting directly.

---

# 10. Portfolio health

`PortfolioHealth` (§5) assesses:

- Portfolio heat, diversification, concentration, correlation, drawdown,
  liquidity, capital utilization — each a read-only, aggregate
  assessment over already-recorded data (§4), never a live gate.

---

# 11. Relationship to Dashboard — a flagged gap, not silently assumed

`ADR-012` (Accepted) already displays portfolio-level statistics (a
"Risk" view showing "portfolio heat, sizing distribution" and a
"Portfolio Summary" observability item) **attributed to Analytics**
(`ADR-012` §4's data-source model names only Prometheus and Analytics).
Now that this ADR formally defines Portfolio Manager as the actual
authority computing whole-portfolio statistics, **`ADR-012` does not yet
name Portfolio Manager as a data source.** This is a genuine gap,
flagged here rather than silently assumed resolved — the same treatment
given to `ADR-013`'s shadow-trading gap before its own amendment. Closing
it requires a future `ADR-012` amendment (adding Portfolio Manager as a
third read-only data source, mirroring its existing Prometheus/Analytics
model) — not assumed or performed by this ADR.

---

# 12. Agent classification

Per `ADR-014` §3's Agent Classes, Portfolio Manager is classified as an
**Infrastructure Agent** — its defining property (§3's table: "No —
operational/observational only") matches exactly, even though its
domain (portfolio-level capital monitoring) differs from Watchdog's
(health) and Dashboard's (visibility). Classification here is by
decision-authority criterion, not subject-matter domain — the same
reasoning `ADR-018` §11 already applied to classify itself as a
Governance Agent. No amendment to `ADR-014`'s six-class taxonomy is
required.

---

# 13. Security

- **Read-only toward the trading pipeline. No broker credentials. No
  execution authority. No MT5 authority.** (Hard Rules.)
- All inputs (§4) are read-only; no output (§5) can be mistaken for or
  used as a live trading instruction (§5's type-level guarantee).
- No credentials of any kind toward MT5 — the same "not that stage"
  boundary `ADR-013` §13 already states for itself relative to MT5
  Bridge (`ADR-008` §10's sole order-placement authority).

---

# 14. Observability

Every portfolio decision includes:

- `trace_id`
- `portfolio_id`
- `timestamp`
- `strategy_set`
- `allocation_version`
- `reason_codes`

Metrics (export-only, additive, the same discipline established at
every prior stage): portfolio heat, exposure by symbol/currency/sector,
correlation-bucket exposure, capital utilization, diversification score,
allocation-recommendation count.

---

# 15. Testing

- **Correlation correctness test** — Portfolio Manager's aggregate
  correlation output matches Risk Engine's own methodology (§8) applied
  across the current open-position set.
- **Allocation reproducibility test** — identical portfolio state and
  configuration produce identical `PortfolioAllocation`/`CapitalBudget`.
- **Portfolio determinism test** — the same discipline `ADR-002` §14
  established for Scanner, applied here: identical inputs always produce
  identical outputs.
- **Budget correctness test** — recommended budgets never exceed
  configured ceilings.
- **Exposure correctness test** — `ExposureSummary` totals match the sum
  of currently open positions' individual exposures.
- **Diversification correctness test** — diversification/concentration
  metrics are internally consistent (e.g. concentration and
  diversification scores do not simultaneously indicate contradictory
  states for the same portfolio).
- **Multi-account correctness test** — aggregation across accounts
  (§6) never conflates one account's exposure with another's when
  per-account reporting is requested.
- **Boundary/type-level test** — no output type (§5) can hold a trade
  instruction, a modified upstream decision field, or an automatic-
  configuration-change instruction.
- **No-feedback-loop test** — a dedicated test asserting no code path
  exists by which `CapitalBudget`/`PortfolioRecommendation` is read by
  Risk Engine's, Compliance Engine's, or any pipeline stage's live
  decision path (§7).

---

# 16. Architectural invariants

- Portfolio Manager owns only portfolio-level decisions.
- Trade-level decisions remain owned by the deterministic pipeline.
- Portfolio Manager never creates trades.
- Portfolio Manager never executes trades.
- Portfolio Manager never bypasses Compliance.
- Portfolio Manager never bypasses Risk.

---

# 17. Acceptance criteria

ADR-017 is acceptable only if it guarantees:

- ✓ Portfolio allocation deterministic (§15).
- ✓ Correlation reproducible (§8, §15).
- ✓ Exposure reproducible (§15).
- ✓ Budget calculations reproducible (§9, §15).
- ✓ No live trading authority (§1, §3, §7, §13).

---

# 18. Reference material — ideas only, not authority

- **No legacy portfolio-management implementation exists anywhere in
  this repository** (verified: `phantom/guards.py`'s correlation-bucket
  concept and `phantom/risk.py`'s per-candidate sizing are the closest
  analogues, and both are already cited as reference-only ideas by
  `ADR-005`). As with every infrastructure-layer ADR this session
  (`ADR-008`, `ADR-009`, `ADR-011`, `ADR-012`, `ADR-013`, `ADR-014`,
  `ADR-018`), there is no legacy module to mine for ideas — this stage
  is designed entirely from first principles.
- `ADR-005` §5/§9/§10/§11's own forward references to this ADR are the
  direct specification this ADR fulfills, not a reference idea — a
  binding contract, the same relationship `ADR-013` had to `ADR-002`
  §4's forward reference.
- Institutional portfolio-management concepts (value-at-risk aggregation,
  correlation-adjusted position sizing, diversification scoring) inform
  this design's vocabulary only — no specific formula, threshold, or
  vendor methodology is authoritative here, consistent with `CLAUDE.md`
  §7's "not invented here" discipline for implementation-time numerics.

---

Per `ADR-001` and `CLAUDE.md` §1.10, **no implementation begins until this
ADR's Status changes from Proposed to Accepted.**
