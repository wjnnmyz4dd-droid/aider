# Copy to VPS

How to move a Titan Protocol Windows release onto a VPS and safely
replace whatever is already there. **Do not assume any old VPS files are
usable** — this procedure always backs up first, then overwrites, never
the reverse.

This describes the current `deployment_windows/` release (built from
`titan_protocol/` + `mt5/`), extracted via `install.py`. It supersedes
the earlier `DEPLOYMENT_PACKAGE/`-based workflow this document used to
describe — that directory no longer exists in this repository.

## 1. What's in this package

`titan_protocol_windows_complete_release.zip` contains:

```
install.py                 master installer
start.py / stop.py / restart.py / health_check.py
install_mt5_files.py       copies + personalizes the MT5 EA
config_loader.py
requirements.txt           empty of packages -- the live runtime is stdlib-only
config/titan_protocol_config.example.json
titan_protocol/            the live engine packages (bridge, evidence_engine,
                            market_intelligence, strategy_engine, risk_engine,
                            compliance_engine, compliance_state_store,
                            runtime, reliability, market_data_ingestion,
                            news_ingestion)
mt5/                        TitanProtocolEA.mq5 + TitanProtocolEA.set
WINDOWS_OPERATOR_GUIDE.md
KNOWN_GAPS.md
RELEASE_MANIFEST.json      source commit, build timestamp, every file's SHA-256
```

Deliberately **excluded** from the live release: `tests/`, `docs/adr/`,
and the `knowledge`/`research_desk` subsystems (read-only intelligence
packages that are not wired into any current entry point).

Verify what you actually received before copying anything:

```
type RELEASE_MANIFEST.json
```

Confirm `source_commit_sha` matches the commit you expect to deploy, and
that `file_count` matches what you extracted.

## 2. Back up the existing VPS installation first

**Never overwrite without a backup, even if the existing VPS files are
believed to be stale.**

On the VPS, in an elevated PowerShell/cmd prompt (adjust
`C:\TitanProtocol` if you installed elsewhere):

```
set STAMP=%date:~-4%%date:~4,2%%date:~7,2%-%time:~0,2%%time:~3,2%%time:~6,2%
mkdir C:\TitanProtocol_backups\pre-deploy-%STAMP%
xcopy /E /I /H C:\TitanProtocol C:\TitanProtocol_backups\pre-deploy-%STAMP%
```

Confirm the backup directory is non-empty and roughly the expected size
before proceeding — an interrupted `xcopy` is not a backup. This single
copy covers `titan_protocol_config.json`, the generated Bridge API key
file, `logs\`, `state\`, and `data\` — there is no separate database
backup mechanism to run, since this deployment layer has no database.

## 3. Stop the running instance, then overwrite

```
cd C:\TitanProtocol
python stop.py
```

Only after step 2's backup is confirmed and `stop.py` reports a clean
shutdown, extract the new release ZIP over the existing install
directory. **Never overwrite these files**, since they hold your live
secrets/state, not shipped package content:

- `titan_protocol_config.json` (your real configuration — only
  `config\titan_protocol_config.example.json` ships in the package)
- `.bridge_api_key.secret` (the generated Bridge API key, if you let
  `install.py` generate one instead of using an environment variable)
- `logs\`, `state\`, `data\` (runtime output)

Everything else — `install.py`, `start.py`, `stop.py`, `restart.py`,
`health_check.py`, `install_mt5_files.py`, `config_loader.py`,
`titan_protocol\`, `mt5\` — is safe to overwrite from the new package.

## 4. Re-run the installer

```
python install.py
```

`install.py` re-verifies the virtual environment, dependencies (a fast
no-op — the live runtime has zero third-party dependencies), folder
structure, configuration, Bridge (socket transport by default, with an
automatic HTTP fallback listener per ADR-034 Amendment 3), Runtime, and
Reliability, then re-personalizes the MT5 EA `.set` file with your
existing `titan_protocol_config.json` values, and starts Titan Protocol.
See `WINDOWS_OPERATOR_GUIDE.md` for the full step-by-step walkthrough.

## 5. Verify before trusting it with a live account

Follow `VERIFY_DEPLOYMENT.md` in full before attaching the EA to a
funded account — do not skip straight to trading on the strength of a
successful copy alone.

## 6. Rollback

If verification fails, restore from the step-2 backup:

```
python stop.py
rmdir /S /Q C:\TitanProtocol
xcopy /E /I /H C:\TitanProtocol_backups\pre-deploy-%STAMP% C:\TitanProtocol
```
