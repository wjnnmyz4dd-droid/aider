# Titan Protocol Windows Operator Guide

Read `KNOWN_GAPS.md` first. This deployment layer brings up Titan Protocol's
Bridge (execution channel), a real live-cycle loop driving
`RuntimeOrchestrator.run_cycle()` from EA-reported bars (via
`titan_protocol/market_data_ingestion/`) and dual-provider news failover
(via `titan_protocol/news_ingestion/`, Trading Economics primary / Forex
Factory backup), and Reliability monitoring — honestly and completely.
Status still reports **DEGRADED**, never HEALTHY, because persisted
day-start/peak-balance tracking and a configured backup news feed are
still open gaps (see `KNOWN_GAPS.md`), not because those components
don't exist. Every step below is accurate to what actually happens;
none of it overclaims readiness for live trading. `install.py`'s own
`INSTALLATION_REPORT.md` states this plainly for your specific run (see
`INSTALLATION_REPORT_TEMPLATE.md` for the shape of that report before
you've run anything).

## Quick start (first-time install)

A first-time user only needs to:

1. Extract the package so its contents sit directly under `C:\TitanProtocol`.
2. Run `python install.py`.
3. Open MT5.
4. Attach `TitanProtocolEA` to a demo chart.

Everything else — creating `titan_protocol_config.json`, generating the Bridge
API key, creating the virtual environment, installing dependencies,
creating `logs\`/`state\`/`data\`, copying and personalizing the MT5 EA
files, verifying Bridge/Runtime/Reliability, creating desktop
shortcuts, and starting Titan Protocol itself — happens automatically inside
`install.py`. Details below.

### 1. Extract the ZIP

Extract `titan_protocol_windows_complete_release.zip` directly into `C:\TitanProtocol`.
After extraction you should have:

```
C:\TitanProtocol\install.py
C:\TitanProtocol\start.py
C:\TitanProtocol\stop.py
C:\TitanProtocol\restart.py
C:\TitanProtocol\health_check.py
C:\TitanProtocol\install_mt5_files.py
C:\TitanProtocol\config_loader.py
C:\TitanProtocol\requirements.txt
C:\TitanProtocol\config\titan_protocol_config.example.json
C:\TitanProtocol\titan_protocol\                 <- the 8 required engine packages
C:\TitanProtocol\mt5\                     <- TitanProtocolEA.mq5 + .set
C:\TitanProtocol\logs\  C:\TitanProtocol\state\  C:\TitanProtocol\data\
C:\TitanProtocol\WINDOWS_OPERATOR_GUIDE.md
C:\TitanProtocol\KNOWN_GAPS.md
C:\TitanProtocol\RELEASE_MANIFEST.json
```

If you use a different drive/path, everything below still works — just
substitute your actual path for `C:\TitanProtocol`.

### 2. Install Python if missing

Open Command Prompt and run `python --version`. If that fails or
reports below 3.9, install Python 3.9+ **64-bit** from
https://www.python.org/downloads/windows/, checking **"Add python.exe
to PATH"** during install.

### 3. Run install.py

```
cd C:\TitanProtocol
python install.py
```

This is the master installer. It runs, in order:

1. **Verify running from the full release package** — confirms
   `titan_protocol\` and `mt5\` sit next to `install.py`.
2. **Create configuration** — copies `config\titan_protocol_config.example.json`
   to `titan_protocol_config.json` if it doesn't already exist (default
   settings: `london_conservative` profile, 7 major pairs, an example
   compliance profile — edit `titan_protocol_config.json` later to customize;
   the defaults exist so install can finish with zero manual editing).
3. **Generate Bridge API key** — generates a random local shared secret
   (not a third-party credential — just the token Titan Protocol and its one
   EA use to recognize each other) and stores it in a gitignored file
   next to the config.
4. **Run deploy.py** — verifies your Python version, creates `.venv`,
   installs `requirements.txt` (a fast no-op — the live runtime has zero
   third-party dependencies), verifies `titan_protocol\`/`mt5\`/`config\` are
   present, validates configuration, creates and verifies
   `logs\`/`state\`/`data\` are writable, compiles everything, and runs
   an import smoke test against all 8 live packages.
5. **Copy + personalize MT5 EA files** — resolves the data folder of
   whichever MT5 terminal is **currently running** (via `mt5_terminal.py`
   cross-referencing each data folder's `origin.txt` against the running
   `terminal64.exe` process — not merely "a folder that looks like MT5
   data"), and copies `TitanProtocolEA.mq5`/`.set` into it, with the
   `.set` file's `ApiKey`/`MagicNumber`/`BackendUrl`/`AllowedSymbolsCsv`
   already filled in from your generated config. If MT5 isn't running yet
   (no terminal process to resolve), this step is skipped with
   instructions to run `python install_mt5_files.py` yourself afterward
   — installation still completes; this alone isn't a blocker. If MT5
   **is** running, this step then requires you to confirm the Bridge
   address is allow-listed in that exact terminal (see the whitelist
   note below) before it completes — pass `--whitelist-confirmed` once
   you have, or `--skip-whitelist-check` to bypass this gate entirely.
6. **Verify Bridge** — actually constructs the real `BridgeEngine` and
   binds it on HTTP (the only supported transport; ADR-034 Amendment 10),
   confirms it's reachable over a real connection, then shuts it down.
7. **Verify Runtime** — actually constructs all 5 core engines and the
   `RuntimeOrchestrator`.
8. **Verify Reliability** — actually constructs the `ReliabilityEngine`
   and calls its health-evaluation method once.
9. **Verify news providers** — actually constructs a real
   `NewsIngestionEngine` (Trading Economics primary, Forex Factory
   automatic backup; ADR-033 Part 2). Reports informationally if
   `forex_factory_base_url` is still empty in your config, since a
   Trading Economics outage then fails closed immediately with no
   functioning backup (see `KNOWN_GAPS.md` section 2) — not a failure,
   an accurate statement of your current configuration.
10. **Create desktop shortcuts** — Start, Stop, Restart, and Health
    Check, pointing at the right Python interpreter and script. Skipped
    (not a failure) on anything other than real Windows.
11. **Launch Titan Protocol** — starts Titan Protocol itself (same as running
    `python start.py`), so it's already running by the time you attach
    the EA. Expect **DEGRADED** status — see `KNOWN_GAPS.md`; this is
    by design, not a bug.

At the end, `install.py` writes `INSTALLATION_REPORT.md` summarizing
every step's real outcome, and prints next steps.

### 4. Open MT5 and compile the EA

1. Open MetaEditor (from MT5: **Tools → MetaQuotes Language Editor**,
   or press **F4**).
2. Navigator panel → **Experts → Titan Protocol** → double-click
   `TitanProtocolEA.mq5`.
3. Press **F7** to compile.
4. Confirm the output shows **"0 error(s)"**.

### 5. Attach the EA

1. In MT5, open a chart for one of your configured symbols — use a
   **demo account** first.
2. Drag **Expert Advisors → Titan Protocol → TitanProtocolEA** onto the chart.
3. In the settings dialog, click **Load** and select
   `TitanProtocolEA.set` from `<your MT5 data folder>\MQL5\Presets\
   TitanProtocol\` — this loads the personalized `ApiKey`/`MagicNumber`
   `install.py` already filled in. Click **OK**.
4. Allow-list the Bridge address if you haven't already: MT5 →
   **Tools → Options → Expert Advisors** → check **"Allow WebRequest for
   listed URL"** and add `http://127.0.0.1:8787` (or your configured
   host/port). HTTP is the only transport Titan Protocol supports
   (ADR-034 Amendment 10).

   **If `GetLastError=4014` persists even after adding the address**:
   the single most common cause is that the change does not take effect
   for an already-attached EA, and in many MT5 builds not even for a
   re-attached one — **fully close and reopen MT5** (not just re-attach
   the EA), then reattach. Also confirm you edited the allow-list in the
   *same* terminal instance `install_mt5_files.py` installed into — its
   own output (and the EA's own `OnInit()` log line,
   `TERMINAL_DATA_PATH=...`) states the exact data folder. MT5 stores
   this allow-list in an undocumented, binary `Config\experts.ini` with
   no supported way for any script to read or write it directly — this
   is a genuine platform limitation, not something `install.py` failed
   to automate. Run `python verify_mt5_instance.py` afterward for a
   real, evidence-based check of everything that CAN be verified
   (correct running instance, correct data folder, correct Experts
   folder, Bridge reachability, and — the actual proof the allow-list is
   working — a real recorded EA heartbeat).

