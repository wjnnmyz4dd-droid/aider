# Operator Checklist

Print-and-check reference for a Phantom deployment operator. See
`LIVE_DEPLOYMENT_GUIDE.md`/`VPS_SETUP_GUIDE.md`/`DISASTER_RECOVERY.md` for
the full explanation behind each item.

## Before any startup (DEV, PAPER, or LIVE)

- [ ] `ConfigurationManager.load_profile` + `.validate(...)` run against
      the real environment; `result.valid` is `True`.
- [ ] Every required secret (`MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`)
      present as a real Windows environment variable — never in a
      committed file.
- [ ] `ProductionDeploymentManager.verify_dependencies()` returns an
      empty tuple.
- [ ] `python -m compileall`, `python -m unittest discover -s
      tests\phantom_pipeline`, `python validate.py`, `python
      scripts\check_architecture.py` all green on this exact VPS.

## Startup

- [ ] `ProductionDeploymentManager.start_all(now)` → `result.all_started`
      is `True`; if not, read `result.aborted_reason` or the first
      non-healthy `ServiceStatus` and resolve it before retrying.
- [ ] `WindowsServiceManager.ensure_started_after_reboot` confirmed
      registered for every managed service, scheduled to run after every
      VPS boot.

## Before going LIVE specifically (in addition to the above)

- [ ] `paper_trading_enabled` is `False` in the loaded profile.
- [ ] `DeploymentValidator.run(DeploymentProfile.LIVE, now)` →
      `report.all_passed` is `True` and `report.blockers` is empty. Do
      not proceed on a partial pass.
- [ ] Every one of the 10 required checks has a **real** probe wired in
      (not a placeholder returning `True`) — confirm this by reading the
      wiring code, not by trusting the report alone.
- [ ] `emergency_stop_functional` probe specifically verified against
      the real `PositionManager.EMERGENCY_CLOSE` path in a staging run
      before the first live order.
- [ ] MT5 account confirmed to be the intended **funded** account (not a
      demo/paper account) by an operator who manually checked the MT5
      terminal itself, independent of what the config file claims.
- [ ] A verified, checksummed backup of configuration + databases exists
      from within the last 24 hours (`BackupManager.verify_integrity`).

## Ongoing (daily)

- [ ] `ProductionMonitoring.sample(now)` shows no unexpected breach in
      `evaluate(...)`.
- [ ] `WindowsServiceManager.restart_history` reviewed for any
      **deferred** MT5 restart (a hung/crashed MT5 during an active
      trade) — confirm it recovered on the next check, and that no order
      was left in an ambiguous state.
- [ ] `archive_daily_logs` + `enforce_retention_policy` ran (check the
      archive directory's most recent timestamp).
- [ ] Full backup set created and `verify_integrity`-checked.

## Incident response

- [ ] Check `crash_dumps/` for a structured dump before anything else.
- [ ] Prefer `ProductionDeploymentManager.stop_all` (graceful) over an
      ungraceful process kill.
- [ ] If a live position must be closed immediately, use the real
      compliance kill-switch path (`compliance_kill_switch_active=True`
      into `PipelineOrchestrator.manage_position`) — never a manual MT5
      terminal action that bypasses Phantom's own audit trail, unless
      Phantom itself is confirmed unreachable.
- [ ] After any incident, restore from the last verified backup only
      after confirming the restore target service is fully stopped.

## Shutdown (planned maintenance)

- [ ] Confirm no trade is actively executing (`trade_in_progress` probe
      returns `False`) before a manual MT5 restart or VPS reboot.
- [ ] `ProductionDeploymentManager.stop_all(now)` → `result.all_stopped`
      is `True`.
