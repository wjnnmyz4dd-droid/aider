# ADR-001 — Single Authority Architecture

Status: **Accepted** (resolved 2026-07-04 — see Resolution)

Owner: Software Architect

Date: 2026-07-04

---

# Problem

Titan Protocol currently contains two independent decision authorities.

Examples:

- titan_protocol/

- phantom_institutional.py

Both contain scoring, compliance, and execution-related logic.

If both systems are connected to MT5 simultaneously they can disagree on:

- Trade approval

- Risk sizing

- Compliance

- Kill Switch

- Session rules

- Exposure

- News filtering

A prop firm system must never allow conflicting authorities.

---

# Decision

There will only be ONE authoritative pipeline.

**Neither `titan_protocol/` nor `phantom_institutional.py` becomes that pipeline.**
Both are retired to reference material — mined for proven ideas,
algorithms, and safety mechanisms, but neither is the permanent authority.
The new architecture is designed from first principles, via ADRs, before
any implementation.

Everything else becomes a supporting service.

Decision Flow (superseded 2026-07-04 — see Resolution for the current
pipeline)

Market Data

↓

Scanner

↓

Scorer

↓

Compliance

↓

Risk

↓

Execution Validator

↓

Execution

↓

MT5

Every module must feed this pipeline.

No module may bypass it.

---

# Single Sources of Truth

Pipeline order (see Resolution): Market Data → Scanner → Strategy Engine →
Scoring Engine → Risk Engine → Compliance Engine → Execution Validator →
MT5 Bridge → Position Manager → Analytics.

## Scanner

Responsible for:

- Signal generation

- Market structure

- Session detection

## Strategy Engine

Responsible for:

- Evaluating confirmation-layer playbooks (ORB, Liquidity Reversal,
  Session Breakout, S/R Bounce, Momentum Continuation, and any future
  playbook)

- Consolidating multiple strategy signals into one non-inflating
  confirmation input — never a raw sum, never a duplicate signal

- Strategies confirm; they never decide, size, or execute

## Scoring Engine

Responsible for:

- Composite confidence score

- Decision classification (APPROVE / WATCHLIST / BLOCK or equivalent)

- Owns no compliance, risk, or execution logic — those are downstream

## Risk Engine

Responsible for:

- Lot sizing

- Stop Loss / Take Profit

- Portfolio limits

- Per-trade risk tiering from rolling performance and drawdown — may only
  reduce risk, never increase it

## Compliance Engine

Responsible for:

- News

- Prop-firm rules

- Daily/total loss limits and kill-switch

- Max positions / exposure

- Final, non-bypassable authority — a Compliance failure blocks
  regardless of what upstream stages produced

## Execution Validator

Responsible for final approval.

Nothing reaches the MT5 Bridge without this approval. Confirms upstream
stages agree (Scoring Engine decision + Risk Engine sizing + Compliance
Engine pass) before authorizing a single order — the only place idempotency
and duplicate-trade prevention are enforced.

## MT5 Bridge

Responsible for:

- The sole channel to MetaTrader — no other module talks to MT5 directly

- Translating an authorized decision into a broker order and reporting
  fills/rejections back upstream

## Position Manager

Responsible for:

- Tracking open positions, partial closes, trailing/breakeven logic post-entry

- The only module allowed to modify a position after entry

## Analytics

Responsible for:

- Per-strategy and portfolio performance reporting from real closed trades
  only

- Read-only — never feeds back into a trading decision except through an
  explicit, auditable Risk Engine input

---

# Forbidden

No duplicate:

- scoring

- compliance

- risk

- execution

- killswitch

No second authority may exist.

---

# Migration Plan

Superseded 2026-07-04 — see Resolution. Original phases assumed one of the
two existing codebases would become primary; that assumption was rejected.
Replacement sequence, per the Resolution's "architecture first,
implementation second, testing third, deployment last":

Phase 1 — Architecture

