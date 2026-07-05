# Changelog

Format loosely follows [Keep a Changelog](https://keepachangelog.com/).
Dates are UTC. This file starts 2026-07-05 forward — it is not a
retroactive record of everything before it. For the full history of
ADR-002 through ADR-013's implementation, the git log (every commit
carries an explicit message and `Co-Authored-By` line, per
`docs/adr/ADR-014-multi-agent-governance.md` §8/§11) remains the
authoritative record; this file does not attempt to reconstruct it.

Update convention: add a dated entry here as part of the "Implement"
phase of `.claude/agents/TEAM.md` §9's RPI workflow (or, for changes not
gated by that workflow, as part of `CLAUDE.md` §4's existing
"produce a change report" requirement).

## [Unreleased]

## 2026-07-06

### Added
- `.claude/agents/quant-validation-engineer.md`, `.claude/agents/
  integration-engineer.md`, `.claude/agents/ai-systems-engineer.md` —
  three new Governance Agents extending the Engineering Council from 10
  to 13, per explicit instruction. Quant Validation Engineer (statistical
  edge validation: walk-forward, Monte Carlo, overfitting, parameter
  robustness — advisory only, never edits strategy/scoring/risk code
  directly); Integration Engineer (post-hoc architectural verification:
  interface compatibility, dependency direction, circular-import
  detection, end-to-end pipeline wiring — verifies, does not design);
  AI Systems Engineer (AI-adjacent features only — trade memory, AI
  trade journal, explainable decisions, outcome analytics, NL dashboard,
  research assistant — hard-boundaried against ever generating a trade
  decision or influencing Scanner/Strategy Engine/Risk Engine/Compliance
  Engine/Execution Validator/MT5 Bridge/Position Manager).
- `docs/adr/ADR-014-multi-agent-governance.md` Amendment 2: documents the
  3 new Governance Agents (fills/authority/mandatory-review-trigger/RACI/
  de-duplication per role) and the decision to fold the requested
  "Reliability Engineer (SRE)" into the existing SRE role rather than add
  a 4th, duplicate agent.
- `TEAM.md` §1/§2/§3/§4/§5/§6/§7/§9 updated in place for the 3 new roles;
  SRE's §1/§4 entries extended to cover runtime-reliability review
  (recovery validation, chaos testing, restart validation) the request
  described under "Reliability Engineer (SRE)"; §5 RACI matrix corrected
  to reflect Watchdog/Dashboard's now-Accepted status (was stale "not yet
  drafted" text left over from before this session's earlier work); §6's
  prior "do not add an 11th agent" recommendation explicitly superseded
  for Quant Validation Engineer only, with the reversal's reasoning
  documented inline rather than silently overwritten.

### Changed (Council extension)
- Nothing in `phantom_pipeline/`, `phantom/`, or `tests/` — confirmed via
  `git diff --stat` showing zero output against all three. Full
  validation suite re-run (1066/1066 tests, `validate.py` 13/13,
  `scripts/check_architecture.py` clean) to confirm this documentation/
  governance-only change introduced no regression.

### Added
- `phantom_pipeline/orchestrator.py` — Phase 2 end-to-end Pipeline
  Orchestrator. Integration glue only (not a 13th stage, no new ADR):
  sequences the 12 already-Accepted stages (Data Pipeline through
  Dashboard, `ADR-013`/`ADR-002`-`ADR-012`) in `ADR-001`'s documented
  order via their existing public interfaces only, forwarding every
  output verbatim. `PipelineOrchestrator.run_scan_cycle()`,
  `record_fill()`, `manage_position()`, `evaluate_watchdog_health()`,
  `render_dashboard_snapshot()`.
- `tests/phantom_pipeline/orchestrator/` — 13 end-to-end integration
  tests: successful trade path, blocked trade path, rejected execution,
  MT5 acknowledgement, position management lifecycle, analytics
  recording, watchdog observation, dashboard visibility, replay
  determinism, pipeline restart, duplicate prevention, failure recovery,
  trace continuity.
- `docs/plans/pipeline-orchestrator.md` — the RPI Research/Plan/
  Validation artifact for this change.

### Changed
- Nothing in any of the 12 existing `phantom_pipeline/` stage packages
  or any pre-existing test file — confirmed via `git diff --stat`
  showing zero output against all of them. `scripts/check_architecture.py`
  passes clean (12 packages, no cycles, no private-state access).

## 2026-07-05

### Added
- `docs/adr/ADR-014-multi-agent-governance.md` Amendment 1: a Research →
  Plan → Implement (RPI) gated workflow, mapped entirely onto the
  existing 10 `TEAM.md` Council agents — no new agent, no new authority.
- `TEAM.md` §9: the RPI workflow's practical detail (phase-to-agent
  mapping, when it's mandatory vs. optional, artifact location).
- `docs/plans/` — the RPI Research/Plan/Validation artifact convention
  (`README.md`, `TEMPLATE.md`).
- `scripts/check_architecture.py` — a repeatable circular-import and
  cross-package private-state-access checker, formalizing the manual
  checks performed during the Phase 1 Certification Audit.
- `.claude/commands/rpi/research.md`, `plan.md`, `implement.md` — slash
  commands driving the three RPI phases via the existing Council agents.
- This file.

### Changed
- Nothing in `phantom_pipeline/` or `phantom/` — this entry is
  governance/tooling only; no trading logic, interface, or test was
  modified.
