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
