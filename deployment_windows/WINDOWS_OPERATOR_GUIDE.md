# Phantom Windows Operator Guide

Read `KNOWN_GAPS.md` first. This deployment layer brings up Phantom's
Bridge (execution channel) and Reliability monitoring honestly and
completely — it does **not** run a live trading decision loop, because
no market-data ingestion component exists in this codebase yet, and it
does **not** verify Trading Economics/Forex Factory news providers,
because no such component exists yet either. Every step below is
accurate to what actually happens; none of it overclaims readiness for
live trading. `install.py`'s own `INSTALLATION_REPORT.md` states this
plainly for your specific run.

## Quick start (first-time install)

A first-time user only needs to:

1. Extract the package so its contents sit directly under `C:\Phantom`.
2. Run `python install.py`.
3. Open MT5.
4. Attach `PhantomBridgeEA` to a demo chart.

Everything else — creating `phantom.config.ini`, generating the Bridge
API key, creating the virtual environment, installing dependencies,
creating `logs\`/`state\`, copying and personalizing the MT5 EA files,
verifying Bridge/Runtime/Reliability, creating desktop shortcuts, and
starting Phantom itself — happens automatically inside `install.py`.
Details below.

### 1. Extract the ZIP

Extract `phantom_windows_deployment.zip` anywhere convenient, then move
its contents so they sit directly under `C:\Phantom`:

```
C:\Phantom\phantom\               <- the 8 required engine packages
C:\Phantom\mt5\                   <- PhantomBridgeEA.mq5 + .set
C:\Phantom\deployment_windows\    <- everything in this guide
```

If you use a different drive/path, everything below still works — just
substitute your actual path for `C:\Phantom`.

### 2. Install Python if missing

Open Command Prompt and run `python --version`. If that fails or
reports below 3.9, install Python 3.9+ **64-bit** from
https://www.python.org/downloads/windows/, checking **"Add python.exe
to PATH"** during install.

### 3. Run install.py

```
cd C:\Phantom\deployment_windows
python install.py
```

This is the master installer. It runs, in order:

1. **Create configuration** — copies `config/phantom.config.template.ini`
   to `phantom.config.ini` if it doesn't already exist (default
   settings: `london_conservative` profile, 7 major pairs, an example
   compliance profile — edit `phantom.config.ini` later to customize;
   the defaults exist so install can finish with zero manual editing).
2. **Generate Bridge API key** — generates a random local shared secret
   (not a third-party credential — just the token Phantom and its one
   EA use to recognize each other) and stores it in a gitignored file
   next to the config.
3. **Run deploy.py** — verifies your Python version, creates `.venv`,
   installs `requirements.txt` (a fast no-op — the live runtime has zero
   third-party dependencies), verifies `phantom\`/`mt5\` are present,
   validates configuration, verifies `logs\`/`state\` are writable,
   compiles everything, and runs an import smoke test.
4. **Copy + personalize MT5 EA files** — auto-detects your MT5 data
   folder and copies `PhantomBridgeEA.mq5`/`.set` into it, with the
   `.set` file's `ApiKey`/`MagicNumber`/`BackendUrl`/`AllowedSymbolsCsv`
   already filled in from your generated config — no manual typing
   needed when you load it in MT5 later. If MT5 hasn't been opened yet
   (no data folder to find), or more than one MT5 installation exists,
   this step is skipped with instructions to run
   `python install_mt5_files.py` yourself afterward — installation
   still completes; this alone isn't a blocker.
5. **Verify Bridge** — actually constructs the real `BridgeEngine` and
   binds its HTTP server on your configured port, confirms it's
   reachable over a real socket connection, then shuts it down.
6. **Verify Runtime** — actually constructs all 5 core engines and the
   `RuntimeOrchestrator`.
7. **Verify Reliability** — actually constructs the `ReliabilityEngine`
   and calls its health-evaluation method once.
8. **Verify news providers** — reports honestly that Trading
   Economics/Forex Factory verification is **not available**, because
   no such component exists in this codebase (see `KNOWN_GAPS.md`
   section 2). This is not a failure; it's an accurate statement of
   what does and doesn't exist yet.
9. **Create desktop shortcuts** — Start, Stop, Restart, and Health
   Check, pointing at the right Python interpreter and script. Skipped
   (not a failure) on anything other than real Windows.
10. **Launch Phantom** — starts Phantom itself (same as running
    `python start.py`), so it's already running by the time you attach
    the EA. Expect **DEGRADED** status — see `KNOWN_GAPS.md`; this is
    by design, not a bug.

At the end, `install.py` writes `INSTALLATION_REPORT.md` summarizing
every step's real outcome, and prints next steps.

### 4. Open MT5 and compile the EA

1. Open MetaEditor (from MT5: **Tools → MetaQuotes Language Editor**,
   or press **F4**).
2. Navigator panel → **Experts → Phantom** → double-click
   `PhantomBridgeEA.mq5`.
3. Press **F7** to compile.
4. Confirm the output shows **"0 error(s)"**.

### 5. Attach the EA

1. In MT5, open a chart for one of your configured symbols — use a
   **demo account** first.
2. Drag **Expert Advisors → Phantom → PhantomBridgeEA** onto the chart.
3. In the settings dialog, click **Load** and select
   `PhantomBridgeEA.set` from `<your MT5 data folder>\MQL5\Presets\
   Phantom\` — this loads the personalized `ApiKey`/`MagicNumber`
   `install.py` already filled in. Click **OK**.
4. Enable **WebRequest** for your Bridge URL if you haven't already:
   MT5 → **Tools → Options → Expert Advisors** → check **"Allow
   WebRequest for listed URL"** → add `http://127.0.0.1:8787` (or your
   configured host/port).

