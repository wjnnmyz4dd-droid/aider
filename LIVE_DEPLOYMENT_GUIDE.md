# Live Deployment Guide

Operator guide for taking Phantom from a validated PAPER deployment to a
live, funded MT5 account on a Windows VPS, using the Phase 5 deployment
package (`phantom_pipeline/deployment/`).

This guide describes **how to wire and operate** the deployment package.
It is not itself the deployment package's authority on any trading
decision — Scanner, Strategy Engine, Scoring Engine, Risk Engine,
Compliance Engine, Execution Validator, MT5 Bridge, and Position Manager
remain exactly as documented in `ADR-002` through `ADR-009`; nothing in
this guide or the package it describes changes any of their behavior.

## 1. Prerequisites

- A Windows VPS meeting `VPS_SETUP_GUIDE.md`'s requirements, with MT5
  installed and a **real, funded** account credential set (LIVE profile
  only — never reuse a DEV/PAPER MT5 login for LIVE).
- A PAPER deployment that has already passed forward validation
  (`phantom_pipeline/paper_trading/forward_test_engine.py`'s report) for
  a period the operator judges sufficient. This guide does not set that
  threshold — that is a business decision, not an engineering one.
- Every secret (`MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`, broker API
  keys if any) present in the VPS's environment, never committed to the
  repository, never logged in plaintext by any component in this
  package (`logging_manager.JsonFormatter` logs the log record's
  message only — callers are responsible for never passing a secret
  value into a log call).

## 2. Configuration profile (`ConfigurationManager`)

1. Load the `LIVE` profile: `ConfigurationManager().load_profile(DeploymentProfile.LIVE, env_mapping)`.
2. Validate before touching anything else:
   `ConfigurationManager().validate(config, env_mapping)`. If
   `result.valid` is `False`, **do not proceed** — every issue in
   `result.issues` is a startup blocker by construction (this manager
   has no "warning that isn't a blocker" path for LIVE).
3. Confirm `paper_trading_enabled` is `False` for LIVE — the
   `ConfigurationManager` already refuses to validate a LIVE profile with
   paper trading enabled, but this is also checked independently by
   `DeploymentValidator`'s `paper_trading_disabled_in_live` probe at
   go-live time (defense in depth, never a single point of failure).

## 3. Wiring the deployment (`ProductionDeploymentManager`)

Register one `ServiceDefinition` per managed service (data feed, MT5
bridge/terminal, the Phantom Python process, Watchdog, Dashboard), with
real `start`/`stop`/`health_check` callables and `depends_on` naming the
services each one requires running first. The manager topologically
orders startup and reverses it for shutdown — you do not need to order
the list yourself.

- **Start**: `manager.verify_dependencies()` first (empty tuple = clear
  to proceed), then `manager.start_all(now)`. A non-empty
  `aborted_reason` means nothing was started — fix the reported issue
  and retry.
- **Stop**: `manager.stop_all(now)` — always graceful, reverse dependency
  order.
- **Health**: `manager.health_check_all(now)` any time, safe to call on a
  running system without side effects.

## 4. Service supervision (`WindowsServiceManager`)

Register the same services (with `is_running`/`is_responsive` probes)
with a `WindowsServiceManager`, and run
`ensure_started_after_reboot`/`check_and_restart_crashed`/
`check_and_restart_hung` on a schedule (a Windows Scheduled Task or a
simple loop is sufficient — this package does not itself provide a
scheduler).

**Hard rule, enforced by the manager itself, not by operator discipline:**
MT5 is never restarted while `trade_in_progress` (an injected probe you
supply, backed by Position Manager's own `LifecycleState` — anything
other than `OPEN`/`CLOSED` means a trade is live) returns `True`. A
restart attempt during an active trade is logged as **deferred**, not
silently skipped — check `manager.restart_history` regularly.

## 5. Go-live validation (`DeploymentValidator`)

Before routing a single real order, run every one of the 10 required
checks (`REQUIRED_CHECK_NAMES`) with real probes wired to the real
system, and require `report.all_passed` before proceeding:

- `all_services_started`, `all_ports_respond`, `mt5_connected`,
  `dashboard_online`, `analytics_active`, `watchdog_active` — wire each
  to the corresponding real health signal.
- `paper_trading_disabled_in_live` — wire to
  `ConfigurationManager.validate(...).valid` for the LIVE profile.
- `risk_limits_loaded` — wire to confirming `RiskEngineConfig` was
  actually loaded from the LIVE profile's config source, not a default.
- `compliance_active` — wire to `ComplianceEngine` actually being
  constructed and reachable (e.g. its metrics object responding).
- `emergency_stop_functional` — wire to a probe that calls
  `PipelineOrchestrator.manage_position(..., compliance_kill_switch_active=True, ...)`
  against an isolated test position and asserts the returned action is
  `ManagementAction.EMERGENCY_CLOSE` — this is Position Manager's own,
  already-implemented mechanism; the probe only proves it is reachable
  end-to-end in this deployment, it does not implement a new one.

If `report.blockers` is non-empty, **do not go live**. See
`OPERATOR_CHECKLIST.md` for the full pre-flight sequence.

## 6. Ongoing operation

- `ProductionMonitoring.sample(now)` on a schedule, feeding
  `dashboard.config.DashboardConfig.infrastructure_components`.
- `enforce_retention_policy`/`archive_daily_logs` on a daily schedule.
- Regular backups per `DISASTER_RECOVERY.md`.

## 7. Rollback

If any post-go-live check regresses, prefer `stop_all` (graceful) over
an ungraceful kill. If a fast stop is required, the compliance
kill-switch → `EMERGENCY_CLOSE` path (§5) closes open positions before
the process itself is torn down.
