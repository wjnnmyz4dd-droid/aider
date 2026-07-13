# ADR-003 — Strategy Engine

Status: **Accepted**

Owner: Multi-Agent Systems Architect (per `.claude/agents/TEAM.md` RACI,
Strategy Orchestrator row — Accountable)

Reviewed by: Software Architect (cross-module boundary sign-off, per
`TEAM.md` §2 — any new engine requires this)

Date: 2026-07-04

Acceptance Date: 2026-07-04

Accepted By: Software Architect / Titan Protocol Engineering Council

Depends on: `ADR-001-single-authority-architecture.md` (Accepted),
`ADR-002-scanner.md` (Accepted)

---

# Pipeline position

Market Data → Scanner → **Strategy Engine** → Scoring Engine → Risk Engine
→ Compliance Engine → Execution Validator → MT5 Bridge → Position Manager
→ Analytics

This ADR defines only the Strategy Engine stage. It consumes the
Scanner's output (`ADR-002`) and produces input for the Scoring Engine
(ADR-004). It does not define either neighbor.

---

# 1. Mission

**The Strategy Engine answers exactly one question: "Given the Scanner's
observations, what trade hypotheses exist?"**

It must never answer:

- Should we trade?
- Which strategy wins?
- How much should we risk?
- Is this compliant?
- Should this execute?
- How should the position be managed?

Every one of those questions belongs exclusively to a later stage
(Scoring Engine, Risk Engine, Compliance Engine, Execution Validator, and
Position Manager, respectively). The Strategy Engine is a **hypothesis
generator**, not a decision-maker. Zero, one, or many hypotheses from
zero, one, or many playbooks in a single call are all correct, healthy
outcomes — the Strategy Engine does not try to reduce multiplicity to a
single answer. That reduction is Scoring Engine's job (§9).

---

# 2. Core Architectural Principles

The Strategy Engine, and every playbook within it, must be:

- **Deterministic** — the same `ScannerObservation` input always produces
  the same set of `CandidateTrade` outputs.
- **Stateless** — no state is carried between calls; each invocation is
  independent. This extends `ADR-002`'s Scanner Purity Principle to this
  stage.
- **Pure** — output is solely a function of the declared inputs
  (`ScannerObservation` plus configuration, §13), nothing else.
- **Testable** — every playbook, and the engine itself, is testable in
  complete isolation using fixture `ScannerObservation`s.
- **Replaceable** — any playbook can be swapped or removed without
  touching any other playbook or the engine's own code.
- **Independent** — playbooks share no mutable state, never call each
  other, and do not know of each other's existence.
- **Extensible** — new playbooks integrate purely through the Strategy
  Registry (§7); zero engine modification (§17).

Explicitly forbidden, as concrete mechanisms rather than abstractions:

- **No randomness** — no RNG-based tie-breaking, sampling, or
  exploration anywhere in a playbook's logic.
- **No hidden state** — no module-level caches, singletons, or counters
  that carry information between calls.
- **No learning** — no online model updates, no confidence adaptation
  from past outcomes. Consistent with the standing prohibition on
  automatic parameter optimization (`docs/adr/ADR-015-external-data-sources-api-governance.md`
  §7, `.claude/agents/TEAM.md` §6).
- **No adaptive behavior** — a playbook's logic changes only through a
  human-reviewed version bump (§5), never at runtime based on results.
- **No cached decisions** — no memoizing a prior call's `CandidateTrade`
  for reuse on a later, distinct call.

---

# 3. Responsibilities

**The Strategy Engine SHALL:**

- Consume `ScannerObservation` objects.
- Execute one or more independent playbooks.
- Produce `CandidateTrade` objects (§6).
- Attach strategy metadata (which playbook, which version).
- Attach supporting evidence (which specific Scanner facts triggered the
  hypothesis).
- Record reasoning metadata — a human-readable narrative connecting
  evidence to the hypothesis, distinct from evidence itself, useful for
  debugging and Analytics without being, or becoming, a score (see §4's
  review note on this distinction).

**The Strategy Engine SHALL NEVER:**

