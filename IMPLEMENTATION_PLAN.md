# Phantom Implementation Plan

**Status: Architecture phase complete. Implementation phase NOT STARTED
for every stage below.**

This plan defines build order, dependencies, and exit criteria for each
stage, derived from the 19 Accepted ADRs in `docs/adr/`. It does not
authorize implementation on its own — per `CLAUDE.md` §1.10, each
stage's own ADR being Accepted is the precondition, and per `ADR-014`
§7 a separate, explicit Human Review "implementation approval" is
required before code begins on any stage. **No code exists for any
stage as of this document's creation.**

Every stage below carries:

- **Order** — build sequence.
- **ADR** — the authoritative source; do not implement beyond what it
  specifies.
- **Depends on** — which earlier-built stages/objects this stage
  consumes.
- **Owner** — the RACI Accountable party (`.claude/agents/TEAM.md` §5,
  or the ADR's own "Owner" line where `TEAM.md` has no row yet).
- **Exit criteria** — drawn directly from the ADR's own Acceptance
  Criteria section; a stage is not "done" until every one of these,
  plus the cross-cutting exit criteria in §0, are met.
- **Status** — `NOT STARTED` for every stage in this document.

---

## 0. Cross-cutting exit criteria (apply to every stage)

Before any stage below is considered complete, in addition to its own
listed exit criteria:

- `validate.py` green, no unexplained score/decision drift (`TEAM.md`
  §3, mandatory for every merge).
- Code Reviewer sign-off (`TEAM.md` §3, mandatory for every merge).
- Test Results Analyzer sign-off confirming the stage's own required
  tests (`VALIDATION_MATRIX.md`) pass.
- Any mandatory reviewer named in the stage's own ADR header (e.g.
  Security Architect for Compliance Engine, Execution Validator) has
  signed off, per `TEAM.md` §3's routing table.
- Boundary/type-level test passes: the stage's output object is
  structurally incapable of holding any forbidden field (every ADR's
  own Never/Forbidden table).