### 6. Verify it's working

```
python health_check.py
```

Reports, among other things:
- `active transport` and `bridge reachable (http)` — confirms the
  Bridge's HTTP listener is actually up and reachable.
- `MT5 bridge connectivity (EA heartbeat)` — checks the Bridge's real
  signal that the EA has actually heartbeated, not just that the port
  is open.
- `queue health` — the real Bridge command-queue depth against your
  configured degraded/critical thresholds.
- `API key environment variable present` and `news-feed trust state` —
  real configuration state, reported for visibility (informational,
  never blocking).
- `market-data readiness` and `news provider failover` — real status
  from the live-cycle loop's market-data and news-provider engines;
  both need a running, connected EA reporting real bars before they
  read HEALTHY (see `KNOWN_GAPS.md`).

Also check the "Experts" tab in MT5's Terminal window (bottom panel)
for the EA's own log lines confirming successful Bridge calls. If you
see repeated `WebRequest` errors, re-check step 5's allow-list.

## Day-to-day operation

Once installed, normal operation is just:

```
python start.py
python stop.py
```

or double-click the **Titan Protocol - Start** / **Titan Protocol - Stop** /
**Titan Protocol - Restart** / **Titan Protocol - Health Check** desktop shortcuts
`install.py` created. No manual copying, no manual configuration, no
multi-step setup — that's all one-time, handled by `install.py`.