| Forbidden action | Owned instead by |
|---|---|
| Score trades | Scoring Engine (ADR-004) |
| Rank trades | Scoring Engine (ADR-004) |
| Approve trades | Compliance Engine (ADR-006) / Execution Validator (ADR-007) |
| Reject trades | Compliance Engine (ADR-006) / Execution Validator (ADR-007) |
| Allocate risk | Risk Engine (ADR-005) |
| Calculate lot size | Risk Engine (ADR-005) |
| Calculate SL/TP | Risk Engine (ADR-005) |
| Perform compliance | Compliance Engine (ADR-006) |
| Execute trades | MT5 Bridge (ADR-008) |
| Communicate with MT5 | MT5 Bridge (ADR-008) |
| Manage positions | Position Manager (ADR-009) |
| Generate analytics | Analytics (ADR-010) |

---

# 4. Pipeline Contract

## Scanner → Strategy Engine

- **Required inputs:** one or more `ScannerObservation` objects
  (`ADR-002` §8), for the symbol(s)/timeframe(s) a given playbook is
  configured to consume.
- **Guaranteed outputs (trusted from Scanner):** referential transparency,
  fail-closed `data_quality_flag`, and no fabricated readings, per
  `ADR-002` §2 and §10. The Strategy Engine must itself treat any
  non-nominal `data_quality_flag` as an automatic **no-hypothesis**
  condition for that observation — this is the contract `ADR-002` §10
  established for this exact stage to honor.
- **Failure behavior:** if a required `ScannerObservation` field is
  missing or degraded, the playbook(s) requiring it produce no
  `CandidateTrade` for that call. They do not guess, degrade silently, or
  substitute a default.
- **Versioning:** `ScannerObservation` carries `schema_version`
  (`ADR-002` §8). Each playbook declares which schema version(s) it is
  compatible with. A playbook encountering an incompatible
  `schema_version` fails closed (no hypothesis) rather than attempting
  best-effort parsing.
- **Backward compatibility:** a new `ScannerObservation` field must be
  additive — safe for a playbook unaware of it to ignore. A breaking
  Scanner change requires a new `schema_version` and coordinated update,
  per `ADR-002`'s own versioning discipline.
- **Interface ownership:** Multi-Agent Systems Architect (this ADR) and
  Software Architect (`ADR-002`) jointly own this boundary — a change on
  either side requires both to sign off, per `TEAM.md` §4's two-tier
  architecture rule.

## Strategy Engine → Scoring Engine