- A distinct, human-initiated instruction authorized implementation to
  begin on this specific stage (`ADR-014` §7, "Implementation
  approval") — never inferred from ADR acceptance alone.

---

## 1. Build order

| Order | Stage | ADR | Depends on | Owner | Status |
|---|---|---|---|---|---|
| 1 | Data Pipeline | `ADR-013` | `ADR-001`, `ADR-015` (vendor governance) | Backend Architect | **NOT STARTED** |
| 2 | Scanner | `ADR-002` | Data Pipeline's `NormalizedBar`/`HistoricalSeries` output contract | Software Architect | **NOT STARTED** |
| 3 | Strategy Engine | `ADR-003` | Scanner's `ScannerObservation` | Multi-Agent Systems Architect | **NOT STARTED** |
| 4 | Scoring Engine | `ADR-004` | Strategy Engine's `CandidateTrade` | Software Architect | **NOT STARTED** |
| 5 | Risk Engine | `ADR-005` | Scoring Engine's `ScoreResult` | Backend Architect | **NOT STARTED** |
| 6 | Compliance Engine | `ADR-006` | Risk Engine's `RiskDecision`; Data Pipeline's `MarketSnapshot` (live calendar/spread/market_status) | Security Architect | **COMPLETE (Phase 1)** |
| 7 | Execution Validator | `ADR-007` | Compliance Engine's `ComplianceDecision`; Data Pipeline's `MarketSnapshot` | Backend Architect | **COMPLETE (Phase 1)** |
| 8 | MT5 Bridge | `ADR-008` (+ Amendment 1) | Execution Validator's `ExecutionDecision`; **must be built to its full Amendment-1 scope, since Position Manager (stage 9) depends on the amended `PositionAdjustmentRequest`/`PositionCloseRequest` input contract** | Backend Architect | **COMPLETE (Phase 1)** |
| 9 | Position Manager | `ADR-009` | MT5 Bridge's `ExecutionReceipt`/`FillReport`; routes `PositionCloseRequest`/`PositionAdjustmentRequest` back through MT5 Bridge (`ADR-008` Amendment 1) | Backend Architect | **COMPLETE (Phase 1)** |
| 10 | Analytics | `ADR-010` | Collects outputs from every stage above (`ADR-002`–`ADR-009`) | Software Architect | **COMPLETE (Phase 1)** |
| 11 | Watchdog | `ADR-011` | Health/metrics signals already exported by every stage above (`ADR-002`–`ADR-010`) | SRE | **NOT STARTED** |
| 12 | Dashboard | `ADR-012` | Prometheus (via Watchdog/every stage's metrics) and Analytics' read-only query surface only | Backend Architect | **NOT STARTED** |
| 13 | Portfolio Manager | `ADR-017` | Position Manager's/Analytics' current-state view (`ADR-009` §5, `ADR-010` §5); reuses Risk Engine's correlation methodology (`ADR-005` §11) | Security Architect | **NOT STARTED** |
| 14 | Replay & Certification Engine | `ADR-018` | Data Pipeline's `ReplaySeries` (`ADR-013` §10); Analytics' replay decision inputs (`ADR-010` §8); Data Pipeline's `MarketSnapshot` for shadow trading (`ADR-013` Amendment 1) | Test Results Analyzer | **NOT STARTED** |
| 15 | AI News Intelligence | `ADR-016` | None on the live pipeline (fully isolated, `ADR-016` §2); its own dedicated feed requires `ADR-015` §12 approval before implementation | Security Architect | **NOT STARTED** |
| 16 | Self-Evolving Research Agent | `ADR-019` | Analytics' historical data (`ADR-010`); Replay & Certification Engine as the promotion gate (`ADR-018`); its own dedicated feed/LLM dependency requires `ADR-015` §12 approval | Security Architect | **NOT STARTED** |

**Not build stages — foundational/governance documents that inform every
stage above rather than occupying a slot in this sequence:** `ADR-001`
(single-authority architecture itself), `ADR-014` (Multi-Agent
Governance — already operative via `TEAM.md`'s existing process), and
`ADR-015` (External Data Sources & API Governance — a policy/approval
framework every stage's adapters must honor, not itself an implemented
stage).

---

## 2. Notes on this ordering (observations, not contradictions)

- **Stage 8 (MT5 Bridge) and stage 9 (Position Manager) are mutually
  referential in scope, not in build order.** `ADR-008` Amendment 1 was
  written specifically to accept Position Manager's outputs; MT5
  Bridge's *full* accepted contract (including Amendment 1) must be
  implemented at stage 8, even though the requests it handles
  (`PositionCloseRequest`/`PositionAdjustmentRequest`) don't exist until
  stage 9 is built. This is a specification-completeness note, not a
  circular dependency — MT5 Bridge's contract is fully specified before
  either stage begins.
- **AI News Intelligence (stage 15)'s placement is a priority choice,
  not a dependency requirement.** Per `ADR-016` §2, it "has no position
  in that pipeline at all" and could be built at any point without
  affecting any other stage — its late placement reflects that it is
  advisory-only and non-blocking, not that anything depends on the
  pipeline being complete first.
- **Portfolio Manager (stage 13) does not require Watchdog (11) or
  Dashboard (12) to exist.** Its actual dependencies (Position Manager,
  Analytics, Risk Engine's correlation methodology) are all satisfied by
  stage 10. Its position after Watchdog/Dashboard in this plan is a
  sequencing choice, not a technical requirement — flagged for
  transparency, not a defect in the given order.

No actual contradiction was found in the given build order: every
dependency implied above resolves to an earlier-numbered stage.

---

## 3. Implementation-readiness gate (restated from `CLAUDE.md` §1.10 and `ADR-014` §7)

For every stage above, all of the following must be true before its row
in this document may be updated from `NOT STARTED`:

1. The stage's own ADR Status is Accepted. *(True for all 19 ADRs as of
   this document.)*
2. A human has issued a distinct instruction to begin implementation on
   that specific stage.
3. The Engineering Council's applicable workflow (`TEAM.md` §2) is
   followed: Minimal Change Engineer implements, Code Reviewer reviews,
   Test Results Analyzer validates, plus any mandatory reviewer named in
   `TEAM.md` §3's routing table for the touched path.

This document does not satisfy condition 2 for any stage — it is a
plan, not an authorization.
