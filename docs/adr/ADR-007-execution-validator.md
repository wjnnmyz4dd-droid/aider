# ADR-007 — Execution Validator

Status: Accepted

Acceptance Date: 2026-07-04

Accepted By: Software Architect / Titan Protocol Engineering Council

Owner: Backend Architect (reliability-pattern precedent from `ADR-005`/
`ADR-006`)

Reviewed by: Security Architect (**mandatory, not merely consulted** —
`.claude/agents/TEAM.md`'s RACI already flags Execution as "the highest
blast-radius component in the system" requiring this gate), Software
Architect (cross-module boundary sign-off, per `TEAM.md` §2)

Date: 2026-07-04

Depends on: `ADR-001-single-authority-architecture.md` (Accepted),
`ADR-002-scanner.md` (Accepted, including Amendment 1),
`ADR-003-strategy-engine.md` (Accepted), `ADR-004-scoring-engine.md`
(Accepted), `ADR-005-risk-engine.md` (Accepted),
`ADR-006-compliance-engine.md` (Accepted)

---

# Pipeline position

Market Data → Scanner → Strategy Engine → Scoring Engine → Risk Engine →
Compliance Engine → **Execution Validator** → MT5 Bridge → Position
Manager → Analytics

This ADR defines only the Execution Validator stage. It consumes the
Compliance Engine's output (`ADR-006`) and produces the sole
authorization MT5 Bridge (ADR-008) may act on. It does not define either
neighbor.

---

# 1. Mission

**The Execution Validator answers exactly one question: "Is this trade
still valid at the exact moment it is about to be submitted?"**

It is the final safety gate before MT5 Bridge. It never decides strategy,
never scores, never sizes risk, never performs policy compliance. It only
validates execution readiness — that everything upstream decided is still
true, right now, at submission time.

**The distinction from Compliance Engine (`ADR-006`) is the one that
matters most for this ADR:** Compliance decides *is this permitted under
the rules* — a policy question, evaluated once, that can remain valid for
some interval. The Execution Validator asks *has anything changed since
that decision was made* — a freshness question, evaluated immediately
before submission, every time. It re-verifies, it never re-decides.

---

# Hard Rules

These override any other requirement in this document if they ever
appear to conflict:

- **If any validation cannot be completed → REJECT.** Never guess, never
  continue, never default to APPROVE.
- **Same inputs → same `ExecutionDecision`.** No randomness, no AI, no
  learning.
- **Nothing may bypass this stage.** No hidden execution path. **No
  emergency override.** If a human genuinely needs to act outside this
  gate, that happens entirely outside Titan Protocol (e.g. manually in the MT5
  terminal) — never through a "force approve" mechanism built into this
  stage. This is an absolute architectural invariant, not a configurable
  policy.
- **The Execution Validator never modifies any upstream decision** —
  `ScoreResult`, `RiskDecision`, `ComplianceDecision`, and `CandidateTrade`
  all remain immutable; this stage only reads them and appends its own
  verdict.

---

# 2. Inputs

- **`ComplianceDecision`** (`ADR-006` §4) — must be APPROVE; a BLOCKed
  candidate never reaches this stage in the first place (Compliance's
  BLOCK is terminal per `ADR-006` §1).
- **`RiskDecision`** (`ADR-005` §4), **`ScoreResult`** (`ADR-004` §6), and
  **`CandidateTrade`** (`ADR-003` §6) — all read-only, via the shared
  `trace_id`, for context and for the order parameters (direction, size,
  SL/TP) this stage validates the freshness of but never recalculates.
- **Current market snapshot** — a fresh, at-this-instant read of price,
  spread, and `market_status`, independent of whatever snapshot Scanner,
  Risk Engine, or Compliance Engine observed earlier in the pipeline.
- **Broker state** — connection health, symbol tradability, current
  margin — read fresh, at this instant.
- **Account state** — current equity/margin, read fresh, to catch drift
  since Compliance Engine's evaluation (e.g. concurrent activity that
  changed available margin).
- **Configuration** — maximum order age, drift tolerances for
  price/spread, idempotency window (§7).

---

# 3. Outputs

One `ExecutionDecision` per `ComplianceDecision` received. Never
discarded — the same "never fewer than one output" discipline
established at every prior stage.

---

# 4. `ExecutionDecision` model

**Allowed:**

- Verdict — APPROVE or REJECT.
- Reason codes — which check (§6) failed, or confirmation of which
  checks passed for an APPROVE.
- Validation-stage detail — precisely which named check produced the
  result (required for the logging discipline, §10).
- Trace ID, timestamp, schema version, metadata.

**Forbidden:**

- Any modification to score, risk sizing, compliance verdict, market
  structure, or `CandidateTrade`.
- **New execution instructions.** An APPROVE authorizes MT5 Bridge to
  submit the trade **exactly as already determined** by `RiskDecision`
  (size, SL/TP) and `CandidateTrade` (direction) — it does not itself
  encode a new or re-derived instruction. Encoding execution instructions
  here would blur this stage's read-only validation role into MT5
  Bridge's.
