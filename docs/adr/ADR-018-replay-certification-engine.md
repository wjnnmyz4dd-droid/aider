# ADR-018 — Replay & Certification Engine

Status: Accepted

Acceptance Date: 2026-07-04

Accepted By: Software Architect / Phantom Engineering Council

Owner: Test Results Analyzer (per the Gap Audit's own recommendation,
`ARCHITECTURE-GAP-AUDIT-2026-07-04.md` §2.5/§3: "statistical/regression
validation is already its lane per `TEAM.md`")

Reviewed by: Software Architect (mandatory — the Gap Audit's own
recommendation names this role "cross-cutting reviewer," and a new
stage crossing package boundaries requires this per `TEAM.md` §3),
Security Architect (Consulted — the promotion-chain touchpoint with
`ADR-019`'s Research Agent sits on the same AI Research Governance
boundary Security Architect already owns per the Gap Audit §2.7)

Date: 2026-07-04

Depends on: `ADR-001-single-authority-architecture.md` (Accepted —
determinism, the precondition this ADR's entire validation model rests
on, `ADR-002` §14), `ADR-002-scanner.md` (Accepted — replay-determinism
requirement), `ADR-003-strategy-engine.md` (Accepted — the promotion
target: a certified strategy becomes a new playbook here, never a
direct port), `ADR-010-analytics-decision-provenance.md` (Accepted —
§8's forward-declared replay-input owner this ADR consumes and, per
that same section, is the actual execution/certification consumer of),
`ADR-013-data-pipeline.md` (Accepted — §10's forward-declared replay-
data-production owner this ADR consumes), `docs/adr/ADR-014-multi-agent-
governance.md` (Accepted — classifies this ADR's own agent as a
Governance Agent, §13 below, and its "no Governance Agent may itself
accept an ADR" Hard Rule is the direct precedent this ADR's "never
promotes automatically" rule extends to strategy promotion),
`docs/adr/ADR-015-external-data-sources-api-governance.md` (Accepted —
Database storage for `CertificationHistory`/`EvidencePackage`, §14
below), `docs/adr/ADR-019-self-evolving-market-structure-research-agent.md`
(Proposed — the reference Research Agent submitting proposals to this
ADR; its Proposed status is preserved here, not upgraded)

---

# Pipeline position

**The Replay & Certification Engine is not part of the live trading
pipeline.** Like Watchdog (`ADR-011`), Dashboard (`ADR-012`), and
Multi-Agent Governance (`ADR-014`), it is cross-cutting — but where
those govern operational health, visibility, and authority
respectively, this ADR governs **evidentiary trust**: whether a
proposed strategy or architectural change has demonstrated enough proof
to be promoted toward production. **It consumes historical information
only** (with one explicitly bounded exception, §8's shadow trading) **and
has zero authority over live trading.**

---

# 1. Mission

**The Replay & Certification Engine answers exactly one question: "Has
a strategy or architectural change demonstrated sufficient evidence to
be promoted toward production?"**

**It never answers:** Should we trade? Should we execute? Should we
override Compliance? Should we bypass Risk? Those are, respectively,
Strategy/Scoring/Risk Engines', Execution Validator's/MT5 Bridge's,
Compliance Engine's, and Risk Engine's questions — each already answered
by its own Accepted ADR, none of them touched by this one. This ADR
evaluates evidence about a *proposed* strategy or change; it never
becomes, replaces, or overrides the stage that would actually run it.

---

# Hard Rules

These override any other requirement in this document if they ever
appear to conflict:

- **The Certification Engine SHALL NEVER:** execute trades, modify live
  strategies, modify risk, modify compliance, modify execution, promote
  automatically, deploy automatically, or override Human Review (§4).
- **Certification never deploys. Certification never trades.
  Certification never changes production.** It evaluates evidence and
  produces a recommendation — nothing more.
- **Promotion is never automatic.** Every promotion requires evidence, a
  certification report, replay success, regression success, **and Human
  approval** — the same "no Governance Agent may itself accept" pattern
  `ADR-014`'s Hard Rules already establish for ADR acceptance, extended
  here to strategy/architecture promotion: this ADR's own agent
  recommends; a human, acting through the Engineering Council process,
  decides.
- **`ADR-019` may submit research. This ADR evaluates evidence. This ADR
  never performs research.** Research generation remains entirely
  `ADR-019`'s (and, before that, the isolated Vibe-Trading lab's,
  `ADR-015` §6) domain.

---

# 2. Responsibilities

The Certification Engine SHALL own:

- Historical replay, decision replay, market replay, trade replay.
- Replay verification.
- Walk-forward testing, Monte Carlo testing, bootstrap analysis.
- Shadow trading evaluation (§8 — the one bounded live-data exception).
- Certification workflow, promotion recommendation.
- Evidence preservation, certification history.
- Regression testing, benchmark comparison.

---

# 3. The Certification Engine shall never

| Forbidden action | Owned instead by |
|---|---|
| Execute trades | MT5 Bridge (`ADR-008`) |
| Modify live strategies | Strategy Engine (`ADR-003`) |
| Modify risk | Risk Engine (`ADR-005`) |
| Modify compliance | Compliance Engine (`ADR-006`) |
| Modify execution | Execution Validator (`ADR-007`) |
| Promote automatically | Human Review (`ADR-014` §7) |
| Deploy automatically | Human Review + `TEAM.md`'s existing Deployment workflow (§2) |
| Override Human Review | Human Review (`ADR-014` §7) — absolute |

---

# 4. Inputs

- **Analytics history** (`ADR-010`) — the archived, immutable decision-
  provenance chain (`TradeProvenanceRecord`), read-only, for regression
  comparison against real historical performance.
- **Replay data** (`ADR-013` §5, §10) — `ReplaySeries`: captured,
  normalized historical ticks/bars/snapshots, read-only.
- **Research proposals** (`ADR-019`) — a candidate strategy/parameter
  set submitted for evaluation, read-only; this ADR never generates one
  itself.
- **Historical market data** — bulk historical data via `ADR-013`'s
  `HistoricalSeries`, for backtesting windows beyond what `ReplaySeries`
  alone captures.
- **Historical decisions** — the same Analytics-archived chain above,
  named separately here because it is consumed for two distinct
  purposes: reconstructing what happened (replay) and comparing outcomes
  (regression/benchmark).

---

# 5. Outputs

One record per certification run, never discarded — the same discipline
established at every prior stage.

- **`ReplayResult`** — the outcome of re-running a stage's already-
  Accepted deterministic logic against archived inputs: whether it
  reproduced the original recorded decision, byte-for-byte.
- **`CertificationReport`** — the full evidentiary record for one
  candidate at one certification level (§6): which validations (§8) were
  run, their results, and the level the evidence supports.
- **`PromotionRecommendation`** — a recommendation only, never a
  decision — whether the evidence, in this agent's assessment, supports
  promotion to the next certification level. Human Review may accept,
  reject, or request further evidence; it is never bound by this
  recommendation.
- **`EvidencePackage`** — the durable, retained bundle of everything a
  human needs to make a promotion decision: `ReplayResult`s, statistical
  test outputs, the dataset/configuration/ADR-version identifiers used
  (§13).
- **`ReplayMetrics`** — performance statistics computed over a replayed/
  backtested run (Win Rate, Profit Factor, Sharpe, Sortino, MAE, MFE,
  Drawdown — the same vocabulary `ADR-010` §9 already defines for
  *live* trades, reused here for consistency so a certified strategy's
  backtested numbers are later comparable to its real Analytics numbers,
  never a competing definition).
- **`CertificationHistory`** — the permanent, append-only record of
  every certification level transition for every candidate, stored
  per `ADR-015` §6's Database entry.

**Type-level guarantee:** none of these output types is structurally
capable of holding a trade instruction, a live risk/compliance/execution
decision, or an automatic deployment action — the same guarantee
established for every prior stage's output type, verified by a
dedicated test (§16).

**Immutability:** every output type, once produced, is immutable — a
permanent record of an evaluation, never a mutable working object.

---

# 6. Certification levels

| Level | Meaning | Entry requires | May do |
|---|---|---|---|
| **Experimental** | A raw hypothesis, not yet formally evaluated. | Nothing beyond existing inside the isolated research lab (`ADR-015` §6, `ADR-019`). | Nothing outside the research lab. |
| **Research** | Has undergone research-lab-side backtesting (`ADR-019`'s own scope). | `ADR-019`'s own research process producing a report. | Submission to this ADR as a candidate (§4). |
| **Candidate** | Formally submitted for certification. | A `ADR-019` (or human-authored architectural-change) proposal accepted as input (§4). | Replay/statistical validation (§8) may begin. |
| **Validated** | Has passed replay-determinism and statistical validation (§8). | All of §8's applicable validations pass. | A `CertificationReport` may be produced. |
| **Certified** | This agent's full evidentiary assessment is complete. | A complete `CertificationReport` and `PromotionRecommendation` exist. | Presentation to Human Review for a promotion decision — **still no live authority.** |
| **Production Approved** | A human has explicitly approved promotion. | Human Review approval (`ADR-014` §7), **and** the normal `TEAM.md` engineering process (Minimal Change Engineer implements the new playbook per `ADR-003`, Code Reviewer reviews) — certification never substitutes for that process. | Live deployment, through the normal engineering pipeline — never performed by this agent. |
| **Retired** | A previously Certified/Production-Approved item has been formally deprecated. | Human Review decision, mirroring `ADR-014` §9's new `Deprecated` ADR-status concept applied to a strategy/change rather than an ADR. | Nothing live; retained for historical/audit reference, never deleted (`CLAUDE.md` Phantom Protocol rule 2). |

**No level, on its own, ever authorizes live trading.** Only "Production
Approved," reached through Human Review **and** the normal engineering
process, does — and even then, this agent performs neither the
implementation nor the deployment.

---

# 7. Promotion

Promotion to the next certification level (§6) requires **all** of:

- Evidence (a complete `EvidencePackage`).
- A `CertificationReport`.
- Replay success (§8).
- Regression success (§8).
- **Human approval** (`ADR-014` §7) — **never automatic**, at any level
  transition, without exception.

---

# 8. Validation

- **Replay integrity** — the replayed inputs (`ReplaySeries`,
  Analytics-archived decisions) are confirmed complete and unmodified
  before any validation runs, per `ADR-010` §6's "nothing may be
  omitted" and `ADR-013` §5's immutability guarantee.
- **Determinism verification** — re-running a stage's already-Accepted
  logic against archived inputs reproduces the original recorded
  decision byte-for-byte (`ReplayResult`) — the concrete fulfillment of
  `ADR-002` §14's replay-determinism requirement, extended to every
  stage that carries the same requirement.
- **Walk-forward testing** — out-of-sample validation across sequential
  historical windows, closing the exact gap `TEAM.md` §6 already
  identified ("whether a playbook's win rate/profit factor reflects a
  real statistical edge or curve-fitting").
- **Monte Carlo testing** — resampling/simulation-based robustness
  assessment of the candidate's statistical edge.
- **Bootstrap analysis** — resampling-based confidence-interval
  estimation for the candidate's performance statistics (§5,
  `ReplayMetrics`).
- **Shadow trading evaluation — the one explicitly bounded exception to
  "historical only."** Shadow trading observes **real-time** market data
  (via `ADR-013`'s `MarketSnapshot`, the same shared object Compliance
  Engine and Execution Validator already consume) to compare a
  candidate's hypothetical decisions against live conditions, without
  ever executing, without ever holding broker credentials, and without
  ever being visible to or influencing the live pipeline. **This is a
  genuine, flagged gap against `ADR-013`'s own text, not a silently
  assumed capability:** `ADR-013` §9's multi-consumer model enumerates
  Scanner, Compliance Engine, and Execution Validator/MT5 Bridge as
  `MarketSnapshot` consumers — it does not yet name this ADR. Adding
  this agent as a fourth `MarketSnapshot` consumer requires a future
  amendment to `ADR-013` (mirroring the `ADR-002` Amendment 1 / `ADR-008`
  Amendment 1 precedent), not assumed here.
- **Regression comparison** — a proposed architectural change's replayed
  performance is compared against Analytics' real historical performance
  for the same historical window, using the shared `ReplayMetrics`
  vocabulary (§5).
- **Historical consistency** — repeated historical loads/replays of the
  same range and configuration produce identical results (mirrors
  `ADR-013` §16's Historical consistency test).

**This ADR fulfills, and supersedes as a formal architecture, `TEAM.md`
§6's lightweight-checklist recommendation** for the same gap (minimum
sample size, walk-forward split, multi-strategy-comparison correction).
That checklist's substance is subsumed into this section rather than
existing as a separate, lighter mechanism alongside it — `TEAM.md` §6
should be read as historically informative, not as a second, competing
validation process once this ADR is Accepted.

---

# 9. Relationship to research (`ADR-019`)

**`ADR-019` may submit research. This ADR evaluates evidence. This ADR
never performs research.** `ADR-019`'s own text already forward-declares
this dependency ("this agent's mandate ... depends on ... the Replay
Engine (`ADR-018`) once drafted ... it is a **consumer** of those future
capabilities, never a substitute for them") — this ADR is the
fulfillment of that forward reference, in the opposite direction:
`ADR-019` submits candidates; this ADR evaluates them; neither performs
the other's function.

---

# 10. Relationship to Analytics' and the Data Pipeline's replay ownership

Restated, not redefined, from `ADR-010` §8 and `ADR-013` §10, both of
which already forward-declared this ADR as their consumer:

- **Analytics (`ADR-010` §8)** owns replay **decision inputs** — the
  archived `ScannerObservation` through `PositionManagementDecision`
  chain.
- **The Data Pipeline (`ADR-013` §10)** owns replay **data production**
  — the raw `ReplaySeries` ticks/bars/snapshots.
- **This ADR** is the actual execution/certification engine that
  re-runs stage logic against both and certifies the result — the scope
  both of those ADRs deliberately declined to claim for themselves.

---

# 11. Agent classification

Per `ADR-014` §3's Agent Classes, the Replay & Certification Engine is a
**Governance Agent** — specifically, the formalized, dedicated tooling
extension of Test Results Analyzer's existing `TEAM.md` role
(statistical/regression validation), not a new agent class. It governs
the *development/promotion process* (whether evidence justifies
promoting a strategy or architectural change), matching `ADR-014` §3's
own definition of Governance Agents' scope exactly: "governs the
development process ... never a live trading decision." No amendment to
`ADR-014`'s six-class taxonomy is required.

---

# 12. Security

- **Read-only. Historical only** (with §8's one bounded, explicitly-
  flagged real-time exception). **No broker authority. No production
  authority.** (Hard Rules.)
- **No order-placement credentials, ever** — mirrors `ADR-008` §10's
  "sole stage with order-placement capability" boundary; this agent is
  not that stage and must never be granted its capability, even for
  shadow trading (§8), which observes but never submits.
- **Database access** for `CertificationHistory`/`EvidencePackage`
  storage is scoped read/write to this agent's own schema only, per
  `ADR-015` §6's Database entry and §9's least-privilege principle —
  never broad access to Compliance Engine's or Analytics' own stored
  state.
- **No network egress beyond the approved sources in §4** and, for
  shadow trading, the same `MarketSnapshot` read path already governed
  by `ADR-013`/`ADR-015` — no new external dependency is introduced by
  this ADR.

---

# 13. Observability

Every certification includes:

- `trace_id`
- `strategy_id`
- `dataset`
- `configuration`
- `ADR versions` — which version/amendment of every relevant stage ADR
  was in effect for this certification run, the same discipline
  `ADR-010` §2 already requires for its own collected objects.
- `results`
- `timestamp`

---

# 14. Testing

- **Replay determinism test** — identical archived inputs reproduce
  identical `ReplayResult`s across repeated runs.
- **Historical consistency test** — repeated historical loads/replays of
  the same range and configuration produce identical results.
- **Regression reproducibility test** — a regression comparison run
  against the same Analytics baseline and the same candidate produces
  identical `ReplayMetrics` deltas across repeated runs.
- **Certification reproducibility test** — re-running an entire
  certification workflow against the same inputs and configuration
  produces an identical `CertificationReport`.
- **Evidence completeness test** — an `EvidencePackage` missing any
  required validation result (§8) is flagged incomplete, never presented
  as sufficient for a `PromotionRecommendation` — the same "nothing may
  be omitted" discipline `ADR-010` §6 already established.
- **Boundary/type-level test** — no output type (§5) can hold a trade
  instruction, a live decision, or an automatic-deployment action.

---

# 15. Architectural invariants

- Certification never deploys.
- Certification never trades.
- Certification never changes production.
- Certification evaluates only evidence.

---

# 16. Acceptance criteria

ADR-018 is acceptable only if it guarantees:

- ✓ Every certification reproducible (§14).
- ✓ Every replay deterministic (§8, §14).
- ✓ Every promotion human-approved (§7, §14).
- ✓ No production authority (§1, §3, §12).

---

# 17. Reference material — ideas only, not authority

- **No legacy replay/certification engine exists anywhere in this
  repository** (verified: no backtesting, walk-forward, or certification
  tooling in `phantom/` or `phantom_institutional.py` beyond ad hoc
  research-side scripts referenced in `docs/research/
  VIBE-TRADING-EVALUATION.md`). As with every infrastructure-layer ADR
  this session (`ADR-008`, `ADR-009`, `ADR-011`, `ADR-012`, `ADR-013`,
  `ADR-014`), there is no legacy module to mine for ideas — this stage
  is designed entirely from first principles.
- `ARCHITECTURE-GAP-AUDIT-2026-07-04.md` §2.5's own analysis — "a
  documented requirement (§14's 'mandatory for ... certification') with
  no architecture yet built to satisfy it" — is the direct origin of
  this ADR; its recommended owner (Test Results Analyzer) and dependency
  list (every stage's determinism guarantee, Analytics, `ADR-015`'s
  Database entry) are followed here, not reinvented.
- `docs/research/VIBE-TRADING-EVALUATION.md`'s existing research →
  backtest → report → human approval → reimplementation chain is the
  direct idea behind §6's certification-level progression and §7's
  promotion requirements — restated at the formal-architecture level,
  not redesigned.

---

Per `ADR-001` and `CLAUDE.md` §1.10, **no implementation begins until this
ADR's Status changes from Proposed to Accepted.**
