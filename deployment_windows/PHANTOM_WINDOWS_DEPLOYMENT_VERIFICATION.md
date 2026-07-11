# Phantom Windows Deployment — Verification Report

Honest account of what was actually run in this (Linux) environment,
what passed, and what can only be verified on a real Windows/MT5
installation. Nothing below is claimed without having actually been
executed.

This report covers the **Python Deployment Manager** (`deploy.py`,
`start.py`, `stop.py`, `restart.py`, `health_check.py`,
`install_mt5_files.py`) that replaced the earlier batch-file layer.
Nothing in `phantom/`, `mt5/`, or the existing test suite was modified.

## Files in this package

```
deployment_windows/
├── .gitignore
├── KNOWN_GAPS.md
├── WINDOWS_OPERATOR_GUIDE.md
├── PHANTOM_WINDOWS_DEPLOYMENT_VERIFICATION.md   (this file)
├── requirements.txt
├── config_loader.py
├── deploy.py
├── start.py
├── stop.py
├── restart.py
├── health_check.py
├── install_mt5_files.py
└── config/
    └── phantom.config.template.ini
```

No batch files remain — every step (setup, start, stop, restart,
health check, MT5 file install) is a Python script, invoked directly
(`python deploy.py`, `python start.py`, ...).

## Commands executed and checks passed (in this Linux sandbox)

- `python3 -m compileall -q deployment_windows/ phantom/` — clean
  compile, no syntax errors, across every file in this package.
- **`deploy.py` executed end to end** against a real test config (a
  non-default port, a `PHANTOM_BRIDGE_API_KEY` environment variable
  set to a test value): created `.venv`, upgraded pip, installed
  `requirements.txt` (a real no-op — Phantom's live runtime is
  stdlib-only), verified `phantom/`/`mt5/` folder structure, validated
  configuration, verified `logs/`/`state/` write permissions, ran
  `compileall`, and ran the import smoke test against all 8 required
  packages — all 9 steps passed, exit code 0.
- **`start.py` executed end to end in both modes**:
  - Launcher mode (`python start.py`, no args): spawned
    `start.py --foreground` as a detached background process, waited,
    ran a health check, and printed DEGRADED (expected — see
    `KNOWN_GAPS.md`).
  - Foreground mode (`start.py --foreground`, run internally): started
    the real `phantom.bridge.server.serve()` HTTP server, confirmed it
    was reachable via a real TCP socket connection, constructed all 5
    core engines and the `RuntimeOrchestrator`, started the
    Reliability heartbeat loop, wrote a correct `health.json`
    (including `mt5_connected` from `BridgeEngine.
    is_connection_healthy`, and `cycle_loop_active: false` with the
    honest reason string), printed the DEGRADED status banner, and
    shut down cleanly on `SIGTERM` (Bridge server closed, pid file
    removed, exit code 0).
- **Duplicate-instance guard verified**: started one instance, then
  ran `start.py` again against the same config — it detected the
  existing pid, printed a message naming it, and ran a health check
  instead of starting a second process; the first instance kept
  running undisturbed.
- **`health_check.py` executed end to end**, standalone and via
  `start.py`'s internal call: while Phantom was running, reported all
  checks passing except the two intentionally-failing informational
  checks ("MT5 bridge connectivity" — no real EA attached in this
  sandbox — and "live trading cycle active"), overall exit code 1
  (DEGRADED). After stopping the process, re-ran it and it correctly
  reported "bridge reachable: FAIL" and "runtime process alive: FAIL",
  overall exit code 2 (FAILED).
- **`stop.py` executed end to end**: graceful `SIGTERM`-based stop
  confirmed within the bounded wait window; running it again against
  an already-stopped instance correctly reported "no pid file found"
  and exited 0 (not an error). Verified its process-identity guard
  directly: wrote a pid file containing a nonexistent pid, and
  separately one containing pid 1 (a real, running, but non-Python
  process) — both times `stop.py` correctly refused to touch the
  process, reported it as a stale pid file, and removed only the pid
  file.
- **`restart.py` executed end to end**: called `stop.py` (confirmed
  graceful shutdown), verified the pid file was gone, called
  `start.py` (new pid, health check reported DEGRADED as expected).
- **`install_mt5_files.py` executed end to end** against a fake MT5
  data folder (a plain directory with an `MQL5/` subfolder, standing
  in for a real MT5 installation): copied `PhantomBridgeEA.mq5` and
  `PhantomBridgeEA.set` into the correct `MQL5/Experts/Phantom/` and
  `MQL5/Presets/Phantom/` paths, and printed the exact MetaEditor
  compile steps without claiming to have run them.