- Anything resembling position management.

**Type-level guarantee:** structurally incapable of holding any forbidden
field, the same guarantee established for every prior stage's output
type, verified by a dedicated test (§12).

**Immutability:** `ExecutionDecision`, once produced, is immutable — MT5
Bridge consumes it, never rewrites it.

---

# 5. Explicitly forbidden

| Forbidden action | Owned instead by |
|---|---|
| Modify scores | Nobody — immutable (`ADR-004` §6) |
| Modify risk | Nobody — immutable (`ADR-005` §4) |
| Modify strategy output | Nobody — immutable (`ADR-003` §6) |
| Modify compliance verdict | Nobody — immutable (`ADR-006` §4) |
| Modify market structure | Nobody — immutable (`ADR-002` §8) |
| Manage positions | Position Manager (ADR-009) |
| **Communicate with MT5 beyond validation** | MT5 Bridge (ADR-008) — see §6's read-only boundary |

---

# 6. Execution checks

All checks are combined by **AND** — the same all-must-pass semantics
`ADR-006` §5 established for compliance, appropriate here since
`ExecutionDecision` is likewise binary, not graded. Grouped by concern:

**Market/price freshness**
- Market still open (`market_status`, read fresh).
- Symbol tradable.
- Price still valid — current price has not drifted beyond a configured
  tolerance from what upstream stages evaluated.
- Spread unchanged — current spread is still within the tolerance
  Compliance Engine's spread check (`ADR-006` §11) validated against;
  **distinct from `ADR-006` §12's historical/expected slippage policy
  check** — this is a live drift check, not a statistical threshold.
- Slippage within limits — the price movement since the upstream
  decision was made is still small enough that submitting now is
  substantially the same trade that was approved, not a different one
  reusing the same `trace_id`.

**Order/account integrity**
- Order still synchronized — the order parameters about to be submitted
  (direction, size, SL/TP) still exactly match `RiskDecision` and
  `CandidateTrade`; no drift between decision-time and submission-time.
- Account synchronized — current account/margin state matches what was
  assumed at decision time; no unexpected concurrent activity has changed
  it.
- Enough margin — a fresh margin check against `RiskDecision`'s sizing,
  since available margin can change between decision and submission.
- Broker connection healthy.
- Trade context unchanged — the umbrella property the checks above are
  specific instances of: nothing material has changed since Compliance
  Engine's decision.

**Staleness and duplication (§7)**
- Trade not stale — time elapsed since Compliance Engine's APPROVE is
  within a configured maximum order age.
- Maximum order age — the specific bound the staleness check enforces;
  exceeding it is a REJECT, never an automatic resubmission (§7).
- No duplicate request — idempotency check (§7).

---

# 7. Idempotency & duplicate-request handling

**This is a deliberate, narrow exception to the statelessness every prior
stage requires** (`ADR-002` §2, `ADR-003` §2, `ADR-004` §2 all forbid
hidden state) — the same class of exception `ADR-002` §2 already carved
out for a session-window clock. The Execution Validator must maintain a
bounded, TTL-pruned record of recently-processed trade requests (keyed by
`trace_id` or an equivalent idempotency key) to detect a duplicate
submission attempt for the same trade. This state must be explicitly
bounded and pruned, mirroring `titan_protocol/orb.py`'s `state_ttl_days` idea —
unbounded growth here would repeat the same class of defect flagged
elsewhere in the reference material.

**This does not violate determinism (§9).** A repeated request is not
"the same inputs" as its first occurrence in the full sense: idempotency
state is itself part of what this stage observes, and it differs between
the first and second attempt. "Same complete inputs (including current
idempotency state) → same decision" holds exactly — a second attempt at
the same trade correctly, deterministically produces REJECT, precisely
because its inputs differ from the first attempt's.

A rejected trade is **not retried automatically** by this stage or any
mechanism inside it. If the underlying opportunity still exists on a
later scan, Scanner produces a fresh `ScannerObservation`, Strategy
Engine a fresh `CandidateTrade` with a fresh `trace_id`, and the full
pipeline runs again through its normal cadence — there is no retry loop,
automatic or otherwise, inside the Execution Validator.

---

# 8. Fail-safe behavior

**If any validation cannot be completed: REJECT.** Restated because it
governs every check in §6 uniformly: an unreachable broker, a failed
margin query, an unreadable market snapshot, or any other check that
cannot be completed all resolve to REJECT — never a default APPROVE,
never a skipped check, never a partial validation treated as sufficient.

---

# 9. Determinism

Same inputs → same `ExecutionDecision`. No randomness, no AI, no
learning. See §7 for why idempotency state does not contradict this.

---

# 10. Logging

Every validation step is logged, not only the final verdict. Every
rejection includes:

- Reason
- Timestamp
- `trace_id` (inherited from `ComplianceDecision`, extending the chain
  from Scanner through every prior stage)
