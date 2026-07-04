# ADR-004 — Scoring Engine

Status: Proposed

Owner: Software Architect (per the reference material's precedent —
`.claude/agents/TEAM.md`'s "Scorer" row is Software-Architect-accountable
— and because scoring is a cross-cutting evaluation concern rather than a
playbook-orchestration one)

Reviewed by: Multi-Agent Systems Architect (consumes `CandidateTrade`
directly from the Strategy Engine and must respect its boundary, per
`TEAM.md` §4's two-tier architecture rule)

Date: 2026-07-04

Depends on: `ADR-001-single-authority-architecture.md` (Accepted),
`ADR-002-scanner.md` (Accepted), `ADR-003-strategy-engine.md` (Accepted)

---

# Pipeline position

Market Data → Scanner → Strategy Engine → **Scoring Engine** → Risk
Engine → Compliance Engine → Execution Validator → MT5 Bridge → Position
Manager → Analytics

This ADR defines only the Scoring Engine stage. It consumes the Strategy
Engine's output (`ADR-003`) and produces input for the Risk Engine
(ADR-005). It does not define either neighbor.

---

# 1. Mission

**The Scoring Engine answers exactly one question: "How strong is each
`CandidateTrade`?"**

It must never answer:

- Should we execute?
- How much should we risk?
- Is the trade compliant?
- Should the order be sent?
- How should the position be managed?

Every one of those belongs to a later stage (Execution Validator, Risk
Engine, Compliance Engine, Execution Validator again, and Position
Manager, respectively). The Scoring Engine is an **independent
evaluator**, not a filter and not a decision-maker. Every `CandidateTrade`
that reaches it receives a `ScoreResult`; none are silently dropped (§7).
A score is advisory strength/confidence information for downstream stages
to weigh alongside their own concerns — it is not itself an approval, and
a low score is not a rejection.

---

# 2. Core Principles

The Scoring Engine, and every scoring rule within it, must be:

- **Deterministic** — the same `CandidateTrade` input always produces the
  same `ScoreResult` output.
- **Stateless** — no state carried between calls.
- **Pure** — output is solely a function of the declared inputs
  (`CandidateTrade` plus configuration, §11), nothing else.
- **Explainable** — a score without a reconstructable rationale is not
  auditable and is not acceptable (§5, §12). This principle is specific to
  scoring and has no direct equivalent at the Scanner or Strategy Engine
  stages, which report facts and hypotheses rather than a synthesized
  number.
- **Testable** — every scoring rule, and the engine itself, is testable
  in complete isolation using fixture `CandidateTrade`s.
- **Replaceable** — any scoring rule can be swapped or removed without
  touching any other rule or the engine's own code.
- **Independent** — evaluating one `CandidateTrade` never depends on the
  presence, content, or score of another (§7).

Explicitly forbidden:

- **No randomness.**
- **No adaptive behavior.**
- **No online learning.**
- **No self-modifying weights** — consistent with the standing
  prohibition on automatic parameter optimization
  (`docs/adr/ADR-015-external-data-sources-api-governance.md` §7,
  `.claude/agents/TEAM.md` §6). A weight changes only through a
  human-reviewed version bump (§11), never at runtime.
- **No hidden state.**

---

# 3. Responsibilities

**The Scoring Engine SHALL:**

- Consume `CandidateTrade` objects.
- Evaluate every candidate independently — scoring one must never depend
  on another candidate's presence, content, or score in the same batch
  (§7).
- Apply deterministic scoring rules.
- Produce `ScoreResult` objects.
- Record detailed scoring evidence.
- Preserve complete traceability, extending the `trace_id` chain
  established at the Scanner stage (`ADR-002` §11) through the Strategy
  Engine (`ADR-003` §12) into scoring.

**The Scoring Engine SHALL NEVER:**

| Forbidden action | Owned instead by |
|---|---|
| Execute trades | MT5 Bridge (ADR-008) |
| Reject trades | Compliance Engine (ADR-006) / Execution Validator (ADR-007) |
| Allocate risk | Risk Engine (ADR-005) |
| Calculate lot size | Risk Engine (ADR-005) |
| Perform compliance | Compliance Engine (ADR-006) |
| Talk to MT5 | MT5 Bridge (ADR-008) |
| Manage positions | Position Manager (ADR-009) |
| Modify Scanner observations | Nobody — immutable everywhere downstream of Scanner (`ADR-002` §2, §7) |
| Modify `CandidateTrade` objects | Nobody — immutable everywhere downstream of Strategy Engine (`ADR-003` §6) |

A "reject" is deliberately absent from the Scoring Engine's vocabulary —
see §7's "must never discard candidates."

---

# 4. Pipeline Contract

## Strategy Engine → Scoring Engine

- **Required inputs:** zero or more `CandidateTrade` objects per call
  (mirrors `ADR-003` §4's own statement of its output guarantee).
- **Guaranteed outputs (trusted from Strategy Engine):** every
  `CandidateTrade` is well-formed per `ADR-003` §6 — immutable,
  structurally incapable of a forbidden field. The Scoring Engine trusts
  this the same way the Strategy Engine trusted `ADR-002`'s Scanner
  guarantee, while still defensively validating it (§12).
- **Failure behavior:** if a `CandidateTrade` violates the trusted
  contract (should not happen if `ADR-003` is honored, but must be
  handled defensively), the Scoring Engine fails closed for **that
  candidate only** — a deterministic failure record (§8), never a crash
  of the whole batch, never a silent drop.
- **Schema versioning:** `CandidateTrade` carries `schema_version`
  (`ADR-003` §6). The Scoring Engine declares which version(s) it is
  compatible with; an incompatible `schema_version` produces a fail-closed
  failure record for that candidate, never best-effort parsing — the same
  rule `ADR-003` §4 established for `ScannerObservation` compatibility.
- **Backward compatibility:** a new `CandidateTrade` field must be
  additive — safe to ignore by scoring rules unaware of it.
- **Interface ownership:** Multi-Agent Systems Architect (`ADR-003`) and
  this ADR's owner jointly own this boundary, per `TEAM.md` §4.

## Scoring Engine → Risk Engine

- **Required inputs (Risk Engine's perspective):** exactly one
  `ScoreResult` — or one deterministic failure record — per
  `CandidateTrade` received. Never fewer: no candidate is silently
  dropped (§7).
- **Guaranteed outputs:** every `ScoreResult` is well-formed per §6's data
  model, structurally incapable of holding a risk/compliance/execution/
  MT5/position-management field.
- **Failure behavior:** a scoring-rule failure for one candidate produces
  a deterministic failure record for that candidate (§8); it never blocks
  scoring of other candidates, and the failure record itself is still
  forwarded — preserving "never discard" even for candidates that
  couldn't be fully scored.
- **Schema versioning:** `ScoreResult` carries its own `schema_version`,
  independent of `CandidateTrade`'s, so Risk Engine can evolve
  independently of the Scoring Engine.
- **Backward compatibility:** same additive-field discipline.
- **Interface ownership:** this ADR's owner is accountable for keeping
  the contract stable until ADR-005 is drafted and assigns its own owner
  for the Risk Engine side.

---

# 5. Scoring Model

Architecture only — no formulas, no weights, no implementation.

- **Rule-based scoring** — the engine applies a set of independent, named
  scoring rules to each `CandidateTrade`. Each rule is itself deterministic
  and stateless, inheriting §2's principles at the rule level, not only
  the engine level.
- **Weighted factors** — a rule may carry a weight, sourced from
  configuration (§11), never hardcoded. The specific weights and
  thresholds are implementation detail, explicitly out of this ADR's
  scope.
- **Evidence collection** — each rule that fires records what evidence
  triggered it, referencing back to the `CandidateTrade`'s own supporting
  observations and evidence (`ADR-003` §6) — extending the traceable
  chain from Scanner fact → Strategy Engine hypothesis → scoring-rule
  contribution.
- **Score explanation** — for any `ScoreResult`, it must be possible to
  state which rules fired, with what evidence, without re-running
  anything — extending `ADR-002`/`ADR-003`'s "answer purely from logs"
  observability requirement to scoring.
- **Confidence rationale** — distinct from the raw score: a rationale for
  *why* the score reflects genuine confidence (e.g. multiple independent
  rules agree, none conflict), not merely a running sum. The specific
  aggregation method remains implementation scope.
- **Traceability** — every score decomposes into its contributing rule
  evaluations; nothing in the final number is unexplained.
- **Versioning** — the rule set itself is versioned (rule versions, weight
  versions, §11), so a scoring change is an auditable version bump, never
  a silent behavior change — the same discipline `ADR-003` §5 established
  for playbook versioning, applied here to scoring rules.

---

# 6. `ScoreResult`

**May contain:**

- Overall score.
- Factor breakdown.
- Evidence.
- Rule contributions.
- Strategy ID.
- Trace ID.
- Schema version.
- Metadata.

**Must never contain:**

- Lot size, Risk, Compliance, Execution commands, MT5 instructions,
  Position management, Broker actions.

**Type-level guarantee:** `ScoreResult`'s data model must be structurally
incapable of holding any forbidden field — verified by a dedicated test
(§14), mirroring `ADR-002` §8's and `ADR-003` §6's guarantees for their
own output types.

**Immutability:** `ScoreResult`, once produced, is immutable through the
rest of the pipeline — the same discipline `ADR-003` §6 established for
`CandidateTrade`. Later stages (Risk Engine's sizing, Compliance Engine's
verdict) attach their own data alongside it; they never rewrite the score
itself.

---

# 7. Multiple Candidates

The Scoring Engine evaluates every `CandidateTrade` **independently** —
each `CandidateTrade`'s `ScoreResult` is computed purely from that
candidate's own inputs (§2). It **may** rank candidates, compare
candidates, and recommend an ordering — but only as a **post-hoc
operation over already-independently-computed scores** (e.g. sorting by
overall score). Ranking must never feed back into, or change, any
individual `ScoreResult` — this is the reconciliation between "evaluate
independently" and "may rank/compare": independence governs how a score is
*computed*; ranking is a read-only view over scores that already exist.

**The Scoring Engine must never discard candidates.** Every
`CandidateTrade` that enters produces a corresponding `ScoreResult` or a
deterministic failure record (§8) — 1:1 or better; nothing silently
vanishes. Filtering — deciding not to act on a candidate — belongs to
later stages (Risk Engine may decline to size one to anything workable,
Compliance Engine may block one, Execution Validator may not authorize
one). **Which stage, if any, ultimately selects among multiple validly
scored candidates for the same symbol at the same instant is not decided
by this ADR** — that is Risk Engine's, Compliance Engine's, or Execution
Validator's concern, to be resolved when those ADRs are drafted (§16).
The Scoring Engine's own invariant is only that it never filters.

---

# 8. Failure Handling

- One candidate's scoring failure never affects another (a direct
  consequence of §7's independence guarantee, not a separate mechanism).
- One scoring rule's failure never stops the engine, and never stops
  other rules evaluating the **same** candidate: if one rule throws, its
  contribution is recorded as failed, the candidate's other rules still
  run, and the candidate still receives a `ScoreResult` — possibly with a
  degraded evidence set and an explicit rule-failure flag — never a total
  loss of the candidate. This mirrors `ADR-003` §10's playbook failure
  isolation, applied one level deeper (per-rule, within a single
  candidate's evaluation).
- Scoring failures produce **deterministic failure records** — the same
  failing input always produces the same failure record content,
  extending determinism (§9) to the failure path itself, not only the
  happy path.

---

# 9. Determinism

- Same inputs → same outputs.
- Same rule versions → same scores. (A rule-version bump may legitimately
  change a score for identical input — that is an intentional, auditable
  change via §11's versioning, not nondeterminism; the "same" comparison
  holds rule version constant.)
- Same configuration → same ranking.
- No nondeterministic behavior anywhere in the engine or any rule.

---

# 10. Logging

- **Trace IDs** — every `ScoreResult` carries the `trace_id` inherited
  from its `CandidateTrade`, which inherited it from its
  `ScannerObservation` — extending, not reinventing, the chain `ADR-002`
  §11 established.
- **Structured scoring logs** — one record per `ScoreResult`.
- **Rule execution logs** — per-rule fired/abstained/failed, a distinct
  granularity from the per-candidate record.
- **Factor contributions** — each rule's specific contribution to the
  overall score, logged for explainability (§5).
- **Error logging** — rule/candidate failures per §8, with enough detail
  to diagnose without blocking the pipeline.
- **Performance metrics** — export-only, additive, changes nothing — the
  same discipline `ADR-002` §12 / `ADR-003` §12 established.

---

# 11. Configuration

- **Rule versions / weight versions** — configuration-visible, not
  buried in code, mirroring `ADR-003` §13's principle that an active
  playbook version is a configuration fact.
- **Feature flags** — enabling a new/experimental scoring rule narrowly
  before wide enablement, without an engine code change.
- **Safe defaults** — absent explicit configuration, a scoring rule
  defaults to **disabled**, never silently active — the same fail-closed
  default philosophy established throughout `ADR-001`/`ADR-002`/`ADR-003`/
  `ADR-015`.
- **Enable/disable scoring modules** — individual rules toggle without
  engine code changes, mirroring the Strategy Registry's enable/disable
  support (`ADR-003` §7).

---

# 12. Security

- **Immutable inputs** — `CandidateTrade` is never mutated by the Scoring
  Engine or any rule, restating `ADR-003` §6's guarantee from the
  consuming side.
- **Read-only `CandidateTrade`** — the Scoring Engine holds a read-only
  reference, never a mutable copy it could accidentally alter.
- **Input validation** — each scoring rule validates its own required
  `CandidateTrade`/evidence fields are present before evaluating,
  mirroring `ADR-003` §15's playbook-level input validation.
- **Defensive programming** — a rule never assumes optional evidence is
  present; missing optional data degrades that rule's contribution, never
  crashes it.
- **Audit trail** — every `ScoreResult`'s full rule-contribution breakdown
  **is** the audit trail (§5). A score must be reconstructable and
  defensible after the fact — a security/accountability property, not
  merely an explainability nicety, given this system's prop-firm
  compliance context.

---

# 13. Performance

Principles only — no invented latency numbers, per `CLAUDE.md` §7.

- **Linear scalability** — execution cost scales linearly with the number
  of `CandidateTrade`s times the number of scoring rules, not
  combinatorially — a direct consequence of candidate and rule
  independence (§2, §7), not a separate goal to engineer for.
- **Bounded execution** — a time budget set empirically at implementation
  time against real fixture data, not invented here (same discipline as
  `ADR-002` §13 / `ADR-003` §14).
- **No duplicate computation** — if multiple rules need the same derived
  value from a `CandidateTrade` or its referenced `ScannerObservation`, it
  is computed once and shared, extending the `swing_points()` lesson
  (`ADR-002` §13) to the scoring-rule layer.
- **Deterministic ordering** — if the engine ranks or orders candidates
  per §7, that ordering is itself deterministic for identical inputs,
  connecting §9's determinism to the ranking operation specifically.

---

# 14. Testing

- **Unit tests** — each scoring rule tested in isolation against fixture
  `CandidateTrade`s.
- **Regression tests** — a rule or weight version bump must not silently
  change another rule's behavior, and must document any intended change
  in its own output for fixed input.
- **Determinism tests** — identical `CandidateTrade` input produces
  identical `ScoreResult` output, asserted directly.
- **Rule consistency tests** — every registered scoring rule satisfies
  whatever common rule interface implementation defines — mirrors
  `ADR-003`'s interface compatibility tests, one layer down.
- **Version compatibility tests** — incompatible `schema_version` produces
  a fail-closed failure record, per §4.
- **Boundary tests** — a structural/type-level test that `ScoreResult`
  cannot hold a forbidden field (§6), mirroring `ADR-002`/`ADR-003`'s
  type-level guarantee tests.
- **Failure isolation tests** — one rule/candidate failure never affects
  another (§8).
- **Explainability tests** — for any `ScoreResult`, the full
  rule-contribution breakdown reconstructs the overall score — the
  explanation must be consistent with the number, not merely
  present-but-decorative (§5, §12).

---

# 15. Extensibility

Future scoring rules require:

- No architecture changes.
- No pipeline changes.
- No Strategy Engine changes.
- No Risk Engine changes.

A new rule is added the same way a new playbook is added to the Strategy
Engine (`ADR-003` §17): a new rule module plus a registry-style entry —
zero changes elsewhere. This mirrors the Strategy Registry's discovery
pattern (`ADR-003` §7), applied here to scoring rules instead of
playbooks.

---

# 16. Architectural Invariants

The Scoring Engine must never:

- Generate trades — it has no hypothesis-creation capability at all; that
  is exclusively the Strategy Engine's (`ADR-003`).
- Modify `CandidateTrade` (§3, §6).
- Perform compliance (reserved for ADR-006).
- Allocate risk (reserved for ADR-005).
- Execute trades (reserved for ADR-008).
- Manage positions (reserved for ADR-009).
- Communicate with MT5 (reserved for ADR-008).

Restated from earlier ADRs for boundary completeness: Scanner never
creates hypotheses (`ADR-002`); Strategy Engine never scores (`ADR-003`).

**Forward-declared, unresolved by this ADR:** which stage, if any, is
authorized to act on only some of multiple validly scored candidates for
the same symbol/instant (§7) is left to Risk Engine (ADR-005), Compliance
Engine (ADR-006), or Execution Validator (ADR-007) to resolve. This ADR's
only commitment is that the Scoring Engine itself is not that stage.

---

# 17. Acceptance Criteria

ADR-004 is acceptable only if it guarantees:

- ✓ Deterministic scoring (§2, §9, §14).
- ✓ Independent candidate evaluation (§2, §7).
- ✓ Explainable scores (§2, §5, §12, §14).
- ✓ Version-controlled scoring rules (§5, §11).
- ✓ No execution logic (§3, §16).
- ✓ No risk logic (§3, §16).
- ✓ No compliance logic (§3, §16).
- ✓ No MT5 logic (§3, §16).
- ✓ Immutable `CandidateTrade` input (§3, §6, §12).
- ✓ Complete traceability (§3, §5, §10).
- ✓ Pipeline boundaries remain explicit (§4, §6's type-level guarantee,
  §16).

---

# 18. Reference material — ideas only, not authority

Studied for ideas only, per `ADR-001`; neither is authoritative:

- `phantom/scorer.py` — the 18-component weighted-scoring shape, the
  NEUTRAL cap concept, and the "Trade Thesis Summary" (informational,
  never scored) are useful ideas for §5's score-explanation/confidence-
  rationale design. **Explicitly not carried forward:** the reference
  scorer directly embeds blocking-guard logic (News, Spread, Correlation,
  Exposure, RR, Prop Compliance) that forces `BLOCK` regardless of score —
  this mixes scoring with compliance in one component. That mixing is
  rejected here the same way `ADR-003` §9 rejected the reference
  `StrategyEngine.resolve()`'s consolidation logic: compliance/guard logic
  belongs entirely to Compliance Engine (ADR-006), never inside scoring.
- `phantom_institutional.py`'s scoring routes — mix scoring, risk sizing,
  compliance, and ML classification in one function with no stage
  boundary at all. Studied as a **negative** example, the same way
  `ADR-003` §20 treated its playbook-equivalent logic — the absence of
  any scoring/compliance/risk separation there is exactly what this ADR's
  stage boundary (§3, §16) is designed to avoid.

---

Per `ADR-001` and `CLAUDE.md` §1.10, **no implementation begins until this
ADR's Status changes from Proposed to Accepted.**
