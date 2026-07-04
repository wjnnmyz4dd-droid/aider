# ADR-005 — Risk Engine

Status: Proposed

Owner: Backend Architect (per `.claude/agents/TEAM.md` RACI, Risk Engine
row — Accountable)

Reviewed by: Security Architect (this stage's boundary against Compliance
Engine's authority is a design-time trust-boundary question, per `TEAM.md`
§4), Software Architect (cross-module boundary sign-off, per `TEAM.md` §2
— any new engine requires this)

Date: 2026-07-04

Depends on: `ADR-001-single-authority-architecture.md` (Accepted),
`ADR-002-scanner.md` (Accepted, including Amendment 1),
`ADR-003-strategy-engine.md` (Accepted), `ADR-004-scoring-engine.md`
(Proposed — status per current repository state)

---

# Pipeline position

Market Data → Scanner → Strategy Engine → Scoring Engine → **Risk
Engine** → Compliance Engine → Execution Validator → MT5 Bridge →
Position Manager → Analytics

This ADR defines only the Risk Engine stage. It consumes the Scoring
Engine's output (`ADR-004`) and produces input for the Compliance Engine
(ADR-006). It does not define either neighbor.

---

# 1. Mission

**The Risk Engine answers exactly one question: "How much capital risk is
allowed for this scored candidate?"**

It does not answer:

- Is this compliant?
- Should this execute?
- Is news safe?
- Is the broker ready?
- How should the position be managed?

Every one of those belongs to a later stage (Compliance Engine, Execution
Validator, Compliance Engine again, Execution Validator again, and
Position Manager, respectively). The Risk Engine is a **capital-budgeting
function**, not a gatekeeper and not a decision-maker about whether to
act — it answers *how much*, never *whether*.

---

# Hard Rules

These override any other requirement in this document if they ever
appear to conflict:

- **Capital preservation overrides opportunity.** Every ambiguity in this
  ADR resolves in favor of less risk, never more.
- **The Risk Engine may reduce or zero risk. It may never increase risk
  above the configured maximum.** Not under any input, not under any
  failure mode, not under any future configuration change that isn't
  itself a deliberate, versioned raise of the ceiling.
- **If required account state is missing → zero risk.**
- **If exposure cannot be calculated → zero risk.**
- **If correlation cannot be evaluated → zero risk.**
- **Risk decisions must be deterministic.** Same inputs always produce
  the same `RiskDecision`.
- **No AI. No learning. No self-adjusting risk without versioned
  configuration.** Any change to risk behavior is a human-reviewed
  configuration or rule version bump (§6), never runtime adaptation.

---

# 2. Inputs

- **`ScoreResult`** objects from the Scoring Engine (`ADR-004` §6) — one
  per scored candidate.
- **The originating `CandidateTrade`** (`ADR-003` §6), read-only,
  referenced via the shared `trace_id` — needed for direction and entry
  concept; never re-scored, never re-generated.
- **The originating `ScannerObservation`'s structural facts** (`ADR-002`
  §5/§8, including Amendment 1's swing hierarchy), read-only, referenced
  via `trace_id` — needed as a structural reference for stop-loss
  placement. **Reused, never recomputed** — an independent swing/
  structure derivation inside the Risk Engine would repeat the
  `swing_points()`-style duplication already rejected at every prior
  stage.
- **Account/risk state** — equity, balance, current drawdown
  (daily/total), rolling trade-outcome history, and currently open
  positions (for portfolio heat, currency exposure, and correlation
  exposure, §9-§11).
- **Versioned configuration** — per-trade ceiling, daily budget, exposure/
  correlation limits, volatility/loss-streak/drawdown scaling rules (§6).

---

# 3. Outputs

One `RiskDecision` per `ScoreResult` received. **The Risk Engine never
discards a candidate** — the same "never fewer than one output per input"
discipline `ADR-004` §7 established for `ScoreResult`. A candidate the
Risk Engine cannot evaluate still receives a `RiskDecision`, with zero
risk and an explicit reason (§15) — never a silent drop.

---

# 4. `RiskDecision` model

**Allowed:**

