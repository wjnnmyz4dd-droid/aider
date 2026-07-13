# ADR-006 — Compliance Engine

Status: Accepted

Acceptance Date: 2026-07-04

Accepted By: Software Architect / Titan Protocol Engineering Council

Owner: Security Architect (per `.claude/agents/TEAM.md` RACI, Compliance
row — Accountable; this is the system's final, non-bypassable authority
per `ADR-001`, and design-time trust-boundary ownership belongs here)

Reviewed by: Backend Architect (Risk Engine boundary, `ADR-005`),
Software Architect (cross-module boundary sign-off, per `TEAM.md` §2)

Date: 2026-07-04

Depends on: `ADR-001-single-authority-architecture.md` (Accepted),
`ADR-002-scanner.md` (Accepted, including Amendment 1),
`ADR-003-strategy-engine.md` (Accepted), `ADR-004-scoring-engine.md`
(Accepted), `ADR-005-risk-engine.md` (Accepted),
`docs/adr/ADR-015-external-data-sources-api-governance.md` (Proposed),
`docs/adr/ADR-016-ai-news-intelligence.md` (Accepted)

---

# Pipeline position

Market Data → Scanner → Strategy Engine → Scoring Engine → Risk Engine →
**Compliance Engine** → Execution Validator → MT5 Bridge → Position
Manager → Analytics

This ADR defines only the Compliance Engine stage. It consumes the Risk
Engine's output (`ADR-005`) and produces input for the Execution
Validator (ADR-007). It does not define either neighbor.

---

# 1. Mission

**The Compliance Engine answers exactly one question: "Is this trade
permitted under all system and account rules?"**

It does not answer:

- Is this a good trade?
- How much should we risk?
- Should we manage the position?
- Should we modify market structure?
- Should we score differently?

Every one of those belongs elsewhere (Scoring Engine, Risk Engine,
Position Manager, Scanner, Scoring Engine again). The Compliance Engine
is Titan Protocol's **final, non-bypassable policy authority** per `ADR-001` —
the one stage in the entire pipeline whose job is a binary permit/deny
decision, not a fact, a hypothesis, a score, or a budget. Everything
before it describes and evaluates a trade; this is where the system
decides whether the rules allow it to happen at all.

---

# Hard Rules

These override any other requirement in this document if they ever
appear to conflict:

- **If any required compliance check cannot be evaluated → BLOCK.** Not a
  reduced approval, not a partial pass — an unconditional block. Unlike
  the Risk Engine's graded, minimum-across-constraints budget (`ADR-005`
  §6), Compliance's checks are all-must-pass: any single failing or
  unevaluable check blocks the entire decision.
- **Compliance decisions must be deterministic.** Same inputs, same
  `ComplianceDecision`.
- **Compliance decisions must be fully traceable.**
- **Compliance may never modify risk sizing, strategy output, or
  scores.** `RiskDecision`, `CandidateTrade`, and `ScoreResult` remain
  immutable; Compliance attaches its own verdict alongside them.
- **Compliance owns all trade-blocking authority. Risk Engine owns
  sizing. Execution Validator owns final pre-order verification.** These
  are three different questions, asked in sequence, never merged: Risk
  Engine asks *how much*; Compliance asks *is this permitted at all*;
  Execution Validator (ADR-007, forward reference) asks *is everything
  still valid right now, at the moment of submission* — re-verifying
  freshness and enforcing idempotency/no-duplicate-trades immediately
  before an order reaches MT5, not re-litigating policy Compliance
  already decided.

---

# 2. Inputs

- **`RiskDecision`** objects from the Risk Engine (`ADR-005` §4) — one
  per sized candidate, read-only.
- **The originating `CandidateTrade` and `ScoreResult`**, read-only, via
  the shared `trace_id` — for context only (e.g. direction, Strategy ID);
  never re-scored, never re-sized.
- **Account state** — equity, balance, daily and total drawdown, current
  open positions, current position count (per symbol and account-wide).
- **Broker state** — whether the MT5 terminal/venue is currently
  reachable and ready (`market_status`, the same fact Scanner already
  consumes as a raw input, `ADR-002` §4 — Compliance Engine receives this
  directly from Market Data, not routed through `ScannerObservation`,
  since it is a live trade-permissibility fact, not a market-structure
  fact).
- **Live economic calendar / news state** — from `ADR-015` §6's **live**
  MT5 Calendar entry only. **Never** the research-only alternative news
  provider (`ADR-015` §6, "APIs to Avoid"), and never `ADR-016`'s AI News
  Intelligence Layer, which `ADR-016` §2 already states explicitly is
  never an automated input to this guard.