One ADR per pipeline stage (Scanner, Strategy Engine, Scoring Engine, Risk
Engine, Compliance Engine, Execution Validator, MT5 Bridge, Position
Manager, Analytics), each naming what's mined from `titan_protocol/` /
`phantom_institutional.py` as reference vs. built new, before any code.

Phase 2 — Implementation

Build each stage per its accepted ADR, smallest-diff discipline
(`.claude/agents/TEAM.md` §6/§7), one stage at a time in pipeline order.

Phase 3 — Testing

Regression + validation per stage, plus full-pipeline integration tests
once all stages exist.

Phase 4 — Deployment

Only after Phase 3 passes in full. `titan_protocol/` and `phantom_institutional.py`
are archived (never deleted, per the existing Archive Policy in `AUDIT.md`)
once the new pipeline supersedes them functionally.

---

# Success Criteria

Exactly one authority exists for:

✓ Trade Approval

✓ Risk

✓ Compliance

✓ Execution

✓ Kill Switch

✓ Portfolio Exposure

✓ News

And additionally, matching the resolved pipeline:

✓ Signal generation / Scanning

✓ Strategy confirmation

✓ Scoring

✓ MT5 communication

✓ Post-entry position management

✓ Performance analytics

No stage's responsibility appears in more than one module. `titan_protocol/` and
`phantom_institutional.py` are reference-only inputs to this design, not
running authorities, once the new pipeline exists.

---

# Future ADRs

Revised 2026-07-04 to match the resolved pipeline, one ADR per stage plus
the cross-cutting concerns the original list identified:

ADR-002 Scanner

ADR-003 Strategy Engine

ADR-004 Scoring Engine

ADR-005 Risk Engine

ADR-006 Compliance Engine

ADR-007 Execution Validator

ADR-008 MT5 Bridge

ADR-009 Position Manager

ADR-010 Analytics

ADR-011 Watchdog (cross-cutting — monitors all stages above)

ADR-012 Dashboard

ADR-013 Data Pipeline (Market Data ingestion, feeds Scanner)

ADR-014 Multi-Agent Governance (Engineering Council process itself)