- Risk budget — expressed as a risk percentage or risk amount.
- Lot size / position size — derived from the risk budget and a
  stop-distance reference (§2's structural input).
- Stop-loss level; take-profit level (if determined here — architecture
  only, no formula).
- Risk tier/mode — a qualitative label describing which regime of
  capital allocation applies (e.g. a defensive/normal/aggressive-style
  classification), not a numeric score.
- Reason codes / evidence — which constraint(s) were binding (§16); this
  directly answers the "why was risk allocated" explainability question
  already named as a gap in `docs/adr/ARCHITECTURE-GAP-AUDIT-2026-07-04.md`
  §2.4.
- Trace ID, schema version, metadata.

**Forbidden:**

- A compliance verdict, an approval/rejection, an execution instruction,
  any MT5 communication, any position-management instruction.
- A rewritten `ScoreResult` or `CandidateTrade` — both remain immutable;
  the Risk Engine attaches its own object alongside them, never rewrites
  either (extending the immutable chain `ScannerObservation` →
  `CandidateTrade` → `ScoreResult` → `RiskDecision`).

**Type-level guarantee:** `RiskDecision`'s data model must be structurally
incapable of holding any forbidden field — the same guarantee established
for every prior stage's output type, verified by a dedicated test (§18).

**Immutability:** `RiskDecision`, once produced, is immutable through the
rest of the pipeline. Compliance Engine and Execution Validator attach
their own verdicts alongside it; neither rewrites it.

---

# 5. Forbidden fields/actions

| Forbidden action | Owned instead by |
|---|---|
| Execute trades | MT5 Bridge (ADR-008) |
| Communicate with MT5 | MT5 Bridge (ADR-008) |
| **Override compliance** | Compliance Engine (ADR-006) — final, non-bypassable authority per `ADR-001`; the Risk Engine's output is always subordinate to it, never a substitute for it |
| Modify `ScoreResult` | Nobody — immutable (`ADR-004` §6) |
| Modify `CandidateTrade` | Nobody — immutable (`ADR-003` §6) |
| Create trades | Strategy Engine (ADR-003) — the Risk Engine never generates a hypothesis |
| Manage positions | Position Manager (ADR-009) |
| Perform compliance, including correlation/exposure **blocking** | Compliance Engine (ADR-006) |

**On correlation/exposure specifically:** the Risk Engine's use of
correlation and currency-exposure data (§10, §11) is **sizing-only** — it
may reduce or zero a risk budget because of elevated correlated exposure.
It is never a blocking or approval decision, and it can never be more
permissive than whatever Compliance Engine's own correlation/exposure
guard (when `ADR-006` is drafted) separately requires. The Risk Engine's
per-candidate view here is also not a substitute for a true cross-
strategy portfolio view — that is `docs/adr/ARCHITECTURE-GAP-AUDIT-2026-07-04.md`'s
recommended ADR-017 (Portfolio Manager), forward-referenced, not resolved,
by this ADR.

---

# 6. Risk budget rules

Architecture only — no formulas, no specific thresholds. The risk budget
awarded to any candidate is the **minimum** across every active
constraint below (§7-§14), never a pick of one constraint over another:
per-trade ceiling, daily budget remaining, portfolio heat, currency
exposure, correlation exposure, volatility adjustment, loss-streak
behavior, and drawdown-aware scaling. This generalizes the reference
material's `risk_pct = min(config_ceiling, engine_output)` pattern
(`phantom/trade_router.py`, cited as an idea only) to multiple
simultaneous constraints, all combined by taking the tightest.

All rule versions and weight/threshold values are configuration, versioned
per the Hard Rules — never hardcoded, never adjusted without a version
bump.

---

# 7. Per-trade risk limits

A configured, versioned ceiling on risk allocated to any single trade
(e.g. a maximum percent of equity). The Risk Engine enforces this as a
hard upper bound — nothing else in §6-§14 may push the awarded risk above
it. Specific numeric values are configuration, not architecture.

---

# 8. Daily risk budget

A configured ceiling on cumulative risk allocated within a defined period
(e.g. a trading day or session). The Risk Engine consumes tracked
cumulative allocated risk for the current period (account/risk state,
§2) and reduces or zeroes new allocations as the budget is consumed.
Resets on a defined boundary. Specific numbers are configuration.

---

# 9. Portfolio heat

Aggregate risk currently "in play" across all open positions. A new
candidate's risk is reduced or zeroed if portfolio heat is already
elevated. This is a per-trade **sizing** consideration, distinct from
(and narrower than) the full cross-strategy aggregate view the gap
audit's recommended Portfolio Manager (ADR-017) would provide — this
ADR's portfolio-heat awareness may be superseded or enriched once that
ADR exists, not contradicted by it.

---

# 10. Currency exposure

Aggregate exposure to a given currency across all open positions. A new
candidate's risk is reduced or zeroed if it would push currency exposure
past a configured limit. Sizing-only, per §5 — the authoritative,
blocking exposure gate remains Compliance Engine's (ADR-006).

---

# 11. Correlation exposure

The same discipline applied to correlation buckets (the reference
material's correlation-bucket concept, `phantom/guards.py`, cited as an
idea only, not authority). Sizing-only, per §5. **If correlation cannot
be evaluated, risk is zero** (Hard Rules) — never assumed safe.

---

# 12. Volatility adjustment

Consumes the originating `ScannerObservation`'s volatility state and
range-structure facts (`ADR-002` §5/§8, reused, never recomputed) to
adjust the risk budget — e.g. reducing risk under extreme or unstable
volatility conditions. Architecture only, no specific formula.

---

# 13. Loss-streak behavior

Consumes rolling trade-outcome history (§2) to detect consecutive losses
and reduce risk accordingly. Mirrors the reference material's
consecutive-loss tracking (`phantom/risk.py`, cited as an idea only) —
architecture only, no specific thresholds.

---

# 14. Drawdown-aware scaling

Consumes current drawdown (daily/total, §2) and applies progressively
tighter risk as drawdown increases, mirroring the reference material's
progressive drawdown-tier concept as an idea, not an authority.
**Important boundary:** the Risk Engine may scale an individual
candidate's risk to zero because of drawdown. **It does not own the
persistent, account-wide kill-switch or trading-halt state** — per
`ADR-001`, that authority belongs to Compliance Engine ("daily/total loss
limits and kill-switch"). A drawdown-zeroed `RiskDecision` here is a
symptom that looks similar to a halt but carries no persistent,
cross-candidate authority; the actual halt, if warranted, is Compliance
Engine's decision to make and enforce, not the Risk Engine's — avoiding
two components independently implementing overlapping kill-switch logic.

---

# 15. Fail-closed behavior

Generalizing the Hard Rules: **any single input the Risk Engine cannot
reliably evaluate resolves that specific constraint to zero risk, and
because the awarded risk is the minimum across all constraints (§6), one
unevaluable constraint drags the entire decision to zero.** Specifically:

- Missing required account state → zero risk.
- Exposure that cannot be calculated → zero risk.
- Correlation that cannot be evaluated → zero risk.

Never guessed, never partially applied, never defaulted to a
non-zero fallback.

---

# 16. Logging and trace_id

- Every `RiskDecision` carries the `trace_id` inherited from its
  `ScoreResult` — extending the chain established at Scanner (`ADR-002`
  §11), through Strategy Engine (`ADR-003` §12) and Scoring Engine
  (`ADR-004` §10).
- Structured logs record **which constraint(s) were binding** — the
  per-trade ceiling, daily budget, portfolio heat, currency exposure,
  correlation, volatility, loss-streak, or drawdown scaling — directly
  answering "why was risk allocated" (or zeroed) without re-running
  anything.
- Failure logging: any fail-closed trigger (§15) is logged with enough
  detail to diagnose without blocking the pipeline.

---

# 17. Metrics

- Counts of `RiskDecision`s by tier/mode.
- Distribution of awarded risk budgets.
- Counts of zero-risk decisions, labeled by reason (missing account
  state / uncalculable exposure / uncalculable correlation / daily budget
  exhausted / drawdown scaling / other).
- Export-only, additive — the same discipline established at every prior
  stage (`ADR-002` §12, `ADR-003` §12, `ADR-004` §10).

---

# 18. Testing

- **Unit tests** — isolated, fixture-based, no dependency on Compliance
  Engine, Execution Validator, or any stage downstream.
- **Determinism tests** — identical inputs produce identical
  `RiskDecision`.
- **Regression tests** — a rule/configuration version bump must not
  silently change behavior for an unrelated configuration; document
  intended changes.
- **Fail-closed tests** — one per Hard Rule: missing account state → zero
  risk; uncalculable exposure → zero risk; uncalculable correlation →
  zero risk.
- **Never-exceeds-maximum test** — a dedicated test proving the awarded
  risk is always less than or equal to the configured ceiling, under
  every tested input including adversarial/malformed account state.
- **Minimum-of-constraints test** — proving the final awarded risk equals
  the minimum across all active constraints (§6), not some other
  combination.
- **Never-discards test** — every `ScoreResult` produces exactly one
  `RiskDecision`.
- **Boundary/type-level test** — `RiskDecision` cannot hold a compliance,
  execution, MT5, or position-management field (§4).

---

# 19. Security

- No broker credentials, no MT5 access — the Risk Engine never talks to
  MT5 (§5).
- `ScoreResult`, `CandidateTrade`, and `ScannerObservation` are read-only,
  immutable inputs — the same discipline established at every prior
  stage.
- Account/risk state is treated as potentially stale or incomplete, not
  automatically trustworthy — connects to `ADR-015` §8's account-feed
  staleness handling; a stale or incomplete feed is exactly the "missing
  required account state" condition that triggers zero risk (§15).
- Defensive programming — missing optional account-state fields degrade
  to zero risk (§15), never crash.
- Audit trail — every `RiskDecision`'s constraint breakdown **is** the
  audit trail, the same framing `ADR-004` §12 established for scoring.

---

# 20. Acceptance criteria

ADR-005 is acceptable only if it guarantees:

- ✓ Deterministic risk decisions (Hard Rules, §18).
- ✓ Never discards a candidate — one `RiskDecision` per `ScoreResult`
  (§3, §18).
- ✓ Never awards risk above the configured maximum, under any input
  (Hard Rules, §7, §18).
- ✓ Capital-preservation-first fail-closed behavior on missing account
  state, uncalculable exposure, and uncalculable correlation (Hard Rules,
  §15).
- ✓ Never overrides Compliance Engine — sizing-only correlation/exposure
  treatment, no blocking authority (§5).
- ✓ Immutable `ScoreResult`/`CandidateTrade`/`ScannerObservation` inputs
  (§2, §4, §19).
- ✓ Complete traceability — shared `trace_id`, constraint-level
  explainability (§16).
- ✓ Pipeline boundaries explicit — no MT5, execution, compliance,
  scoring, or hypothesis-generation logic anywhere in this stage (§5).
- ✓ No AI, no learning, no self-adjusting risk without versioned
  configuration (Hard Rules).

---

# 21. Reference material — ideas only, not authority

- `phantom/risk.py` — the risk-tier concept (defensive/normal/aggressive-
  style modes), the progressive-drawdown-level concept, and the
  fail-safe-to-minimum-on-error philosophy are useful ideas. Explicitly
  not authoritative: its specific numeric bands, thresholds, and tier
  triggers.
- `phantom/trade_router.py` — the `risk_pct = min(config_ceiling,
  engine_output)` pattern is the direct idea behind §6's
  minimum-across-constraints rule; its authority/compliance ordering
  (compliance final, risk-engine-can-only-reduce) is the same ordering
  this ADR establishes between Risk Engine and Compliance Engine.
- `phantom/guards.py` — the correlation-bucket and exposure-cap concepts
  are useful ideas for §10/§11's sizing-only treatment; the guard's own
  blocking behavior is explicitly not carried into this ADR (§5) — that
  belongs to Compliance Engine (ADR-006).
- `phantom_institutional.py`'s risk/sizing routes — mix sizing with
  scoring and compliance in one function with no stage boundary at all,
  the same negative-example pattern `ADR-003` §20 and `ADR-004` §18
  already identified for their own reference-material equivalents.

---

Per `ADR-001` and `CLAUDE.md` §1.10, **no implementation begins until this
ADR's Status changes from Proposed to Accepted.**