- `python start.py` — launches Titan Protocol as a detached background
  process, waits, health-checks it, and reports HEALTHY/DEGRADED/FAILED.
  Refuses to start a second instance if one is already running.
- `python stop.py` — stops **only** the one Titan Protocol process recorded in
  `state\titan_protocol.pid` — graceful shutdown first, forced termination
  only after a bounded wait, never touching any other process (it
  verifies the recorded pid is actually a Python process before
  touching it, so a stale/reused pid is never killed). Logs and state
  are preserved.
- `python restart.py` — calls `stop.py`, confirms shutdown, calls
  `start.py`, reports post-restart health.
- `python health_check.py` — reports current status without starting or
  stopping anything.

Logs: timestamped files in `logs\` (`log_dir` in `titan_protocol_config.json`,
default relative to the config file's own folder). Current health
snapshot: `state\health.json`. `data\` is reserved for a future
market-data component and is not used by anything today (see
`data\README.md`).

## Rollback

Nothing here is destructive:
- `install_mt5_files.py` (called by `install.py`) never overwrites
  `TitanProtocolEA.mq5`/`.set` without first backing up the existing
  file to `<file>.bak_<timestamp>`.
- `stop.py` never deletes logs or state.
- To remove Titan Protocol entirely: `python stop.py`, then delete `C:\TitanProtocol`
  and the `MQL5\Experts\TitanProtocol\`/`MQL5\Presets\TitanProtocol\` folders inside
  your MT5 data folder, and delete the 4 desktop shortcuts.

## Advanced: manual step-by-step (if you don't want install.py to do everything)

If you'd rather control every step yourself — a custom trading profile,
hand-picked symbols before the first run, or just wanting to see each
piece work individually — you can run the same steps `install.py`
automates, one at a time:

```
cd C:\TitanProtocol
copy config\titan_protocol_config.example.json titan_protocol_config.json
notepad titan_protocol_config.json
```
Edit `bridge.allowed_symbols`, `trading_profile.selected_profile`,
`compliance.rule_profile_name` as needed (it's a plain JSON file — every
key is documented inline via `_note`/`_maps_to` comment fields). Set a
real API key either via `setx TITAN_PROTOCOL_BRIDGE_API_KEY "your-secret"`
(open a new Command Prompt afterward) or by letting `install.py`'s
key-generation step run on its own
(`python -c "import install; install.step_generate_bridge_api_key()"`).
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

## Release manifest

`RELEASE_MANIFEST.json` (same folder) records exactly what shipped in
this package: the source commit, build timestamp, every included file
with its SHA-256 hash, the Python version requirement, and a summary of
the known gaps below — useful for confirming a VPS copy matches what
you extracted, or for auditing what changed between releases.