ADR-015 External Data Sources & API Governance (added 2026-07-04 — not
part of the original per-stage list above; covers every external
service/API/vendor used anywhere in Titan Protocol, including ones with no
pipeline stage of their own, e.g. source control, AI development tooling,
and the VIBE research lab's isolation boundary)

ADR-016 AI News Intelligence Layer (added 2026-07-04 — not part of the
original per-stage list; an advisory-only system running beside the
pipeline, not inside it, with zero authority over any trade)

ADR-017 Portfolio Manager (recommended by
`ARCHITECTURE-GAP-AUDIT-2026-07-04.md`, not yet drafted — cross-symbol
exposure/correlation/risk-budgeting, distinct from Position Manager
(ADR-009)'s single-position lifecycle scope)

ADR-018 Replay & Certification Engine (recommended by
`ARCHITECTURE-GAP-AUDIT-2026-07-04.md`, not yet drafted — cross-cutting
historical replay/certification tooling)

ADR-019 Self-Evolving Market Structure Research Agent (added 2026-07-04
— a research-lab-only hypothesis generator with zero live pipeline
access, governed by the same AI Research Governance boundary as ADR-015
§7 and ADR-016)

---

# Resolution (2026-07-04)

Both open questions below were put to the project owner directly. Answers:

1. **Primary implementation: neither.** `titan_protocol/` and
   `phantom_institutional.py` are both retired to reference-only status —
   mined for proven algorithms and safety mechanisms, but neither becomes
   the permanent authority. The system is designed from first principles
   via a sequence of ADRs (see revised Future ADRs list) before any
   implementation begins. This is a stronger resolution than either option
   originally offered in Open Question 1, and supersedes that recommendation.
2. **Forward test status: concluded.** The `RELEASE.md` freeze on
   `phantom_institutional.py` (frozen at `156f18c`) no longer applies —
   there is no live system currently depending on that file's stability,
   which is what unblocks retiring it to reference-only rather than having
   to keep it running in parallel.

Order of work going forward, per explicit instruction: **architecture
first, implementation second, testing third, deployment last.** No code
will be written until each pipeline stage has its own accepted ADR.

Historical record of the pre-resolution review follows, preserved for
traceability rather than deleted.

---

## Architect's Review (pre-resolution — superseded by Resolution above)

The problem statement and the "no second authority" principle are sound
and match the Conflicting Responsibilities finding already on record
(`.claude/agents/TEAM.md` §8). Three things below must be resolved before
this ADR can move from **Proposed** to **Accepted** — approving it as
written would leave the single most important decision unmade.

## Open Question 1 — Phase 3 has no answer

"Select primary implementation" is the actual decision this ADR exists to
make, and it's currently a placeholder. Evidence from the standing
architecture review:

- **`phantom_institutional.py`** is the system actually wired to MT5 today.
  Per `AUDIT.md`: it exposes ~100 HTTP routes the EA posts to directly
  (`/heartbeat`, `/score`, `/bars_push`, `/feedback`, `/account/snapshot`),
  gates every score request through `phantom_command_center.py`'s
  `/can-trade` (fail-closed), and is the subject of `RELEASE.md`'s
  `v1.0-forward-test` freeze — i.e. it is the live authority right now, not
  a candidate.
- **`titan_protocol/`** is the newer, modular, fully-tested package (13/13
  `validate.py`, stdlib-only) — but its own README states "It never places
  orders. Execution, if any, lives outside this package." It has no MT5
  bridge, no watchdog, no command-center integration, and no execution
  path at all today.

Neither codebase is a drop-in "primary implementation" as-is: one has
execution wiring but is the less cleanly architected of the two; the other
has the cleaner architecture but no execution wiring. Recommend Phase 3
conclude explicitly: **`titan_protocol/`'s pipeline shape becomes the target
architecture, with `phantom_institutional.py`'s proven MT5/command-center
integration and compliance logic ported into it** — rather than the
reverse — but this determines which system holds execution authority and
should not be decided unilaterally. **Needs your confirmation.**

## Open Question 2 — freeze-policy conflict

`RELEASE.md` freezes `phantom_institutional.py` at commit `156f18c` under
an explicit policy: *"No new features. Only confirmed runtime bug fixes"*
for a 2–4 week forward test. The most recent commit touching that file
(`f5b0c7a`) was expressly justified as "permitted by the RELEASE.md freeze
policy" for exactly this reason. Phase 3/4 of this migration (selecting
and then removing a duplicate authority) is unambiguously **not** a
runtime bug fix — running it now would violate the freeze on a system
that may currently be mid-forward-test. **Is the forward test still
active, or has it concluded?** Phase 3/4 should not start until you
confirm it's over.

## Open Question 3 — "Execution" and "MT5 Bridge" don't exist in either codebase

Confirmed by filesystem search earlier this session: there is no
`Execution`, `Execution Validator`, or `MT5 Bridge` source file in this
repository. `titan_protocol/trade_router.py` is advisory position **sizing**
only — it never places an order. The actual order-placement logic, if any,
lives client-side in the MT5 EA (`DarkPhantomProtocol_v2.mq5`), which also
isn't in this repository. Phase 1's inventory should record this
explicitly so "select primary implementation" isn't assumed to include
code that doesn't exist yet — building a real Execution Validator/MT5
Bridge is new work, not a migration of existing duplicate logic, and per
§2 of the Charter (Architecture Priorities) and Core Rule 10, that's
exactly the kind of execution-logic change that needs explicit sign-off
before implementation, not just before this ADR.

*(At the time this review was written, the ADR was held at Proposed
pending answers to Open Questions 1–2, since proceeding without them would
have meant deciding execution authority unilaterally — forbidden by Core
Rule 10 and the Council's Execution-row RACI gate. Both questions have
since been answered; see Resolution above. Open Question 3 remains
relevant as a scoping note for ADR-007/ADR-008 and is not superseded.)*
