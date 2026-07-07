# Copy to VPS

How to move `DEPLOYMENT_PACKAGE/` onto the Windows VPS and safely replace
whatever is already there. **Do not assume any old VPS files are
usable** — this procedure always backs up first, then overwrites, never
the reverse.

## 1. What's in this package

`DEPLOYMENT_PACKAGE/` contains only the current, working Phantom runtime:

```
DEPLOYMENT_PACKAGE/
  phantom_pipeline/        16 packages: analytics, compliance_engine,
                            dashboard, data_pipeline, deployment,
                            execution_validator, knowledge, mt5_bridge,
                            orchestrator.py, paper_trading,
                            position_manager, research_desk, risk_engine,
                            scanner, scoring_engine, strategy_engine,
                            watchdog
  config/                  *.env.template for DEV/PAPER/LIVE
  scripts/                 start_phantom.py, start_phantom.bat, stop_phantom.bat
  requirements.txt
  VERSION.txt              exact source commit this build came from
```

`knowledge/` (`ADR-020`) and `research_desk/` (`ADR-021`) are read-only
observers — trade memory/semantic search and market-research/journal
agents respectively. Neither has any decision, execution, risk,
compliance, or scoring authority, and neither is wired into
`start_phantom.py`'s trading loop; they are available to import and wire
up separately per `KNOWLEDGE_DEPLOYMENT_GUIDE.md`/`RESEARCH_DESK_GUIDE.md`
if you want them running on this VPS, but their absence from the running
process has zero effect on trading behavior.

Deliberately **excluded**: `tests/`, `docs/adr/`, `AUDIT.md`,
`IMPLEMENTATION_PLAN.md`, `VALIDATION_MATRIX.md`, `docs/plans/`,
`CLAUDE.md`, `.claude/`, and the legacy `phantom/` +
`phantom_institutional.py` (reference-only, not a running authority per
`CLAUDE.md` §2 — packaging them would risk running two competing
systems on the same VPS).

Verify what you actually received before copying anything:

```
type DEPLOYMENT_PACKAGE\VERSION.txt
```

Confirm the commit hash matches what you expect to deploy.

## 2. Back up the existing VPS installation first

**Never overwrite without a backup, even if the existing VPS files are
believed to be stale.**

On the VPS, in an elevated PowerShell/cmd prompt:

```
set STAMP=%date:~-4%%date:~4,2%%date:~7,2%-%time:~0,2%%time:~3,2%%time:~6,2%
mkdir C:\phantom_backups\pre-deploy-%STAMP%
xcopy /E /I /H C:\phantom C:\phantom_backups\pre-deploy-%STAMP%\phantom
```

Confirm the backup directory is non-empty and roughly the expected size
before proceeding — an interrupted `xcopy` is not a backup.

If `phantom_pipeline/deployment`'s `BackupManager` is already running on
this VPS (i.e. this is not the very first deployment), also take one via
its own mechanism so the SQLite databases are backed up through
`sqlite3`'s online backup API rather than a raw file copy:

```
python -c "from phantom_pipeline.deployment import BackupManager; from datetime import datetime, timezone; BackupManager(r'C:\phantom_backups').backup_database([r'C:\phantom\<your.db>'], datetime.now(timezone.utc))"
```

## 3. Overwrite

Only after step 2's backup is confirmed:

```
rmdir /S /Q C:\phantom\phantom_pipeline
xcopy /E /I /H DEPLOYMENT_PACKAGE\phantom_pipeline C:\phantom\phantom_pipeline
xcopy /E /I /H DEPLOYMENT_PACKAGE\scripts C:\phantom\scripts
xcopy /E /I /H DEPLOYMENT_PACKAGE\config C:\phantom\config
copy DEPLOYMENT_PACKAGE\requirements.txt C:\phantom\requirements.txt
copy DEPLOYMENT_PACKAGE\VERSION.txt C:\phantom\VERSION.txt
```

**Never overwrite `C:\phantom\config\*.env`** (only the `*.env.template`
files ship in this package) — your real secrets live in the `.env` files
you created from the templates, not in anything this package overwrites.

## 4. Install/update dependencies

```
pip install -r C:\phantom\requirements.txt
```

## 5. Verify before starting

Follow `VERIFY_DEPLOYMENT.md` in full before running `START_PHANTOM.md`'s
startup procedure — do not skip straight to starting the service on the
strength of a successful copy alone.

## 6. Rollback

If verification fails, restore from the step-2 backup:

```
rmdir /S /Q C:\phantom\phantom_pipeline
xcopy /E /I /H C:\phantom_backups\pre-deploy-%STAMP%\phantom\phantom_pipeline C:\phantom\phantom_pipeline
```
