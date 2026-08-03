# Phantom EA — Engineering Charter

## Mission

Build and maintain an institutional-grade MT5 trading system designed for
prop firms. Primary objectives: reliability, capital preservation,
deterministic behavior, maintainability. Profit comes from disciplined
execution, not feature count.

## Priority order

When guidance conflicts, higher wins:

1. **Phantom Protocol rules** (§1)
2. **Phantom safety architecture** (§2)
3. **Phantom coding & scoring standards** (§3)
4. **Minimal Change Engineer philosophy** (§6)
5. **General engineering behavior** (§7)
6. Claude's own defaults

**Architecture authority:** `docs/adr/ADR-001-single-authority-architecture.md`
(Accepted) and its per-stage successors (ADR-002 onward) are the single
source of truth for Phantom's target pipeline and supersede §2's original
component order wherever the two conflict. See §2.

---

## 1. Phantom Protocol rules

1. Never sacrifice stability for new features.
2. Never remove existing functionality unless explicitly instructed.
3. Prefer replacing weak logic over adding duplicate logic.
4. Before adding anything, check for duplicate indicators, duplicate
   scoring, and duplicate filters.
5. Keep the architecture modular and loosely coupled.
6. Preserve backward compatibility unless the user explicitly approves
   breaking it.
7. Every change must compile cleanly and include validation.
8. Every change must explain why it improves the system.
9. If uncertain about execution logic, ask before changing it — don't
   guess (see §7).
10. Never modify production code until the relevant architecture has been
    reviewed — concretely, no implementation begins on a pipeline stage
    until that stage has its own **Accepted** ADR under `docs/adr/` (see
    §2). A Proposed or superseded ADR does not authorize implementation.

## 2. Phantom safety architecture

**Current architecture (authoritative — `docs/adr/ADR-001-single-authority-architecture.md`, Accepted 2026-07-04):**

There is exactly one authoritative pipeline, designed from first
principles and built one accepted ADR per stage — architecture first,
implementation second, testing third, deployment last:

**Market Data → Scanner → Strategy Engine → Scoring Engine → Risk Engine →
Compliance Engine → Execution Validator → MT5 Bridge → Position Manager →
Analytics**

`phantom/` and `phantom_institutional.py` are **reference-only** — mined
for proven algorithms and safety mechanisms, neither is a running
authority and neither should be extended as if it were. Per-stage ADRs
(ADR-002 Scanner through ADR-010 Analytics, plus ADR-011 Watchdog, ADR-012
Dashboard, ADR-013 Data Pipeline, ADR-014 Multi-Agent Governance) define
each stage's scope before any code for that stage is written.

**Historical — superseded 2026-07-04 by ADR-001, kept for context only, do
not use for current sequencing decisions:** the original component
priority order was Risk Engine → Execution Safety → MT5 Bridge → Watchdog
→ Scanner → Scorer → Analytics → Dashboard. This described a two-authority
state (`phantom/` and `phantom_institutional.py` both live) that ADR-001
explicitly rejected.

**Risk philosophy:**
- Capital preservation overrides profit.
- No duplicate trades. No uncontrolled pyramiding.
- No score inflation. No bypass of guards.
- No execution without validation.

**Scoring rules:**
- No duplicate confirmation. No indicator counted twice. No strategy
  counted twice. Every score component must be independent.

**Strategy philosophy:**
- Strategies may confirm each other; they may never create duplicate
  signals or bypass guards.
- Every playbook, current or future, is a confirmation layer only within
  the Strategy Engine stage — none may decide, size, or execute a trade.
  (Do not hand-list playbook names here — a hand-maintained list is
  exactly the drift risk documented as a defect in the reference material;
  see `.claude/agents/TEAM.md` §8.)

## 3. Phantom coding & scoring standards

- Write readable code. Avoid magic numbers. Document public methods. Keep
  functions focused.
- Do not over-engineer. No unnecessary abstraction.
- Review every change like a hedge-fund production system: question every
  assumption, look for race conditions, duplicate logic, memory leaks,
  threading issues, performance bottlenecks. Never assume correctness.

## 4. Required workflow — before, during, and after every change

**Before:**
1. Read the affected files and their dependencies.
2. Check the affected architecture against §2's current pipeline (ADR-001
   and its per-stage successors) — not the historical order.
3. If the change touches a pipeline stage, confirm that stage's ADR is
   **Accepted**, not merely Proposed, before implementing (§1.10).
4. Identify duplicate logic and potential regressions.
5. Explain the proposed solution before touching code.

**During:**
6. Implement the smallest change that solves the problem (§6).

**After:**
7. Validate — compile success, startup success, regression tests, scoring
   distribution, strategy consistency, API endpoints, MT5 compatibility,
   watchdog compatibility, as applicable to what changed.
8. Produce a change report: **Summary, Files changed, Why, Risks,
   Validation, Remaining issues, Recommendations.**

## 5. Engineering Council

Ten specialist agents are installed in `.claude/agents/` with a full
governance charter (roster, responsibilities, RACI matrix, review
pipeline, standing improvement backlog) in `.claude/agents/TEAM.md`. Consult
that file for which agent owns which component and when each is mandatory
before a merge. This section is a pointer, not a duplicate — do not restate
its contents here.

## 6. Minimal Change Engineer philosophy

The default implementation mode for every change, regardless of who
proposed it:

- Make the smallest correct change that solves the stated problem.
- Tolerate three similar lines before extracting a fourth into an
  abstraction.
- Skip defensive code for scenarios that cannot occur.
- Keep bug fixes and refactors in separate changes — never bundle a
  drive-by refactor into a fix.
- If a proposal can't be implemented as a minimal diff, split the rest
  into an explicitly-scoped follow-up rather than expanding scope inline.

## 7. General engineering behavior

Applies wherever §1–6 don't already cover the situation; does not restate
anything above.

- **Never guess.** Verify assumptions against the actual repository —
  read the code, don't infer it. If uncertain after investigating, then
  ask (per §1.9), rather than inventing an answer.
- **Always consider edge cases** before calling a change complete.
- **Never leave partial implementations** — a change either fully solves
  what it set out to solve, or it isn't done.
- **Keep commits focused** — one logical change per commit.
- **Leave the codebase cleaner than you found it**, within the bounds of
  §6 — this means not leaving a mess from your own change, not license to
  refactor unrelated code.
- **Optimize for long-term maintainability** as a tiebreaker between
  equally-minimal options, never as a reason to expand scope.

No web-development or frontend-specific assumptions apply — this is a
Python trading engine with no browser surface.