- **Current spread** — consumed directly, the same way Scanner
  independently receives it as a raw input (`ADR-002` §4). Spread is not
  part of `ScannerObservation`'s data model (`ADR-002` §8 does not list
  it), so Compliance Engine's spread validation (§11) does not depend on
  a field Scanner doesn't define.
- **Versioned configuration** — drawdown limits, session/weekend
  windows, spread/slippage thresholds, maximum-position limits, news
  blackout windows.

---

# 3. Outputs

One `ComplianceDecision` per `RiskDecision` received. The Compliance
Engine never silently drops a candidate — every input produces an
explicit APPROVE or BLOCK, the same "never fewer than one output" pattern
established at every prior stage (`ADR-004` §7, `ADR-005` §3).

---

# 4. `ComplianceDecision` model

**Allowed:**

- Verdict — APPROVE or BLOCK. (The first stage whose output is
  legitimately a decision, not a fact/hypothesis/score/budget — see §1.)
- Reason codes — which check(s) triggered a BLOCK, or confirmation of
  which checks passed for an APPROVE.
- Evaluated-checks list — every check that was run, useful for audit even
  when all pass.
- Rule/policy version.
- Trace ID, schema version, metadata.

**Forbidden:**

- A modified score, a modified `RiskDecision` (lot size, SL/TP), a
  modified `CandidateTrade` (direction), an execution instruction, MT5
  communication, position-management instructions.

**Type-level guarantee:** structurally incapable of holding any forbidden
field, the same guarantee established for every prior stage's output
type, verified by a dedicated test (§18).

**Immutability:** `ComplianceDecision`, once produced, is immutable.
Execution Validator attaches its own verdict alongside it, never rewrites
it — extending the chain `ScannerObservation` → `CandidateTrade` →
`ScoreResult` → `RiskDecision` → `ComplianceDecision`.

**APPROVE is necessary, not sufficient.** An APPROVE means no compliance
rule blocks this trade — it does not guarantee execution. Execution
Validator's own, later check (ADR-007) is still required before anything
reaches MT5.

---

# 5. Hard rule philosophy