- **Required inputs (from Scoring Engine's perspective):** zero or more
  `CandidateTrade` objects per call.
- **Guaranteed outputs:** every forwarded `CandidateTrade` is well-formed
  per §6's data model and structurally incapable of carrying a
  score/approval/size/SL-TP/execution instruction — the same type-level
  guarantee `ADR-002` §8 established for `ScannerObservation`, applied
  here.
- **Failure behavior:** a playbook failure (§10) never causes the
  Strategy Engine to forward a malformed or partial `CandidateTrade` —
  the failed playbook's contribution is simply absent, never a guess.
- **Versioning:** `CandidateTrade` carries its own `schema_version`,
  independent of `ScannerObservation`'s, so Scoring Engine can evolve
  independently of the Strategy Engine.
- **Backward compatibility:** same additive-field discipline as above.
- **Interface ownership:** Multi-Agent Systems Architect is accountable
  for keeping this contract stable until ADR-004 is drafted and assigns
  its own owner for the Scoring Engine side of the boundary.

---

# 5. Playbook Architecture

A plugin interface every playbook must expose (conceptual only — no
implementation code):

- **Strategy ID** — stable, unique identifier, independent of any display
  name; persists across versions.
- **Version** — the playbook's own version number, independent of the
  engine's version.
- **Description** — human-readable summary of the hypothesis category it
  looks for.
- **Inputs** — which `ScannerObservation` fields it reads.
- **Outputs** — confirmation that it produces only `CandidateTrade`
  objects (§6), nothing else.
- **Required Scanner observations** — fields that must be present and
  nominal for the playbook to run at all; absence means no hypothesis,
  never a degraded attempt.
- **Optional Scanner observations** — fields that enrich a hypothesis's
  evidence/reasoning if present, but are non-blocking if absent.
- **Supported symbols** — explicit list or pattern; a playbook must never
  silently run against a symbol it wasn't designed for.
- **Supported timeframes** — same discipline, explicit.
- **Configuration schema** — the playbook's own tunable parameters
  (thresholds, lookback windows), versioned alongside the playbook.
- **Failure conditions** — explicit enumeration of what causes the
  playbook to abstain (produce nothing) versus what would indicate a true
  implementation bug (an exception) — feeds directly into §10.
- **Health status** — a simple, queryable status (e.g. healthy / degraded
  / disabled) the registry and Watchdog (ADR-011) can observe,
  independent of any single call's outcome.

---

# 6. `CandidateTrade`

**Allowed fields:**

- Direction hypothesis (a hypothesis, not a decision — e.g. an
  up/down/none-equivalent value).
- Entry concept (a described zone/level/condition, not an order).
- Strategy ID (§5).
- Supporting observations (references to the specific
  `ScannerObservation` facts that triggered this hypothesis).
- Evidence (structured data backing the hypothesis).
- Reason codes (short, enumerable codes — e.g. an identifier for "sweep
  plus change-of-character" — distinct from free-text reasoning).
- Metadata (`schema_version`, timestamp, symbol, timeframe, playbook
  version, `trace_id` per §12).

**Forbidden fields**, each owned instead by the stage in §3's table:

- Score, Approval, Ranking, Risk, Lot size, Stop Loss, Take Profit,
  Compliance, Execution commands, MT5 instructions.

**Type-level guarantee:** `CandidateTrade`'s data model must be
structurally incapable of holding any forbidden field — verified by a
dedicated test (§16), not just behavioral testing, mirroring `ADR-002`
§8's guarantee for `ScannerObservation`.

`CandidateTrade`, once produced, is **immutable** through the rest of the
pipeline. Later stages attach their own data (scores, sizes, approvals)
alongside it; they never rewrite it (§18).

---

# 7. Strategy Registry

- **No hard-coded strategy lists.** The engine itself must not contain an
  explicit list of playbook names or classes. This directly prevents the
  class of defect already on record in the reference material —
  `titan_protocol/analytics.py`'s `STRATEGIES` tuple drifted out of sync with the
  actual playbook roster (`.claude/agents/TEAM.md` §8) — from recurring
  at this stage.
- **Automatic discovery** — playbooks register themselves, or are
  discovered via a defined convention, without the engine needing a
  manually maintained list. (The reference material's
  `titan_protocol/strategies/orchestrator.py` discovery pattern is a useful idea
  here, not an authority, per `ADR-001`.)
- **Version controlled** — the registry records each playbook's declared
  version (§5); upgrading a playbook is a version bump, not a silent
  behavior change.
- **Configuration driven** — which playbooks are active, and their
  tunable parameters, come from configuration (§13), not code changes.
- **Enable/disable support** — a playbook can be disabled without
  deleting it or touching any other playbook.
- **Future-proof:** adding a playbook means adding a new module
  satisfying §5's interface and registering it — zero changes to the
  Strategy Engine's own code, the registry's own code, or any other
  playbook.

## Duplicate Strategy ID Handling

- **Every Strategy ID must be globally unique.** Uniqueness is a registry
  invariant, not a convention.
- **Duplicate registration is a configuration error**, not a runtime
  condition the engine tolerates or works around.
- **Duplicate IDs are detected during registry initialization** — before
  any playbook runs, not discovered lazily at call time.
- **Registry initialization fails fast.** A duplicate Strategy ID halts
  registry startup; it does not proceed with a partially-loaded registry.
- **The duplicate strategy is never loaded.** Neither conflicting
  registration is silently activated — detection blocks both, not just
  the second one seen.
- **Log a structured error** containing both conflicting Strategy IDs,
  their names, and their versions — sufficient detail to resolve the
  conflict without re-deriving it from source.
- **No automatic replacement.** The registry never silently substitutes
  one conflicting playbook for another.
- **No "last one wins" behavior.** Registration order must never
  determine which playbook survives a conflict — that would make registry
  behavior depend on incidental load order, violating determinism (§2).
- **Registry behavior remains deterministic** — the same set of playbook
  modules, registered in any order, produces the same
  fails-to-initialize outcome and the same structured error content.
- **Duplicate IDs require explicit developer resolution** — renaming or
  removing one of the conflicting playbooks — before the registry, and
  therefore the Strategy Engine, can start at all.

This closes the gap identified in this ADR's architectural review: prior
to this addition, §5 and §7 did not define what happens when two
playbooks register under the same Strategy ID.

---

# 8. Initial Playbooks — placeholders only, no implementation

Reserved Strategy IDs and conceptual roles only. No logic, no thresholds,
no implementation code. Note: these are fresh, first-principles
placeholders, not a renaming of the reference material's five playbooks —
per `ADR-001`, neither `titan_protocol/` nor `phantom_institutional.py` is
authoritative, so no 1:1 mapping to the old playbook set should be
assumed.

- **ORB** — hypothesis category: a session's opening-range breakout as a
  directional trigger.
- **Liquidity Reversal** — hypothesis category: a liquidity sweep followed
  by a structural reversal signal.
- **Session Breakout** — hypothesis category: a breakout of a prior
  session's range as a directional trigger.
- **Trend Continuation** — hypothesis category: continuation of an
  already-established trend following a pause or pullback.
- **Range Reversal** — hypothesis category: rejection at the boundary of
  an established trading range.

Each is reserved as a Strategy ID and a one-sentence conceptual role only
— design and implementation are out of scope for this ADR.

---

# 9. Conflict Handling

Multiple playbooks may generate `CandidateTrade` objects for the same
symbol at the same instant, including directly opposing ones (one
playbook's hypothesis is LONG, another's is SHORT). **The Strategy Engine
never chooses a winner.** It forwards every valid `CandidateTrade`
unmodified.

This is a deliberate correction over the reference material: the
reference `StrategyEngine.resolve()` consolidated agreeing signals
(`max(score) + confluence bonus`) and dampened conflicting ones — that
consolidation and conflict-resolution logic is explicitly **relocated to
Scoring Engine (ADR-004)**, not carried forward into this stage. The
Strategy Engine's job ends at producing hypotheses; deciding which
hypothesis (if any) matters is Scoring Engine's exclusive responsibility.

---

# 10. Failure Isolation

- A playbook's exception or failure is caught at the playbook boundary,
  logged (§12), and treated as "this playbook abstained" — it never
  propagates to crash the engine or affect any other playbook.
- The engine invokes each playbook independently; no playbook can corrupt
  another playbook's inputs or outputs (a direct consequence of §2's
  independence principle, not a separate mechanism).
- The pipeline as a whole never halts because of a single playbook
  defect — extending `ADR-002` §7's "must not raise on bad input"
  discipline from data input to playbook execution.

---

# 11. Purity Guarantee

Scanner produces facts (`ADR-002`). Strategy Engine produces hypotheses
(this ADR). No overlap, enforced as follows:

- The Strategy Engine must not compute new market-structure facts itself.
  If a playbook needs a derived fact the Scanner doesn't provide, that is
  a gap in `ADR-002`'s contract to raise with the Software Architect —
  never something the Strategy Engine should compute independently. This
  prevents duplicate-computation drift (e.g. two playbooks each
  re-deriving their own swing-pivot detection), which would repeat the
  `swing_points()` defect (`ADR-002` §13) at a new layer.
- No stage leakage: the Strategy Engine performs none of Scoring Engine's,
  Risk Engine's, Compliance Engine's, Execution Validator's, MT5
  Bridge's, or Position Manager's responsibilities — restating §3's table
  as the purity-enforcement lens tying this ADR together.

---

# 12. Logging

- Every `CandidateTrade`, and every playbook's abstention, is logged as a
  structured record.
- Every record shares the `trace_id` established at the Scanner stage
  (`ADR-002` §11), so a single market observation's full journey through
  the Strategy Engine and beyond stays correlated — this extends, rather
  than reinvents, `ADR-002`'s already-established discipline.
- **Strategy lifecycle:** registry events (playbook enabled/disabled/
  version-changed) are logged distinctly from per-call hypothesis
  records.
- **Failure logging:** a caught playbook failure (§10) is logged with
  enough detail (playbook ID, version, input reference) to diagnose
  without blocking the pipeline.
- **Metrics:** counts of `CandidateTrade`s produced, per playbook, per
  direction, per symbol; counts of playbook failures/abstentions.
  Export-only, additive, changes nothing — the same discipline `ADR-002`
  §12 established.
- **Observability requirement:** it must be possible to answer "which
  playbooks fired, which abstained, and why" for any given scan purely
  from logs/metrics, without re-running anything.

---

# 13. Configuration

- **Strategy enable/disable** — per playbook, per environment (e.g. a
  certification/forward-test configuration may differ from a later live
  configuration).
- **Versioning** — which playbook version is active is a
  configuration-visible fact, not buried in code.
- **Symbols / timeframes** — which symbols/timeframes a playbook is
  actually allowed to run against are configured, not hard-coded,
  enforcing §5's declared support at a controllable layer.
- **Feature flags** — a mechanism to enable a new/experimental playbook
  narrowly (e.g. specific symbols only) before wider enablement, without
  an engine code change.
- **Safe defaults** — absent explicit configuration, the default is
  **disabled**, never enabled. An unconfigured playbook produces no
  hypotheses, consistent with the fail-closed philosophy already
  established throughout `ADR-001`/`ADR-002`/`ADR-015`.

---

# 14. Performance

Principles only — no invented latency numbers, per `CLAUDE.md` §7's rule
against guessing unverified figures.

- **Bounded execution** — each playbook completes within a bounded time
  budget; the number itself is set empirically at implementation time
  against real fixture data, not invented here (same discipline as
  `ADR-002` §13).
- **No duplicate computation** — if multiple playbooks need the same
  derived value from a `ScannerObservation`, it is computed once and
  shared, never recomputed per playbook. This explicitly extends
  `ADR-002` §13's `swing_points()` lesson to this stage.
- **Linear scalability** — engine-level execution cost scales linearly
  with the number of enabled playbooks, not combinatorially — a direct
  consequence of playbook independence (§2), not a separate goal to
  engineer for.
- **Minimal allocations** — playbooks avoid unnecessary copying of
  `ScannerObservation` data; observations are immutable (§15) and may be
  referenced rather than duplicated.

---

# 15. Security

- **Trust boundaries** — the Strategy Engine trusts `ScannerObservation`
  as already-validated per `ADR-002`'s fail-closed guarantee, but must
  still treat playbook configuration (§13) as needing validation: a
  malformed configuration fails closed (playbook disabled), never crashes
  or runs with undefined behavior.
- **Immutable Scanner observations** — a `ScannerObservation`, once
  produced, is never mutated by the Strategy Engine or any playbook —
  read-only reference semantics, preventing one playbook's processing
  from corrupting what another playbook (or logging/metrics) sees.
- **Input validation** — each playbook validates its own required inputs
  are present and nominal before producing a hypothesis (§5).
- **Defensive programming** — a playbook never assumes an optional field
  is present; missing optional data degrades the hypothesis's evidence,
  never crashes the playbook.
- **Strategy isolation** — no playbook may access another playbook's
  internal state, configuration, or output. This reinforces §2's
  independence principle as a blast-radius property: a compromised or
  buggy playbook cannot corrupt another's behavior.

---

# 16. Testing

- **Unit tests** — each playbook tested in isolation against fixture
  `ScannerObservation`s, with no dependency on the engine, registry, or
  other playbooks.
- **Determinism tests** — identical `ScannerObservation` input produces
  identical `CandidateTrade` output (or identical no-hypothesis outcome),
  asserted directly — extending `ADR-002` §15's discipline to this stage.
- **Isolation tests** — prove one playbook's failure/exception does not
  affect another playbook's execution or output in the same call.
- **Registry tests** — prove a playbook can be added, removed, or
  disabled without modifying the registry's own code or any other
  playbook — a direct test of §7 and §17's extensibility claim.
- **Interface compatibility tests** — every registered playbook satisfies
  the common interface (§5) — a contract-level test, not just behavioral.
- **Regression tests** — a playbook version bump must not silently change
  another playbook's behavior, and must document any intended change in
  its own output for fixed input.
- **Failure isolation tests** — simulate a playbook throwing and assert
  the engine still returns valid `CandidateTrade` objects from every
  other playbook, with the failure logged per §12.
- **Duplicate Strategy ID detection** — registering two playbooks under
  the same Strategy ID is detected at registry initialization, per §7's
  Duplicate Strategy ID Handling subsection.
- **Registry initialization failure** — a duplicate Strategy ID causes
  registry startup to fail fast; the registry must not proceed in a
  partially-loaded state and neither conflicting playbook is loaded.
- **Deterministic duplicate handling** — the same conflicting playbook
  set, registered in any order, produces the same fails-to-initialize
  outcome — proves registration order never determines a "winner."
- **Structured error logging verification** — the logged error for a
  duplicate Strategy ID contains both conflicting Strategy IDs, their
  names, and their versions, per §7.
- **Reasoning-metadata boundary test** — confirms that reasoning metadata
  (§3, §6) contains descriptive evidence only: it is not interpreted as a
  numeric confidence score, and it cannot influence ordering or ranking
  of `CandidateTrade`s anywhere within the Strategy Engine. This is the
  test-level enforcement of the boundary flagged in this ADR's
  architectural review — reasoning metadata must never become an
  implicit scoring mechanism smuggled in under a different name.

---

# 17. Extensibility

A new playbook is a new module implementing §5's interface plus a
registry entry (§7) — zero lines changed in the Strategy Engine's own
code or any existing playbook. Existing playbooks remain untouched
because they share no code path with a new addition beyond the common
interface contract. Future playbooks integrate **only** through the
registry. This is the same property the reference material's
`orchestrator.py` discovery pattern gestures at (cited as an idea only,
per `ADR-001`), made a first-class, tested architectural guarantee here
rather than an implementation convenience.

---

# 18. Architectural Invariants

Must never be violated:

- Scanner never creates hypotheses (`ADR-002`).
- **The Strategy Engine never scores, ranks, approves, rejects, sizes, or
  executes** (§3).
- **The Strategy Engine never resolves conflicts between
  `CandidateTrade`s** — exclusively Scoring Engine's job (§9, ADR-004).
- **The Strategy Engine never computes new market facts the Scanner
  didn't provide** — a gap to raise against `ADR-002`, never routed
  around (§11).
- `CandidateTrade`, once produced, is immutable — later stages attach
  data alongside it, never rewrite it (§6).
- Scoring Engine never generates hypotheses (reserved for ADR-004 to
  restate and own).
- Risk Engine never changes strategy logic (reserved for ADR-005).
- Compliance Engine never modifies `CandidateTrade` (reserved for
  ADR-006).
- Execution Validator never invents trades (reserved for ADR-007).
- MT5 Bridge never makes decisions (reserved for ADR-008).

The invariants attributed to ADR-004 through ADR-008 are forward
declarations for consistency; they will be restated and formally owned
when those ADRs are drafted.

---

# 19. Acceptance Criteria

ADR-003 is acceptable only if it guarantees:

- ✓ Strategies are fully independent (§2, §15).
- ✓ Strategies are deterministic (§2, §16).
- ✓ Strategies are stateless (§2).
- ✓ Strategies are replaceable (§2, §7).
- ✓ A strategy can be added without modifying others (§7, §17, §16).
- ✓ A strategy can be removed without affecting others (§7, §17).
- ✓ No execution logic exists (§3, §18).
- ✓ No scoring logic exists (§3, §9, §18).
- ✓ No compliance logic exists (§3, §18).
- ✓ No MT5 logic exists (§3, §18).
- ✓ No position management exists (§3, §18).
- ✓ Scanner and Strategy responsibilities never overlap (§11, §18).
- ✓ Strategy and Scoring responsibilities never overlap (§9, §11, §18).
- ✓ Pipeline boundaries are explicit and enforceable (§4, §6's type-level
  guarantee).
- ✓ Strategy ID collisions cannot silently occur — registry
  initialization fails fast and deterministically on any duplicate (§7
  Duplicate Strategy ID Handling, §16).
- ✓ Reasoning metadata cannot become an implicit scoring mechanism — it
  is descriptive only, never numeric, never influences ordering or
  ranking (§3, §6, §16).

---

# 20. Reference material — ideas only, not authority

Studied for ideas only, per `ADR-001`; neither is authoritative:

- `titan_protocol/strategies/base.py` — the `StrategyContext`/`StrategySignal`
  shape (facts handed to a strategy, a signal handed back) is a useful
  idea for §5/§6's boundary; not an authoritative type.
- `titan_protocol/strategies/orchestrator.py` — the discovery-and-registration
  pattern (`discover_strategy_classes()`) is a useful idea for §7; its
  specific canonical-ordering mechanism is not binding.
- `titan_protocol/strategies/engine.py` — its `resolve()` consolidation/
  conflict-dampening logic is explicitly **not** carried forward into this
  stage (§9); it is relocated to Scoring Engine (ADR-004) as a deliberate
  architectural correction, not an oversight.
- `titan_protocol/strategies/{orb_strategy,liquidity_reversal,session_breakout,
  support_resistance,momentum_continuation}.py` — studied only for the
  general shape of "what a playbook looks at"; no thresholds, scoring
  weights, or logic are authoritative or referenced for the placeholders
  in §8.
- `phantom_institutional.py` — its playbook-equivalent logic is embedded
  directly inside its scoring routes with no plugin boundary at all;
  studied primarily as a **negative** example — the absence of a
  playbook/engine separation there is exactly what this ADR's plugin
  architecture (§5, §7) is designed to avoid.

---

Per `ADR-001` and `CLAUDE.md` §1.10, **no implementation begins until this
ADR's Status changes from Proposed to Accepted.**
