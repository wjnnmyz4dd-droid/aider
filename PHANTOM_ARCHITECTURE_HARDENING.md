# Phantom vNext — Architecture Hardening: Final Specification Revision

Status: **specification revision only.** No production code was
written. No new engine was created. `mt5/PhantomBridgeEA.mq5` was not
modified. The approved architecture (8 live components + offline
Validation + `phantom/shared/`) is unchanged in scope — this document
and its companion spec revisions close every Critical and High finding
from `PHANTOM_RED_TEAM_AUDIT.md` entirely within that existing
structure, plus one thin orchestrator module (`phantom/runtime/`, not a
ninth engine, per this task's own explicit instruction).

Phase 1's gate is unchanged and still unmet — checked again before
writing this: MetaEditor compile not run for real, MT5 demo validation
not executed, `docs/mt5_validation/08_signoff_template.md` still blank.
Nothing below begins or authorizes any implementation.

---

## 1. Updated architecture specification

The 9-component roster (`PHANTOM_FINAL_ARCHITECTURE.md`) and
`phantom/shared/`'s locked contents are unchanged. What changed is
*how they connect and who owns what wasn't previously owned*:

- **`phantom/runtime/runtime.py`** added — the thin orchestrator
  closing Finding 2.1. Full spec: `docs/specs/00_runtime_orchestrator.md`.
- **Strategy Engine** no longer depends on Market Intelligence Engine
  or System Reliability Engine directly — Runtime mediates both
  (`docs/specs/02_strategy_engine.md` §2, §8).
- **Portfolio Statistical Risk Engine** gains the pending-exposure
  reservation ledger and minimum-sample-size gate
  (`docs/specs/03_portfolio_statistical_risk_engine.md` §3, §6.1).
- **Market Intelligence Engine** is declared the system's one time/
  session/holiday authority (`docs/specs/04_market_intelligence_engine.md`
  §6.1) — not a new component, not logic added to `phantom/shared/`.
- **Prop Firm Compliance Engine**'s rule set expands from 5 to 10
  configurable categories (`docs/specs/05_prop_firm_compliance_engine.md`
  §"FTMO configuration model").
- **Research & Learning Engine** now records every cycle outcome (not
  only successful executions) and gains a reconciliation path for lost
  execution reports (`docs/specs/06_research_learning_engine.md` §3).
- **System Reliability Engine** gains the system-wide operator-
  authentication/authorization surface
  (`docs/specs/07_system_reliability_engine.md` §"Operator
  authentication").
- **Validation**'s existing "never imports a live orchestrator" rule
  is restated to explicitly include `phantom/runtime/`
  (`docs/specs/08_validation.md` §9).
- **PhantomBridgeEA**: unchanged code; a new specification,
  `docs/specs/09_bridge_concurrency_hardening.md`, documents the
  required thread-safety fix for a *future, separately-authorized*
  change.

Every one of the above is a spec addition to an already-approved
component, or a thin, logic-free orchestrator — nothing here is a new
engine, and nothing here redraws a component boundary.

## 2. Updated dependency graph

```
Phase 1: PhantomBridgeEA (built, frozen, gated; concurrency fix
         specified separately, docs/specs/09)
        |
        |  (execution + account telemetry)
        v
phantom/shared/  (Pair, Direction, Timeframe, Clock, Price, Volume,
                  Money, SCHEMA_VERSION, shared enums/value objects/
                  constants/error types -- locked, no business logic)
        |
        +---------------+------------------+------------------+
        v               v                  v                  |
  Evidence Engine  Market Intelligence  System Reliability     |
  (leaf + own       Engine (leaf + own   Engine (core: health/  |
  market data)      calendar data +      kill-switch/operator-  |
                     PhantomBridgeEA's   auth; reads Bridge's   |
                     server-time         ConnectionHealth)      |
                     telemetry)                                |
        |               |                  |                  |
        +-------+-------+                  |                  |
                v                           |                  |
        Strategy Engine (Evidence only --   |                  |
        no longer depends on Intelligence   |                  |
        or Reliability directly)            |                  |
                |                           |                  |
                v                           |                  |
     +----------------------------------------------------+   |
     |          phantom/runtime/runtime.py                |<--+
     |  depends on ALL 8 components -- the only file that  |
     |  is allowed to. Owns: sequencing, the halt-check,   |
     |  the entry-gate check, the tie-break cascade, the    |
     |  submit_command rejection propagation.               |
     +----------------------------------------------------+
                |
                v
     Portfolio Statistical Risk Engine (Strategy + Evidence +
     Intelligence + Bridge telemetry; owns the exposure-
     reservation ledger)
                |
                v
     Prop Firm Compliance Engine (Risk + Bridge account state +
     Market Intelligence's event classification, read-only)
                |
                v
     PhantomBridgeEA.submit_command (existing, unmodified interface)
                |
                v
     Research & Learning Engine (observer -- every outcome, every
     stopping stage, plus reconciliation from Bridge's
     TradeTransactionReport mirror)

Validation (offline): Evidence Engine's models.py + Strategy Engine's
playbook interface only -- never phantom/runtime/, never any live
orchestrator.
```

No cycle exists. Runtime is the only node with in-edges from all 8
components' interfaces and out-edges to none of their internals — it
calls, it is never called back into.

## 3. Updated runtime flow

Full step-by-step sequence, including the tie-break and rejection-
propagation branches, is specified in
`docs/specs/00_runtime_orchestrator.md` §5. Restated at the level this
task asked for:

```
Evidence
  ↓
Strategy               (returns 0+ candidate ideas)
  ↓
Market Intelligence    (entry gate; BLOCKED_* drops all candidates)
  ↓
[tie-break cascade, only if >1 candidate survived the gate]
  ↓
Portfolio Statistical Risk   (size or veto; reserves exposure)
  ↓
Prop Firm Compliance         (approve/reduce/reject; never enlarges)
  ↓
Bridge                       (submit_command; ErrorCode possible)
  ↓
Research & Learning (observer)   -- every outcome, every stage
  ↓
System Reliability (observer)    -- cycle health/duration/error report
```

`is_halted()` gates the *entire cycle*, checked once before "Evidence"
runs for any pair — it is not drawn as an arrow between two components
because it isn't a data handoff, it's whether the cycle runs at all.

## 4. Updated authority matrix

| Component | Sole authority | May never |
|---|---|---|
| PhantomBridgeEA | Execution | Score, size, decide, evaluate compliance |
| Evidence Engine | Scoring | Select a strategy, size, gate entries, calculate session/holiday time |
| Strategy Engine | Selection/confirmation | Size, gate entries itself, resolve its own ties, recompute regime |
| Market Intelligence Engine | News (incl. the one time/session/holiday authority) | Score price structure, size, select a strategy |
| Portfolio Statistical Risk Engine | Sizing (incl. exposure reservation) | Enforce prop-firm rules, select a strategy, execute |
| Prop Firm Compliance Engine | Rules (approve/reduce/reject; never increase) | Compute statistics, select a strategy, execute |
| Research & Learning Engine | None (observer/advisory only) | Write to any live engine, recompute Risk Engine's stats |
| System Reliability Engine | Reliability (halt authority + operator auth) | Make a trading decision |
| Validation | None (offline only) | Touch anything live, import `phantom/runtime/` |
| `phantom/runtime/` | None (orchestration only) | Contain business/trading/risk/strategy/compliance logic |
| `phantom/shared/` | None (value types only) | Contain any logic at all |

This is the literal enforcement target for every structural-boundary
test named across `docs/specs/00`–`09`.

## 5. Updated sequence diagram

```
Pair P, cycle N
───────────────
Runtime -> Reliability: is_halted()?
Reliability -> Runtime: false
Runtime -> Evidence: get_pair_evidence(P, now)
Evidence -> Runtime: PairEvidence(score=82, regime=TRENDING, ...)
Runtime -> Strategy: evaluate(P, now, evidence)
Strategy -> Runtime: (TradeIdea[BOS_FVG], TradeIdea[TREND_CONTINUATION])
Runtime -> Intelligence: get_entry_gate(P, now)
Intelligence -> Runtime: ALLOWED
Runtime -> Research: strategy_ranking()          [tie-break input]
Runtime -> Risk: portfolio_stats()               [tie-break input]
Runtime -> Intelligence: get_pair_intelligence(P, now)  [tie-break input]
Runtime: resolve tie -> TradeIdea[BOS_FVG] wins (higher evidence score)
Runtime -> Risk: evaluate(idea, portfolio, now)
Risk -> Runtime: SizingRecommendation(volume=0.5, tier=STANDARD)
  [Risk reserves exposure internally before returning]
Runtime -> Compliance: evaluate(sizing, account, now)
Compliance -> Runtime: TradeCommand(BUY, 0.5, ...)
Runtime -> Bridge: submit_command(command)
Bridge -> Runtime: None (accepted)
Runtime -> Research: record_trade(snapshot, outcome=SUBMITTED)
Runtime -> Reliability: record_cycle(report)
```

A rejected branch (illustrative — Compliance rejects):

```
...
Runtime -> Compliance: evaluate(sizing, account, now)
Compliance -> Runtime: ComplianceRejection(rule=daily_loss, ...)
Runtime -> Research: record_trade(snapshot, outcome=ComplianceRejection(...))
Runtime -> Reliability: record_cycle(report)      [Bridge never called]
```

## 6. Updated threat model

| Asset | Threat | Mitigation |
|---|---|---|
| Kill switch / emergency lockout / peg-policy block | Unauthenticated or spoofed "operator" action | Single `operator_auth` authority (System Reliability Engine), every action authenticated + authorized + audited unconditionally, no trusted-caller bypass (closes Finding 17.1) |
| Account balance/equity/login in logs | Exposure via log retention/export | Centralized redaction/retention policy in the one shared `logging.py` sink (closes Finding 18.1) |
| Research & Learning Engine's RAG surface | Prompt injection via untrusted content | RAG retrieval scoped to this system's own recorded trade memory only, never external/untrusted content (already specified, restated here) |
| `phantom/bridge`'s command queue | Concurrent-request race under `ThreadingHTTPServer` producing lost/duplicate state | Locking fix specified in `docs/specs/09_bridge_concurrency_hardening.md`, pending separate authorization |
| Compliance rule-set configuration | Unauthorized change silently loosening a hard limit | Configuration changes are one of the five `AdministrativeAction` types requiring authentication + audit |
| Cross-pair correlated exposure | Two correlated ideas both approved before either executes | Pending-exposure reservation ledger, owned solely by Risk Engine, serialized by Runtime (closes Finding 2.2) |
| Prop-firm contractual news restriction | Confused with Market Intelligence's general risk blackout, silently weakened by an unrelated tuning change | Modeled as an independent Compliance Engine rule that *reuses* Market Intelligence's classification but is separately configured (closes Finding 11.1) |

## 7. Updated concurrency model

- **`phantom/runtime/runtime.py`**: strictly serial, single-threaded,
  no concurrency primitives of its own. Per-pair steps for Evidence
  Engine and Market Intelligence Engine may be parallelized by an
  implementation (no shared mutable state between pairs at those
  stages). Risk Engine's `evaluate()` step **must** be serialized
  across pairs within a cycle, because its internal exposure
  reservation is shared, order-dependent state.
- **Components 2, 3, 4 (partially), 5, 6, 7, 8**: assume a
  single-threaded caller (Runtime); none are required to be internally
  thread-safe. This is what closes Finding 5.2 — not by adding locks to
  eight components, but by giving them a serial caller.
- **`phantom/bridge/`**: the one genuine exception. It independently
  serves the MT5 EA's own asynchronous HTTP traffic via
  `ThreadingHTTPServer`, decoupled from Runtime's cycle. This is why
  Finding 5.1's fix (`docs/specs/09_bridge_concurrency_hardening.md`)
  is scoped to exactly this component.

## 8. Updated operator model

Full specification: `docs/specs/07_system_reliability_engine.md`
§"Operator authentication". Summary: one authority (System Reliability
Engine), one `OperatorIdentity`/`OperatorCredentials`/
`AdministrativeAction`/`AuditRecord` model, five minimum administrative
actions (emergency stop, resume, manual override, maintenance-mode
toggle, configuration change), every action authenticated, authorized,
and audited — including denials. Compliance Engine's emergency lockout
and Market Intelligence Engine's peg/policy block both route through
this one surface rather than defining their own. The specific
credential mechanism is deliberately left open for a future, separately
-approved decision — this hardening pass commits to the seam existing
and being singular, not to an implementation.

## 9. Updated FTMO configuration model

Full specification: `docs/specs/05_prop_firm_compliance_engine.md`
§"FTMO configuration model". Ten configurable rule categories (daily
loss, overall drawdown, max positions, max trades/day, stop-loss
required, weekend holding, news restrictions, consistency rules,
profit-target tracking, trading-day tracking), all data-driven from a
named `ComplianceRuleSet` — no prop firm's name or values are
hard-coded in the engine's logic; a second prop firm is a second
configuration instance, never a second engine.

## 10. Updated testing requirements

Consolidated from every spec's own §10 (full detail lives there; this
is the cross-component checklist a reviewer can use without opening
all ten files):

- Runtime: sequencing, determinism, halt-gate, entry-gate, tie-break
  cascade (no-randomness proof), veto/rejection-propagation per stop
  point, no-idea test.
- Bridge concurrency (future change): concurrent-poll-and-report stress
  test, idempotency-under-concurrency, heartbeat-under-load,
  no-deadlock, full existing 85-test regression.
- Evidence Engine: per-detector fixtures, determinism, score/confidence
  consistency, no-independent-time-calculation.
- Strategy Engine: per-playbook fixtures, auto-discovery, multi-
  candidate (not mutual-exclusion), no-independent-regime.
- Portfolio Statistical Risk Engine: per-statistic fixed-seed fixtures,
  Risk Schedule table, determinism, type-level "cannot increase",
  pending-exposure reservation, reservation-release (all four
  `ReleaseReason`s), minimum-sample-size, hedging/netting aggregation.
- Market Intelligence Engine: per-classifier fixtures, entry-gate
  fixture suite, score/gate independence, DST-transition fixture,
  holiday-calendar fixture.
- Prop Firm Compliance Engine: per-rule fixtures across all ten
  categories, multi-prop-firm configuration test, never-enlarges,
  account-state-freshness, end-to-end `BridgeEngine` integration,
  emergency-lockout.
- Research & Learning Engine: structural boundaries (no recompute, no
  live-engine import), every-outcome recording, reconciliation.
- System Reliability Engine: kill-switch transitions, halt propagation,
  health-monitor staleness, unauthenticated-action-rejected, cross-
  component authorization, every-administrative-action audited.
- Validation: structural boundary (no live orchestrator, no
  `phantom/runtime/`), known-outcome regression, determinism,
  comparison ranking.
- Cross-cutting: at least one dual-degradation integration scenario
  (e.g. Market Intelligence *and* Risk Engine both unreachable at once)
  extending Phase 6's existing end-to-end test, per the audit's
  Finding 20.1.

## 11. Updated implementation roadmap

See `PHANTOM_IMPLEMENTATION_ROADMAP.md` §6.1 ("Architecture Hardening
amendments") for the full delta: new Phase 1R (bridge concurrency
remediation, separately gated), new Phase 2R (`phantom/runtime/`
skeleton, built incrementally from Phase 4a, fully wired by Phase 6),
and scope additions to Phase 3c (operator auth), Phase 5 (exposure
reservation + sample-size gate), and Phase 6 (full ten-category rule
set) folded into those phases' own original exit criteria rather than
appended as afterthoughts.

---

## Final readiness assessment

| Score | Value | Change from prior audit | Why |
|---|---|---|---|
| **Architecture** | **91/100** | 79 → 91 | Every Critical/High finding closed at the specification level: orchestration owned, race condition specified for remediation, exposure reservation owned, FTMO gaps modeled, tie-break deterministic, time authority singular, operator auth singular. Remaining gap to 100 is that these are specifications, not yet implementations. |
| **Reliability** | **80/100** | 63 → 80 | Orchestration ownership and the bridge concurrency fix (once actually applied) remove the two largest reliability risks found. Held below 90 because "no restart logic yet" (System Reliability Engine's `auto_recovery.py`, Phase 8) remains a deliberate, still-outstanding deferral, and the bridge fix itself has not yet been implemented — only specified. |
| **Maintainability** | **92/100** | 88 → 92 | The authority matrix and structural-boundary-test discipline now extend uniformly across all 8 components plus Runtime; single-responsibility files, no hidden coupling, no hand-maintained lists anywhere in the design. |
| **Institutional readiness** | **85/100** | 68 → 85 | DST/broker-time handling, hedging/netting awareness, and pending-exposure reservation close the three largest institutional-grade gaps found. Held below 90 pending real implementation and the operator-authentication mechanism's actual selection (deliberately left open here). |
| **FTMO readiness** | **83/100** | 60 → 83 | All four concrete FTMO gaps (news restriction, weekend holding, consistency/profit-target, stop-loss-required) are now modeled as explicit, configurable Compliance Engine rules with their own tests specified. Held below 90 because these are specifications awaiting implementation and, ultimately, verification against a real prop-firm account's actual rule text. |
| **Production readiness** | **55/100** (unchanged in kind, re-affirmed) | 52 → 55 | Marginal increase only, because **Phase 1's real MetaEditor compile and MT5 demo validation remain unmet** — checked again for this document. No amount of specification quality above that gate substitutes for it. This score cannot rise meaningfully until that gate clears. |

### Is the architecture now frozen for implementation?

**Yes, at the specification level — with two conditions restated, not
new:**

1. This document, `PHANTOM_FINAL_ARCHITECTURE.md`,
   `PHANTOM_IMPLEMENTATION_ROADMAP.md`, `PHANTOM_TECHNICAL_SPECIFICATIONS.md`,
   and `docs/specs/00`–`09` together now constitute the complete,
   hardened specification for Phantom vNext. Every Critical and High
   finding from `PHANTOM_RED_TEAM_AUDIT.md` is closed at this level.
   No further specification revision is anticipated absent a new
   finding.
2. **Implementation of Phase 2 onward (including `phantom/runtime/`
   and `phantom/shared/`) still does not begin** until Phase 1's three
   real-world gates (§0 of the roadmap) are satisfied and a separate,
   explicit go-ahead is given — this hardening pass revises
   specifications only, per its own instructions, and does not and
   cannot waive that prerequisite.

Frozen means: nothing about *what* to build or *how the pieces fit
together* should change without going through this same explicit,
audited process again. It does not mean implementation may start now.