- **Full repository test suite**: `python3 -m unittest discover -s
  tests/phantom` — **972 passed, 1 failed** (see "Known test
  interaction" below); no test that exercises actual engine behavior
  was affected, and no engine file was touched.

## Two real defects found and fixed during this verification

Both were caught by actually running the scripts, not by inspection —
consistent with this repository's "never claim verification that
wasn't run" discipline:

1. **`deploy.py`'s configuration/write-permission checks never added
   the repository root to the venv subprocess's `sys.path`.** Running
   `deploy.py` for real failed at "Validate configuration" with
   `ModuleNotFoundError: No module named 'phantom'`, because
   `config_loader.py` imports from `phantom.bridge.config` etc. but
   the check script only put `.` (deployment_windows/ itself) on
   `sys.path`. Fixed by also inserting the repo root, matching what
   `step_import_smoke_test()` already did correctly.
2. **`start.py`'s venv-activation guard never actually fired.** It
   compared `Path(sys.executable).resolve()` against the venv
   interpreter's resolved path — but `python -m venv` on POSIX creates
   the venv's `python` as a *symlink* to the base interpreter, so
   resolving both paths collapses them to the same target regardless
   of which one launched the process. Running `start.py` directly
   with the system interpreter (not `.venv`'s) while `.venv` existed
   should have been refused, but wasn't. Fixed by comparing
   `sys.prefix` instead (which correctly reflects the venv root on
   both POSIX symlink-based and Windows copy-based venvs), then
   re-verified: the system interpreter is now correctly refused
   (exit code 2, clear message), and the venv interpreter is correctly
   accepted.

## Known test interaction (reported, not silently fixed)

`tests/phantom/bridge/test_structural_boundary.py::
TestGitDiffTouchesNoUnrelatedPackage::
test_git_status_shows_only_expected_paths_changed` fails while this
change is uncommitted, because it hardcodes an allowlist of top-level
paths (`phantom/`, `mt5/`, `tests/phantom/`, `docs/research/`,
`docs/adr/`, root-level `PHANTOM_*.md` files) dating from Bridge
Phase 1, and `deployment_windows/` is not on it. This is a
**git-status-based test-infrastructure check, not an engine-logic
problem** — it inspects `git status --porcelain`, not any behavior of
`phantom/bridge`, and resolves itself as soon as the deployment-layer
changes are committed (a clean `git status` always passes it).

## What was verified vs. what requires a real Windows/MT5 environment

**Verified in this environment (Linux sandbox, proxying for
Windows-Python behavior):** all Python logic — config parsing/
validation, `.venv` creation and the fail-closed 9-step setup sequence,
Bridge startup, engine construction, Reliability heartbeat loop, health
snapshot writing (including the real `mt5_connected` signal), graceful
shutdown, forced-shutdown fallback, process-identity verification
before touching any pid, duplicate-instance refusal, restart
sequencing, and health check reporting in both HEALTHY/DEGRADED/FAILED
directions.

**Cannot be verified without a real Windows + MT5 installation, and
were NOT claimed as verified:**
- Whether `taskkill /PID` (without `/F`) actually delivers a signal
  Python's own handlers catch gracefully on Windows, vs. immediately
  falling through to the bounded forced-termination path in `stop.py`
  — this is a real, disclosed uncertainty; either way the script
  behaves safely (it always converges to either "confirmed stopped" or
  a forced kill scoped to exactly one verified pid).
- MT5 terminal auto-detection under `%APPDATA%\MetaQuotes\Terminal\`
  on a real Windows machine (verified here only against a synthetic
  fake data folder), and the actual MetaEditor compile step (F7 →
  "0 error(s)" → `.ex5` produced) — this repository has no MT5
  installation to test against. `install_mt5_files.py` copies files
  and prints the exact compile steps; it does not and cannot claim to
  have compiled anything itself.
- `WebRequest` connectivity from a real MT5 terminal to the Bridge —
  the EA's endpoint set was verified by direct comparison against
  `phantom/bridge/server.py`'s real handlers (see
  `PHANTOM_MT5_DEPLOYMENT_AUDIT.md`), but no live MT5 process placed an
  actual `WebRequest` call in this environment.
- `subprocess.CREATE_NEW_CONSOLE` (Windows-only flag used by
  `start.py`'s launcher mode to open a visible console window) — this
  sandbox is POSIX, so the launcher's detached-process path was
  exercised using the POSIX branch (`start_new_session=True`,
  `stdout`/`stderr` to `DEVNULL`) instead; the Windows branch was
  reviewed for correct syntax but not executed.

## Remaining real-environment gates before first live use

1. Run this deployment on an actual Windows VPS and confirm
   `deploy.py`/`start.py`/`stop.py`/`restart.py`/`health_check.py`/
   `install_mt5_files.py` behave the same way this report describes,
   including the Windows-only `CREATE_NEW_CONSOLE`/`taskkill` paths
   that could not be exercised here.
2. Compile the EA in a real MetaEditor and confirm "0 error(s)."
3. Attach the compiled EA to a demo chart and confirm a real
   `WebRequest` heartbeat reaches the Bridge (`python health_check.py`
   should show `[PASS] MT5 bridge connectivity (EA heartbeat)` while
   MT5's Experts tab shows successful heartbeat POSTs).
4. Before any live trading is possible at all: design and implement a
   live trading-cycle loop that drives `phantom/market_data_ingestion/`
   (ADR-033 Part 1, implemented but not wired into any entry point) and
   calls `RuntimeOrchestrator.run_cycle()` — see `KNOWN_GAPS.md` §1.
   Nothing in this deployment layer trades until that exists.