- Validation stage — precisely which named check (§6) produced the
  rejection

This makes every REJECT attributable to a specific check without
re-running anything, the same explainability discipline established at
every prior stage.

---

# 11. Metrics

- Approval rate / reject rate.
- Average validation latency.
- Duplicate-prevention count (§7).
- Margin failures, spread failures, broker failures, synchronization
  failures — each as its own labeled counter, not folded into a single
  generic rejection count.
- Export-only, additive — the same discipline established at every prior
  stage.

---

# 12. Testing

- **Unit tests** — isolated, fixture-based, no dependency on MT5 Bridge
  or any stage downstream.
- **Determinism / replay-determinism tests** — identical inputs (including
  identical idempotency state, §7) produce identical `ExecutionDecision`.
- **Duplicate-prevention test** — a repeated request for the same
  `trace_id` is REJECTed on the second attempt.
- **Stale-trade rejection test** — a request older than the configured
  maximum order age is REJECTed.
- **Broker-disconnect test** — an unreachable broker produces REJECT, not
  a hang or a default APPROVE.
- **Spread-drift and slippage-drift tests** — price/spread movement
  beyond configured tolerance produces REJECT.
- **Margin-failure test** — insufficient current margin produces REJECT
  even when `RiskDecision`'s original sizing was valid at decision time.
- **Synchronization-failure test** — a mismatch between the order about
  to be submitted and `RiskDecision`/`CandidateTrade` produces REJECT.
- **Trace-propagation test** — `trace_id` is present and correct on every
  logged validation step and on the final `ExecutionDecision`.
- **Boundary/type-level test** — `ExecutionDecision` cannot hold a
  modified score/risk/compliance/structure field or a new execution
  instruction (§4).

---

# 13. Security

- **The Execution Validator becomes the final immutable gate. Nothing may
  bypass it. No hidden execution path. No emergency override.** (Hard
  Rules.) This is established here as a forward-declared, binding
  requirement on MT5 Bridge (ADR-008): **MT5 Bridge must require a
  matching `ExecutionDecision` APPROVE before submitting any order** —
  ADR-008 must honor this, not merely reference it.
- **Read-only at the permission level, not merely by convention.** The
  Execution Validator's broker/market connection is scoped, at the
  credential level, to have **no order-placement capability whatsoever**
  — a compromised or buggy Execution Validator cannot place an order even
  if it tried, because its access structurally lacks that capability.
  This is the same least-privilege principle `ADR-015` §9 established for
  credentials generally, applied here as a hard permission boundary
  specifically because this stage sits one step before order placement.
- All upstream inputs (`ComplianceDecision`, `RiskDecision`, `ScoreResult`,
  `CandidateTrade`) are read-only; none are mutated.
- Idempotency state (§7) is protected against tampering — it is a safety
  mechanism, not a log a compromised component could clear to enable a
  duplicate submission.

---

# 14. Acceptance criteria

ADR-007 is acceptable only if it guarantees:

- ✓ Never changes any upstream decision — `ScoreResult`, `RiskDecision`,
  `ComplianceDecision`, `CandidateTrade` all remain immutable (§4, §5).
- ✓ Only validates — never decides strategy, scores, sizes, or performs
  policy compliance (§1, §5).
- ✓ May only approve or reject — binary, never graded (§3, §4).
- ✓ Every rejection is deterministic (§8, §9, §12).
- ✓ Every rejection is logged with reason, timestamp, `trace_id`, and
  validation stage (§10).
- ✓ Every approval is traceable (§10).
- ✓ No hidden execution path, no emergency override — enforced at the
  permission level, not just behaviorally (§13).
- ✓ Idempotency state is bounded, TTL-pruned, and does not contradict
  determinism (§7, §9).

---

# 15. Reference material — ideas only, not authority

- `titan_protocol/orb.py`'s idempotency mechanism (`_confirmed_sessions`,
  `_processed_signal_ids`, TTL-pruned via `state_ttl_days`) — the direct
  idea behind §7's duplicate-request handling. Its specific session-
  confirmation semantics are ORB-strategy-specific (already excluded from
  Scanner per `ADR-002` §6) and are not what's reused here — only the
  general shape of a bounded, pruned idempotency record is.
- `titan_protocol/trade_router.py`'s fail-closed patterns
  (`"compliance-state-error (fail-closed)"`,
  `"account-feed-error (fail-closed)"`) — the direct idea behind this
  ADR's fail-safe philosophy (§8), generalized from account-feed errors
  specifically to every execution check.
- `phantom_institutional.py` — has no distinct execution-validation stage
  at all; order submission logic, wherever it exists, is not separated
  from scoring/risk/compliance concerns. Studied as a negative example,
  the same pattern every prior ADR's reference-material review has
  identified for this file.

---

Per `ADR-001` and `CLAUDE.md` §1.10, **no implementation begins until this
ADR's Status changes from Proposed to Accepted.**
