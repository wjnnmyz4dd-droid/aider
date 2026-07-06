# Plan: Phase 5 — Production deployment & operations infrastructure

Status: Validated
Owner (Plan phase): SRE
Touched components: new `phantom_pipeline/deployment` package, 4 new root
operator docs, only

---

## Research

- **Affected files and their dependencies**: none of the 13 existing
  `phantom_pipeline` packages are modified. A new 14th package,
  `phantom_pipeline/deployment/`, is added — the same posture
  `orchestrator.py` (Phase 2), the four real adapters (Phase 3), and
  `paper_trading` (Phase 4) already established: tooling built *around*
  an already-Accepted, already-implemented pipeline, never a new stage,
  never a new ADR. This is explicit in the task instruction ("No
  architecture redesign. No ADR modifications.").
- **Duplicate-logic check performed before writing anything** (`CLAUDE.md`
  §1.4):
  - `phantom_pipeline/watchdog/real_recovery_executor.py` already performs
    bounded, per-component OS-level recovery actions (`systemctl restart`,
    SIGHUP reload, log rotation) for the 8 `RecoveryActionType` values —
    but that is Watchdog's own *in-pipeline component recovery*, invoked
    only after `WatchdogEngine.attempt_recovery` decides eligibility. The
    Windows Service Manager this phase builds is a different, higher
    layer: whole-process/VPS-level service supervision (auto-start after
    reboot, crash/hang detection across the entire deployed stack — MT5
    terminal, Phantom process, dashboard) that exists *before* Watchdog
    itself is even running. It reuses `real_recovery_executor.py`'s
    proven dependency-injection shape (command runner / callback
    injected, never inline OS calls) rather than duplicating its
    internals, and never reimplements `RecoveryActionType`/
    `WatchdogEngine`'s eligibility, backoff, or freeze-and-escalate logic.
  - `PositionManager` already has a real emergency-stop mechanism —
    `ManagementAction.EMERGENCY_CLOSE`, driven by
    `compliance_kill_switch_active` (`position_manager/checks.py`
    `emergency_close`). The Deployment Validator's
    "emergency stop functional" check exercises this real, already-tested
    path (a caller-supplied probe that drives `PipelineOrchestrator.
    manage_position(..., compliance_kill_switch_active=True, ...)` and
    asserts `ManagementAction.EMERGENCY_CLOSE`) — it never invents a
    second, parallel kill-switch.
  - `dashboard.config.DashboardConfig` already lists
    `infrastructure_components` (`cpu`, `memory`, `disk`, `network`,
    `vps`, `watchdog`) that Dashboard expects to receive readings for —
    a real, previously-unfilled gap (no producer exists yet).
    `ProductionMonitoring` is that producer; it is read by whoever wires
    the system together and handed to Dashboard the same way every other
    already-produced object is, never a second dashboard.
  - No existing config, package, or doc defines DEV/PAPER/LIVE
    deployment profiles, a backup/restore mechanism, or a service
    lifecycle manager anywhere in the repository (confirmed via
    repository-wide search) — this is new ground, not a duplicate.
- **Touched stages' ADR status**: no stage's ADR is touched. `ADR-001`
  through `ADR-019` are all Accepted and read-only inputs to this
  package's design; nothing here proposes an ADR-020.
- **`python3 scripts/check_architecture.py` result (baseline, before this
  change)**: PASS — 13 packages, no cycles, no private-state access.
  This phase's cross-package imports (e.g. `from ..mt5_bridge.models
  import ConnectionState`, `from ..position_manager.models import
  LifecycleState`) target only another package's `.models` — never a
  private submodule — matching every prior phase's precedent.
- **Platform constraint**: the target runtime is a Windows VPS, but this
  repository's CI/dev environment is Linux. Every OS-touching operation
  (start/stop a service, detect a hung process, sample CPU/RAM/disk/
  network, restart on crash) is therefore built with an injectable seam
  (a constructor-supplied callable), with a small stdlib-only Linux/POSIX
  default implementation for local testing — exactly the shape
  `RealRecoveryActionExecutor` already proved out in Phase 3. Real
  Windows-specific defaults (`pywin32`/`nssm`/`sc.exe`) are a follow-up
  the operator docs flag explicitly, not something this phase fabricates
  and cannot test.

## Plan

New package `phantom_pipeline/deployment/`:

1. `models.py` — shared, side-effect-free types: `ServiceState`,
   `DeploymentProfile` (DEV/PAPER/LIVE), `ServiceDefinition`,
   `ServiceStatus`, `RestartReason`/`RestartRecord`,
   `ConfigValidationIssue`/`ConfigValidationResult`, `ResourceSample`,
   `MonitoringSnapshot`, `BackupTarget`/`BackupRecord`/`BackupManifest`,
   `RestoreResult`, `DeploymentCheckResult`/`DeploymentReadinessReport`.
2. `config_manager.py` — `ConfigurationManager`: loads a profile from an
   injected mapping (never reads `os.environ` directly, so tests never
   touch real process env), validates before startup (missing secrets,
   invalid MT5 account, wrong broker profile, LIVE-must-not-paper-trade).
3. `service_manager.py` — `WindowsServiceManager`: per-service DI seams
   (start/stop/is_running/is_responsive), auto-start-after-reboot,
   crash/hang detection and restart with a logged `RestartRecord`, and
   the hard rule "never restart MT5 while a trade is actively executing"
   via an injected `trade_in_progress` probe.
4. `deployment_manager.py` — `ProductionDeploymentManager`: one-command
   `start_all`/`stop_all` over a dependency-ordered
   `Sequence[ServiceDefinition]` (topological sort on `depends_on`),
   pre-launch dependency verification, post-start health verification,
   reverse-order graceful shutdown.
5. `logging_manager.py` — rotating + JSON-structured production logging,
   daily archive, crash-dump generation, retention-policy enforcement.
   Pure filesystem/stdlib `logging`, no new dependency.
6. `monitoring.py` — `ProductionMonitoring`: injected samplers for CPU/
   RAM/disk/network latency/MT5 connection quality/Python process
   health/dashboard health, with stdlib-only Linux-compatible defaults;
   threshold evaluation feeding Dashboard's already-declared
   `infrastructure_components`.
7. `backup_manager.py` — `BackupManager`: checksummed backup/restore for
   configuration, SQLite databases (via `sqlite3`'s online backup API,
   never a raw copy of a live DB file), analytics, and trade history;
   `verify_integrity` re-checksums a backup independently of the record
   claiming it.
8. `deployment_validator.py` — `DeploymentValidator`: the 10 named
   go-live checks as injected probes, aggregated into a
   `DeploymentReadinessReport` with `blockers` populated whenever a
   check fails.

Tests: `tests/phantom_pipeline/deployment/`, one file per module, using
fakes for every injected seam (mirrors every existing adapter test's
style) — no test depends on a real Windows service, a real MT5 terminal,
or real `/proc` filesystem contents beyond what's genuinely portable.

Docs (repository root, matching `ARCHITECTURE.md`/`AUDIT.md`/`RELEASE.md`'s
existing convention): `LIVE_DEPLOYMENT_GUIDE.md`, `VPS_SETUP_GUIDE.md`,
`DISASTER_RECOVERY.md`, `OPERATOR_CHECKLIST.md`.

## Validation

`python3 -m compileall`, `python3 -m unittest discover -s
tests/phantom_pipeline`, `python3 validate.py`, `python3
scripts/check_architecture.py` — all four must stay green, with the
package count rising from 13 to 14 and zero diff against any existing
file.
