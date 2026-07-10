# Phantom vNext — Technical Specifications

Status: **specification only.** No production code was written. No new
package was created (`docs/specs/` holds documentation, not a Python
package). No existing code was modified.

## Gate status (unchanged)

Phase 1 remains blocked pending real MetaEditor compilation and MT5
demo validation — checked again before writing this document, nothing
has changed:

1. MetaEditor compile — not yet run for real.
2. MT5 demo validation (`docs/mt5_validation/02_demo_validation_plan.md`,
   31 tests) — not yet executed.
3. `docs/mt5_validation/08_signoff_template.md` — still blank.

Nothing in this document is implementation or an implementation
authorization. It is the depth of specification requested for the
eight remaining approved components, produced while that gate stays
closed, per this task's own explicit instruction to specify rather
than build.

## What this is

Full technical specifications — purpose, responsibilities, public
interfaces, inputs, outputs, internal data models, decision authority,
dependencies, explicit non-responsibilities, test plan, performance
requirements, failure modes, security considerations, and logging
requirements — for each of the eight remaining approved components,
plus the detailed strategy/scoring/intelligence framework content
requested alongside them.

| File | Component | Extra content |
|---|---|---|
| `docs/specs/00_runtime_orchestrator.md` | `phantom/runtime/` (thin orchestrator, not a 9th engine) | Added by Architecture Hardening — closes Red Team Audit Finding 2.1 |
| `docs/specs/01_evidence_engine.md` | Evidence Engine | Scoring framework: individual pair scoring, the 65-point qualification threshold's actual enforcement point, confidence explanation mechanics |
| `docs/specs/02_strategy_engine.md` | Strategy Engine | All five playbooks in full detail: market conditions, entry, exit, invalidation, preferred sessions, suitable pairs; tie-break cascade (Architecture Hardening) |
| `docs/specs/03_portfolio_statistical_risk_engine.md` | Portfolio Statistical Risk Engine | The full Risk Schedule table restated in context; pending-exposure reservation and minimum-sample-size gate (Architecture Hardening) |
| `docs/specs/04_market_intelligence_engine.md` | Market Intelligence Engine | Pair-specific news scoring, Pair Safety Score, London/New York session preference, high-impact blackout rules, currency-peg/policy handling; the one time/session/holiday authority (Architecture Hardening) |
| `docs/specs/05_prop_firm_compliance_engine.md` | Prop Firm Compliance Engine | Ten-category FTMO configuration model (Architecture Hardening) |
| `docs/specs/06_research_learning_engine.md` | Research & Learning Engine | Every-outcome recording + reconciliation path (Architecture Hardening) |
| `docs/specs/07_system_reliability_engine.md` | System Reliability Engine | Operator authentication model (Architecture Hardening) |
| `docs/specs/08_validation.md` | Validation (offline only) | |
| `docs/specs/09_bridge_concurrency_hardening.md` | PhantomBridgeEA (spec revision only, no code change) | Added by Architecture Hardening — closes Red Team Audit Finding 5.1 |

See `PHANTOM_ARCHITECTURE_HARDENING.md` for the consolidated hardening
pass: updated dependency graph, runtime flow, authority matrix, threat
model, concurrency model, operator model, FTMO configuration model
summary, testing requirements, roadmap deltas, and final readiness
assessment.

## What this is not

- Not implementation. No file under `phantom/` beyond what already
  exists (`phantom/bridge/`, frozen) was touched.
- Not a new architecture. Every interface, data model, and dependency
  named here matches `PHANTOM_FINAL_ARCHITECTURE.md`'s locked component
  roster and `PHANTOM_IMPLEMENTATION_ROADMAP.md`'s locked build order,
  Risk Schedule, and Market Intelligence deltas exactly — nothing here
  introduces a ninth component, a new package, or a new layer.
- Not an approval to begin Phase 2. Implementation of `phantom/shared/`
  or any of the eight components still requires both the Phase 1 gate
  above and a separate, explicit go-ahead, per every prior message in
  this thread.

## Cross-cutting contracts restated (for reviewer convenience)

These appear in full inside the individual specs; listed here once so
a reviewer can check consistency across all eight without opening
every file:

- **Sizing can only shrink downstream of Risk Engine.**
  `SizingRecommendation` (Risk Engine spec §6) is structurally
  incapable of being increased; Compliance Engine (spec §7) may only
  shrink or reject it.
- **Compliance Engine's approved output is exactly
  `phantom.bridge.models.TradeCommand`** — the real, already-built
  Phase 1 shape, submitted through the existing
  `BridgeEngine.submit_command`. No new execution path is introduced.
- **Research & Learning Engine reads, never recomputes, Risk Engine's
  rolling statistics** — enforced by a structural-boundary test named
  in both specs.
- **Market Intelligence Engine's `get_entry_gate` is a mandatory,
  non-overridable precondition**, architecturally distinct from its
  advisory scores (`NewsScore`/`MarketImpactScore`/`PairSafetyScore`),
  and distinct in mechanism between scheduled-calendar blackouts
  (fixed pre/post window) and peg/policy events (held until explicitly
  cleared).
- **System Reliability Engine's kill switch is a distinct, higher
  authority than PhantomBridgeEA's own transport-level emergency stop**
  — every live component's decision function checks `is_halted()` as a
  precondition, the same pattern as the entry gate.
- **Evidence Engine has no decision authority** — the 65-point
  qualification threshold it reports is enforced by Risk Engine's Risk
  Schedule, not by Evidence Engine itself.
- **Validation never imports a live component's orchestrator**, only
  `models.py` types — structurally enforced the same way Phase 1's own
  boundary test already works.

## Stop condition

These are the complete technical specification documents requested.
Nothing was implemented. Awaiting approval before any Phase 2 build
begins, and awaiting the Phase 1 real-MT5 gate independently of that
approval.
