# Phantom Architecture — Summary

**Status: Architecture phase complete. Implementation phase not started.**

This document summarizes the full accepted architecture as of 2026-07-04.
It is a derived summary — **every ADR in `docs/adr/` remains the sole
authority**; where this document and an ADR appear to disagree, the ADR
wins. This document does not itself authorize implementation of anything
(`CLAUDE.md` §1.10).

---

## 1. Mission

Phantom is an institutional-grade MT5 trading system for prop firms,
built on one deterministic, single-authority decision pipeline plus a
set of cross-cutting operational, governance, and evidentiary layers.
Capital preservation and deterministic behavior take priority over
feature count, per `CLAUDE.md`'s Engineering Charter.

`phantom/` and `phantom_institutional.py` are **reference-only** —
mined for proven algorithms and ideas across every ADR's own "Reference
material" section; neither is, or ever becomes, a running authority
(`ADR-001`).

---

## 2. The deterministic trading pipeline

```
Market Data → Data Pipeline (ADR-013)
           → Scanner (ADR-002)
           → Strategy Engine (ADR-003)
           → Scoring Engine (ADR-004)
           → Risk Engine (ADR-005)
           → Compliance Engine (ADR-006)
           → Execution Validator (ADR-007)
           → MT5 Bridge (ADR-008)
           → Position Manager (ADR-009)
           → Analytics (ADR-010)
```

Every stage is deterministic (`ADR-002` §14 and equivalents), every
stage's output is immutable once produced, and every stage answers
**exactly one question** — stated in its own ADR's Mission section. No
stage may recompute, override, or bypass another. The chain of
immutable objects — `ScannerObservation` → `CandidateTrade` →
`ScoreResult` → `RiskDecision` → `ComplianceDecision` →
`ExecutionDecision` → (broker events) → `PositionManagementDecision` —
is the backbone of the entire system; see `INTERFACE_SPECIFICATION.md`
for the full object catalog.

Two deliberate, explicitly-justified exceptions to strict determinism/
statelessness exist: Scanner's bounded session-window clock (`ADR-002`
§2) and the idempotency records at Execution Validator/MT5 Bridge
(`ADR-007` §7, `ADR-008` §7) — both bounded, TTL-pruned, and reconciled
with determinism in their own ADRs.

---

## 3. Cross-cutting layers (not pipeline stages)

| Layer | ADR | Role |
|---|---|---|
| Watchdog | `ADR-011` | Operational health monitoring and bounded infrastructure recovery. No trading authority. |
| Dashboard | `ADR-012` | Read-only human-facing visualization, sourced only from Prometheus and Analytics. No write capability anywhere. |
| Multi-Agent Governance | `ADR-014` | Classifies every actor (engineering, runtime, research, advisory, human) and their permissions; grants no new authority. |
| External Data Sources & API Governance | `ADR-015` | Single source of truth for every external dependency; vendor isolation, adapter rules, four-step approval gate for anything new. |
| AI News Intelligence | `ADR-016` | Advisory-only, human-and-Analytics-facing news layer. Zero live pipeline access. |
| Portfolio Manager | `ADR-017` | Whole-portfolio monitoring/recommendation. No live feedback loop into Risk Engine or Compliance Engine. |
| Replay & Certification Engine | `ADR-018` | Evidentiary gate for promoting a strategy or architectural change. Never deploys, never trades. |
| Self-Evolving Research Agent | `ADR-019` | Fully isolated research-lab process. Zero live pipeline access; promotion only through `ADR-018` + Human Review + normal engineering process. |

---

## 4. Architectural invariants (system-wide)

- **Single authority per responsibility** (`ADR-001`, `ADR-014` §13) —
  every responsibility has exactly one accountable owner; no agent owns
  another agent's decision logic.
- **Facts, never decisions**, until the stage whose job it is to decide
  (`ADR-002` §3 and equivalents throughout).
- **Fail-closed everywhere** — an unevaluable input never defaults to
  the permissive outcome (`ADR-005` Hard Rules, `ADR-006` Hard Rules,
  `ADR-007` Hard Rules, `ADR-013` §7).
- **No duplicate computation** — shared methodology is reused, never
  independently recomputed (the `swing_points()` lesson, cited in
  `ADR-002` §13, `ADR-013` §8, `ADR-017` §8).
- **Read-only, credential-scoped least privilege** — MT5 Bridge (`ADR-008`
  §10) is the sole stage with order-placement capability; every other
  stage is structurally incapable of it.
- **No implementation before acceptance** (`CLAUDE.md` §1.10) — a stage's
  code may not begin until its own ADR's Status is Accepted.
- **No automatic promotion** — a strategy or architectural change only
  reaches production through evidence (`ADR-018`) plus Human Review
  (`ADR-014` §7); no agent, including any AI-assisted role, may accept
  an ADR or approve a promotion unilaterally.

---

## 5. Full accepted ADR index

| # | Title | Status |
|---|---|---|
| ADR-001 | Single Authority Architecture | Accepted |
| ADR-002 | Scanner (+ Amendment 1) | Accepted |
| ADR-003 | Strategy Engine | Accepted |
| ADR-004 | Scoring Engine | Accepted |
| ADR-005 | Risk Engine | Accepted |
| ADR-006 | Compliance Engine | Accepted |
| ADR-007 | Execution Validator | Accepted |
| ADR-008 | MT5 Bridge (+ Amendment 1) | Accepted |
| ADR-009 | Position Manager | Accepted |
| ADR-010 | Analytics & Decision Provenance | Accepted |
| ADR-011 | Watchdog & Recovery | Accepted |
| ADR-012 | Dashboard & Observability | Accepted |
| ADR-013 | Data Pipeline (+ Amendment 1) | Accepted |
| ADR-014 | Multi-Agent Governance | Accepted |
| ADR-015 | External Data Sources & API Governance | Accepted |
| ADR-016 | AI News Intelligence | Accepted |
| ADR-017 | Portfolio Manager | Accepted |
| ADR-018 | Replay & Certification Engine | Accepted |
| ADR-019 | Self-Evolving Market Structure Research Agent | Accepted |

All 19 ADRs are Accepted as of 2026-07-04. No stage has been
implemented. See `IMPLEMENTATION_PLAN.md` for build order,
`INTERFACE_SPECIFICATION.md` for every shared object, and
`VALIDATION_MATRIX.md` for required tests and exit criteria per stage.

---

## 6. Known, flagged, non-blocking documentation follow-ups

Carried forward from prior architectural reviews this session — none of
these affect implementation readiness, all are documentation
synchronization items:

- `ADR-019`'s own "Depends on" header still cites `ADR-015` as
  "(Proposed)"; `ADR-015` is now Accepted.
- `ADR-012` does not yet name Portfolio Manager as a Dashboard data
  source (flagged in `ADR-017` §11).
- `TEAM.md`'s RACI table has no rows yet for Data Pipeline,
  Multi-Agent Governance, Replay & Certification Engine, or Portfolio
  Manager.