### 6. Verify it's working

```
python health_check.py
```

Look for `[PASS] MT5 bridge connectivity (EA heartbeat)` once the EA is
attached and running — this checks the Bridge's real signal that the
EA has actually heartbeated, not just that the port is open.

## Day-to-day operation

Once installed, normal operation is just:

```
python start.py
python stop.py
```

or double-click the **Phantom - Start** / **Phantom - Stop** /
**Phantom - Restart** / **Phantom - Health Check** desktop shortcuts
`install.py` created. No manual copying, no manual configuration, no
multi-step setup — that's all one-time, handled by `install.py`.

- `python start.py` — launches Phantom as a detached background
  process, waits, health-checks it, and reports HEALTHY/DEGRADED/FAILED.
  Refuses to start a second instance if one is already running.
- `python stop.py` — stops **only** the one Phantom process recorded in
  `state\phantom.pid` — graceful shutdown first, forced termination
  only after a bounded wait, never touching any other process. Logs and
  state are preserved.
- `python restart.py` — calls `stop.py`, confirms shutdown, calls
  `start.py`, reports post-restart health.
- `python health_check.py` — reports current status without starting or
  stopping anything.

Logs: timestamped files in `logs\` (`log_dir` in `phantom.config.ini`,
default relative to the config file's own folder). Current health
snapshot: `state\health.json`.

## Rollback

Nothing here is destructive:
- `install_mt5_files.py` (called by `install.py`) never overwrites
  `PhantomBridgeEA.mq5`/`.set` without first backing up the existing
  file to `<file>.bak_<timestamp>`.
- `stop.py` never deletes logs or state.
- To remove Phantom entirely: `python stop.py`, then delete `C:\Phantom`
  and the `MQL5\Experts\Phantom\`/`MQL5\Presets\Phantom\` folders inside
  your MT5 data folder, and delete the 4 desktop shortcuts.

## Advanced: manual step-by-step (if you don't want install.py to do everything)

If you'd rather control every step yourself — a custom trading profile,
hand-picked symbols before the first run, or just wanting to see each
piece work individually — you can run the same steps `install.py`
automates, one at a time:

```
cd C:\Phantom\deployment_windows
copy config\phantom.config.template.ini phantom.config.ini
notepad phantom.config.ini
```
Edit `[bridge] allowed_symbols`, `[trading_profile] selected_profile`,
`[compliance] rule_profile_name` as needed. Set a real API key either
via `setx PHANTOM_BRIDGE_API_KEY "your-secret"` (open a new Command
Prompt afterward) or by letting `install.py`'s key-generation step run
on its own (`python -c "import install; install.step_generate_bridge_api_key()"`).
Then:

```
python deploy.py
python install_mt5_files.py
```
(compile the EA in MetaEditor, as in step 4 above), then:
```
python start.py
```
and attach the EA as in step 5 above.