Compliance rules are **hard policy**, not tunable risk preferences — the
distinction from Risk Engine's graded budget (`ADR-005` §6) is
architectural, not cosmetic. A hard rule either passes or it doesn't;
there is no "reduce but still proceed" outcome for a compliance check the
way there is for a risk constraint. Every check in §6-§13 is combined by
**AND**: all must pass for APPROVE; any single failure or unevaluable
check is sufficient for BLOCK (Hard Rules). Rules are versioned
configuration (per `ADR-005`'s "no self-adjusting risk without versioned
configuration," applied identically here to compliance) — never adjusted
without a human-reviewed version bump.

---

# 6. Daily drawdown limits

A configured, versioned daily drawdown threshold. Breaching it BLOCKs new
trades for the remainder of the defined period (a daily lockout) —
mirrors the reference material's daily-lockout concept (`titan_protocol/
guards.py`'s `ComplianceEngine`, cited as an idea only). The lockout
resets on a defined boundary (e.g. next trading day), but **the reset
itself is a policy rule, not an assumption** — if the reset condition
cannot be evaluated, the lockout remains in force (Hard Rules).

---

# 7. Total drawdown limits

A configured, versioned total (account-lifetime or evaluation-period)
drawdown threshold. Breaching it triggers the kill switch (§14) — a
**permanent** state, not a daily one, distinct from §6's lockout in
persistence semantics. This directly closes a gap already on record: the
reference material's legacy no-equity fallback path had no kill-switch
persistence at all (flagged in this session's earlier architecture
review). Under this ADR's Hard Rules, that fallback is structurally
impossible — if live equity/account state required to evaluate total
drawdown is unavailable, the check cannot be evaluated, and Compliance
BLOCKs (Hard Rules), rather than silently degrading to a weaker or
absent check.

---

# 8. News restrictions

Blocks trades within a configured blackout window around high-impact
news events for currencies relevant to the candidate's symbol, sourced
exclusively from the live MT5 Calendar (§2). Mirrors `titan_protocol/guards.py`'s
news-blackout concept as an idea. If the live calendar feed is stale or
unavailable, the check cannot be evaluated and Compliance BLOCKs (Hard
Rules) — never defaults to "no news" when the feed is simply absent.

---

# 9. Session restrictions

Blocks (or permits) trades based on configured active-session windows,
consistent with the session-window configuration concept already
established for Scanner (`ADR-002` §4's session time input) and for
Strategy Engine playbook configuration (`ADR-003` §13). Specific hours are
configuration, not architecture.

---

# 10. Weekend restrictions

Blocks trades when `market_status` (§2) indicates the venue is not
currently tradeable (weekend, holiday) — the same fact Scanner already
consumes and fails closed on (`ADR-002` §9). Compliance Engine's own
check is independent of Scanner's — Compliance does not infer market
closure from Scanner's `data_quality_flag`; it evaluates `market_status`
directly, since Scanner's degraded output for a closed market and
Compliance's own weekend-restriction check are different concerns that
happen to share an underlying fact.

---

# 11. Spread validation

Blocks trades where the current spread (§2) exceeds a configured,
symbol-aware threshold — mirrors `titan_protocol/guards.py`'s symbol-aware spread
guard as an idea. **This is a pre-trade policy check** — whether the
spread observed right now is within acceptable bounds to permit trading
at all. It is distinct from any post-fill slippage handling, which would
be a concern for Execution Validator or MT5 Bridge (ADR-007/ADR-008,
forward reference, not resolved here).

---

# 12. Slippage validation

Blocks trades where **expected or historical** slippage for this
symbol/session exceeds a configured threshold — a pre-trade policy check
using historical/typical slippage data, not an actual fill result (which
does not exist yet at this pipeline stage). **Explicitly distinct from
§11**: spread validation checks the current, observable spread; slippage
validation checks a historical/statistical expectation. Post-fill
slippage (did *this* order's actual fill slip too much) is out of scope
for this ADR — forward-referenced to Execution Validator/MT5 Bridge.

---

# 13. Maximum positions

Blocks a new same-direction position when a configured per-symbol or
account-wide position-count limit is already reached — mirrors `titan_protocol/
guards.py`'s exposure/stacking guard as an idea. **Distinct from Risk
Engine's portfolio-heat sizing (`ADR-005` §9)**: Risk Engine *reduces*
budget as heat rises; Compliance Engine *blocks outright* once a hard
count limit is reached. Both may be active simultaneously without
conflict — Risk Engine's sizing narrows the budget on the way in;
Compliance's count limit is a separate, harder backstop.

---

# 14. Kill switch

A **permanent**, latched state triggered by a total-drawdown breach (§7).
Once triggered, it does not clear on its own — mirrors `titan_protocol/
guards.py`'s permanent `_killed` flag as an idea, in contrast to §6's
daily lockout, which resets automatically. **Kill-switch state must
persist across process restarts** — a Compliance Engine that forgets it
was killed after a restart is a severe safety defect, not an
implementation detail. This requires durable storage, per `ADR-015` §6's
Database entry, which already lists Compliance Engine as an approved
consumer for exactly this kind of persistent safety state. Clearing a
latched kill switch is a deliberate, human-reviewed action (through the
Engineering Council process), never automatic.

---

# 15. Fail-safe behavior

**If any required compliance check cannot be evaluated: BLOCK.**
Restated from the Hard Rules because it governs every section above
uniformly: missing account state, an unreachable broker, a stale news
feed, an unevaluable drawdown calculation, or any other required input
being absent all resolve to BLOCK, never to a default APPROVE, never to
skipping the check. Compliance has no concept of "proceed cautiously" —
only APPROVE (all checks passed) or BLOCK (at least one did not, or could
not be evaluated).

---

# 16. Logging

- Every `ComplianceDecision` carries the `trace_id` inherited from its
  `RiskDecision` — extending the chain from Scanner (`ADR-002` §11)
  through Strategy Engine, Scoring Engine, and Risk Engine (`ADR-003`
  §12, `ADR-004` §10, `ADR-005` §16).
- Structured logs record every check evaluated and its individual
  pass/fail/unevaluable result — not just the final verdict — so a BLOCK
  is always attributable to a specific check without re-running anything.
- Kill-switch and daily-lockout state transitions are logged distinctly
  from per-trade decisions, since they are account-level events, not
  per-candidate ones.

---

# 17. Metrics

- Counts of `ComplianceDecision`s by verdict (APPROVE/BLOCK) and, for
  BLOCK, by triggering check.
- Kill-switch and daily-lockout state as a live gauge.
- Export-only, additive — the same discipline established at every prior
  stage (`ADR-002` §12, `ADR-003` §12, `ADR-004` §10, `ADR-005` §17).

---

# 18. Testing

- **Unit tests** — isolated, fixture-based, no dependency on Execution
  Validator or any stage downstream.
- **Determinism tests** — identical inputs produce identical
  `ComplianceDecision`.
- **One test per check (§6-§13)** — proving each check independently
  triggers BLOCK when violated and does not when satisfied.
- **Fail-safe tests** — one per required input category (missing account
  state, unreachable broker, stale news feed, unevaluable drawdown) —
  each must produce BLOCK, never APPROVE, never a skipped check.
- **Kill-switch persistence test** — proving a latched kill switch
  survives a simulated process restart.
- **Kill-switch vs. daily-lockout distinction test** — proving the two
  have different reset semantics (permanent vs. next-period reset).
- **Boundary/type-level test** — `ComplianceDecision` cannot hold a
  modified score, sizing, direction, execution, or position-management
  field (§4).
- **Never-discards test** — every `RiskDecision` produces exactly one
  `ComplianceDecision`.

---

# 19. Security

- No broker credentials beyond what's needed to read broker
  readiness/`market_status` (§2) — no order-placement capability of any
  kind; that remains MT5 Bridge's alone (ADR-008).
- All inputs (`RiskDecision`, `CandidateTrade`, `ScoreResult`, account
  state, broker state, news state, spread) are treated as read-only;
  Compliance Engine mutates none of them.
- Account state, broker state, and news state are treated as untrusted
  and potentially stale — staleness itself is a required-check-cannot-
  be-evaluated condition (§15), not a value to trust by default.
- Kill-switch/lockout state storage (§14) must be protected against
  unauthorized modification — clearing it is a privileged, audited,
  human-reviewed action, never a side effect of any automated process.
- Audit trail — every `ComplianceDecision`'s full evaluated-checks list
  **is** the audit trail, the same framing `ADR-004` §12 and `ADR-005`
  §19 established for their own stages.

---

# 20. Acceptance criteria

ADR-006 is acceptable only if it guarantees:

- ✓ Deterministic compliance decisions (Hard Rules, §18).
- ✓ Never discards a candidate — one `ComplianceDecision` per
  `RiskDecision` (§3, §18).
- ✓ Unconditional BLOCK on any unevaluable required check, with no
  default-APPROVE fallback (Hard Rules, §15, §18).
- ✓ Never modifies risk sizing, strategy output, or scores (§4, §18).
- ✓ Kill-switch state is permanent and persists across restarts,
  distinct from the daily lockout's automatic reset (§14, §18).
- ✓ Immutable `RiskDecision`/`CandidateTrade`/`ScoreResult` inputs (§2,
  §4, §19).
- ✓ Complete traceability — shared `trace_id`, per-check explainability
  (§16).
- ✓ Pipeline boundaries explicit — Compliance owns blocking authority
  only; Risk Engine's sizing and Execution Validator's final pre-order
  verification remain separate, non-overlapping questions (Hard Rules,
  §1).

---

# 21. Reference material — ideas only, not authority

- `titan_protocol/guards.py`'s `ComplianceEngine` — the live-equity peak
  tracking, daily/total drawdown calculation, permanent kill-switch, and
  daily-lockout-with-automatic-reset design are useful ideas, directly
  informing §6/§7/§14. Its legacy no-equity fallback path is explicitly
  **not** carried forward — this ADR's Hard Rules make that fallback
  structurally impossible (§7).
- `titan_protocol/guards.py`'s spread, correlation, and exposure guards — useful
  ideas for §11 and §13; the correlation guard specifically overlaps with
  `ADR-005` §11's sizing-only treatment — this ADR's Maximum Positions
  check (§13) is deliberately narrower (a hard count limit only), leaving
  correlation-based sizing to Risk Engine and correlation-based
  cross-strategy blocking, if ever added, to a future Portfolio Manager
  (ADR-017, forward reference, not resolved here).
- `phantom_institutional.py`'s compliance-adjacent logic embedded in its
  scoring/circuit-breaker routes — studied as a negative example, the
  same pattern `ADR-003` §20, `ADR-004` §18, and `ADR-005` §21 already
  identified for their own reference-material equivalents: no stage
  boundary at all, compliance mixed with scoring and command-center
  availability checks in one function.

---

Per `ADR-001` and `CLAUDE.md` §1.10, **no implementation begins until this
ADR's Status changes from Proposed to Accepted.**
