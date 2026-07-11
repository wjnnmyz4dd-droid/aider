# Phantom Windows Operator Guide

Read `KNOWN_GAPS.md` first. This deployment layer brings up Phantom's
Bridge (execution channel) and Reliability monitoring honestly and
completely — it does **not** run a live trading decision loop, because
no market-data ingestion component exists in this codebase yet. Every
step below is accurate to what actually happens; none of it overclaims
readiness for live trading.

## 1. Extract the ZIP

Extract `phantom_windows_deployment.zip` anywhere convenient (e.g. your
Desktop or Downloads) using Windows' built-in "Extract All" (right-click
the zip → Extract All) or 7-Zip.

## 2. Move it to C:\Phantom

Move the extracted folder so its contents sit directly under
`C:\Phantom`. After this step you should have:

```
C:\Phantom\phantom\               <- the 8 required engine packages
C:\Phantom\mt5\                   <- PhantomBridgeEA.mq5 + .set
C:\Phantom\deployment_windows\    <- everything in this guide
C:\Phantom\PHANTOM_MT5_DEPLOYMENT_AUDIT.md
```

If you use a different drive/path, every step below still works —
just substitute your actual path for `C:\Phantom`.

## 3. Install Python if missing

Check first: open Command Prompt and run `python --version`. If that
fails or reports a version below 3.9, install Python 3.9+ **64-bit**
from https://www.python.org/downloads/windows/ . During install, check
**"Add python.exe to PATH"** — `setup_phantom.bat` depends on this.

## 4. Run setup_phantom.bat

Before running it, copy the config template and edit it:

```
cd C:\Phantom\deployment_windows
copy config\phantom.config.template.ini phantom.config.ini
notepad phantom.config.ini
```

Edit at minimum: `[bridge] api_key` (a real secret, not the
placeholder), `[bridge] allowed_symbols`, `[trading_profile]
selected_profile`, and `[compliance] rule_profile_name` if you have a
real prop-firm rule profile configured. Then:

```
setup_phantom.bat
```

This verifies Python, creates `.venv`, installs `requirements.txt`
(a fast no-op — Phantom's live runtime has zero third-party
dependencies), verifies the `phantom\`/`mt5\` folders and your config
are present and valid, verifies `logs\`/`state\` are writable, compiles
everything, and runs an import smoke test. It stops immediately and
tells you exactly what's wrong if any step fails — nothing after a
failure runs.

## 5. Install the MT5 files

```
install_mt5_files.bat
```

This locates your MT5 data folder (or asks you for it if more than one
terminal is installed, or none is auto-detected), copies
`PhantomBridgeEA.mq5` into `MQL5\Experts\Phantom\` and
`PhantomBridgeEA.set` into `MQL5\Presets\Phantom\`, taking a timestamped
backup of anything it would otherwise overwrite. It does **not**
compile the EA — that requires MetaEditor.

## 6. Compile in MetaEditor

1. Open MetaEditor (from MT5: **Tools → MetaQuotes Language Editor**,
   or press **F4** inside MT5).
2. In the Navigator panel, expand **Experts → Phantom** and
   double-click `PhantomBridgeEA.mq5`.
3. Press **F7** (or the Compile toolbar button).
4. Confirm the output window at the bottom shows **"0 error(s)"**. A
   `PhantomBridgeEA.ex5` file appears next to the `.mq5` only once
   compilation succeeds.
5. Back in MT5, right-click the Navigator panel → **Refresh** so
   **Expert Advisors → Phantom → PhantomBridgeEA** appears.

## 7. Configure WebRequest / API access

MT5 blocks outbound HTTP from EAs by default. In MT5:
**Tools → Options → Expert Advisors** → check **"Allow WebRequest for
listed URL"** → add the exact URL from your `phantom.config.ini`'s
`[bridge] host`/`port` (default `http://127.0.0.1:8787`). This must
match `BackendUrl` in the EA's own inputs (see step 9).

## 8. Start Phantom

```
start_phantom.bat
```

This validates your configuration, starts Phantom in a new console
window (Bridge HTTP service, the 5 engines + Runtime Orchestrator
constructed, Reliability monitoring), waits a few seconds, then runs a
health check and prints **HEALTHY / DEGRADED / FAILED**. Expect
**DEGRADED** — see `KNOWN_GAPS.md` for exactly why, and that this is
by design, not a bug in this deployment layer.

## 9. Attach the EA to a demo chart

1. In MT5, open a chart for one of the symbols in your
   `allowed_symbols` list (start with a **demo account**, not live).
2. Drag **Expert Advisors → Phantom → PhantomBridgeEA** onto the chart.
3. In the settings dialog, confirm/edit `BackendUrl` to match your
   Bridge (default `http://127.0.0.1:8787`), and confirm `MagicNumber`
   matches `phantom.config.ini`'s `[bridge] magic_number` /
   `[runtime] magic_number` exactly (they must be identical to each
   other, and setup already checked this).

## 10. Load the .set file

In the same EA settings dialog, click **Load** at the bottom and
select `PhantomBridgeEA.set` from
`<your MT5 data folder>\MQL5\Presets\Phantom\` (the file
`install_mt5_files.bat` copied there), then click **OK**.

## 11. Verify heartbeat and Bridge connectivity

```
health_check.bat
```

Look for `[PASS] bridge reachable` and, once the EA is attached and
running, check the "Experts" tab in MT5's Terminal window (bottom
panel) for the EA's own log lines confirming successful `WebRequest`
calls to `/bridge/heartbeat`. If you see WebRequest errors, re-check
step 7's URL allow-list.

## 12. Stop and restart safely

```
stop_phantom.bat
```
Stops **only** the one Phantom process recorded in `state\phantom.pid`
— graceful shutdown first, forced termination only after a bounded
wait, never touching any other Python process on the machine. Logs and
state files are preserved.

```
restart_phantom.bat
```
Calls `stop_phantom.bat`, confirms the pid file is gone, calls
`start_phantom.bat`, and reports the post-restart health status.

## 13. Finding logs

Timestamped log files are written to the `log_dir` set in
`phantom.config.ini` (`[logging] log_dir`, default `C:\Phantom\logs`),
one file per start (`phantom_YYYYMMDD_HHMMSS.log`). The current health
snapshot is written continuously to `state\health.json` (the
`state_dir` you configured).

## 14. Rollback

Nothing this deployment layer does is destructive:
- `install_mt5_files.bat` never overwrites `PhantomBridgeEA.mq5`/`.set`
  without first copying the existing file to
  `<file>.bak_<timestamp>` right next to it — to roll back, delete the
  new file and rename the `.bak_...` file back to its original name.
- `stop_phantom.bat` never deletes logs or state.
- To remove Phantom entirely, stop it first (`stop_phantom.bat`), then
  delete `C:\Phantom` and the `MQL5\Experts\Phantom\` /
  `MQL5\Presets\Phantom\` folders inside your MT5 data folder.
