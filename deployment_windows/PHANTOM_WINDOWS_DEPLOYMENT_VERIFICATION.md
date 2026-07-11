# Phantom Windows Deployment — Verification Report

Honest account of what was actually run in this (Linux) environment,
what passed, and what can only be verified on a real Windows/MT5
installation. Nothing below is claimed without having actually been
executed.

## Files created (all new; nothing in `phantom/`, `mt5/`, or the
existing test suite was modified)

```
deployment_windows/
├── .gitignore
├── KNOWN_GAPS.md
├── WINDOWS_OPERATOR_GUIDE.md
├── PHANTOM_WINDOWS_DEPLOYMENT_VERIFICATION.md   (this file)
├── requirements.txt
├── config_loader.py
├── run_phantom.py
├── health_check.py
├── setup_phantom.bat
├── start_phantom.bat
├── stop_phantom.bat
├── restart_phantom.bat
├── health_check.bat
├── install_mt5_files.bat
└── config/
    └── phantom.config.template.ini
```

## Commands executed and checks passed (in this Linux sandbox)

- `python3 -m py_compile deployment_windows/config_loader.py
  deployment_windows/run_phantom.py deployment_windows/health_check.py`
  — clean compile, no syntax errors.
- **`config_loader.load_settings()` against a real, filled-in test
  config** — successfully parsed every `[bridge]`/`[runtime]`/
  `[trading_profile]`/`[risk]`/`[compliance]`/`[news]`/`[reliability]`/
  `[logging]` section and constructed the real `BridgeConfig`/
  `RuntimeConfig`/`RiskEngineConfig`/`ReliabilityConfig` dataclasses
  with the parsed values. Confirmed it correctly rejects a config that
  still has the `REPLACE_WITH_YOUR_BRIDGE_API_KEY` placeholder (exit
  code 2, clear message).
- **`run_phantom.py` executed end to end**: started the real
  `phantom.bridge.server.serve()` HTTP server on a test port, confirmed
  it was reachable via a real TCP socket connection, constructed all 5
  core engines and the `RuntimeOrchestrator`, started the Reliability
  heartbeat loop, wrote a correct `health.json` (with
  `cycle_loop_active: false` and the honest reason string), printed the
  DEGRADED status banner, and shut down cleanly on `SIGTERM` (Bridge
  server closed, pid file removed, exit code 0).
- **Duplicate-instance guard verified**: started one instance, then
  attempted a second against the same config — the second refused to
  start (exit code 2, clear message naming the existing pid), while the
  first kept running undisturbed.
- **`health_check.py` executed end to end**: while `run_phantom.py` was
  running, reported all 10 checks passing except the (intentionally,
  honestly) failing "live trading cycle active" check, overall exit
  code 1 (DEGRADED). After stopping the process, re-ran it and it
  correctly reported "bridge reachable: FAIL" and "runtime process
  alive: FAIL", overall exit code 2 (FAILED).
- **Full repository test suite**: `pytest tests/` — **2,557 passed,
  1 failed** (see "Known test interaction" below). This is the same
  2,558-test suite from the Phase 3B report; the only change is the
  one pre-existing test's own allowlist reacting to a new, legitimate
  top-level directory (see below) -- no test that exercises actual
  engine behavior was affected, and no engine file was touched.
- `git status --porcelain` confirmed the only change in this
  repository is the new, untracked `deployment_windows/` directory --
  zero lines changed in any tracked file, in `phantom/`, `mt5/`, or
  `tests/`.

## Known test interaction (reported, not silently fixed)

`tests/phantom/bridge/test_structural_boundary.py::
TestGitDiffTouchesNoUnrelatedPackage::
test_git_status_shows_only_expected_paths_changed` fails now, because
it hardcodes an allowlist of top-level paths
(`phantom/`, `mt5/`, `tests/phantom/`, `docs/research/`, `docs/adr/`,
root-level `PHANTOM_*.md` files) dating from Bridge Phase 1, and
`deployment_windows/` is not on it.

This is a **test-infrastructure allowlist gap, not an engine-logic
problem** — nothing in `deployment_windows/` imports, calls, or
modifies any `phantom/` code; the test itself says nothing about
Bridge's actual behavior. Per this mission's explicit "do not modify
any code" instruction, **this test file was not touched.** Extending
its allowlist with `"deployment_windows/"` (a one-line change) is the
obvious fix if you want this test green going forward, but that
decision -- and the one-line edit -- is left to you rather than made
silently.

## What was verified vs. what requires a real Windows/MT5 environment

**Verified in this environment (Linux sandbox, proxying for
Windows-Python behavior):**
- All Python logic: config parsing/validation, Bridge startup, engine
  construction, Reliability heartbeat loop, health snapshot writing,
  graceful shutdown, duplicate-instance refusal, health check reporting.

**Cannot be verified without a real Windows + MT5 installation, and
were NOT claimed as verified:**
- Whether `setup_phantom.bat`/`start_phantom.bat`/`stop_phantom.bat`/
  `restart_phantom.bat`/`health_check.bat`/`install_mt5_files.bat`
  actually execute correctly under `cmd.exe` — there is no Windows
  shell in this sandbox to run them in. Every `.bat` file was written
  and manually reviewed for correct batch syntax (label targets,
  `errorlevel` checks, quoting of paths with spaces), but line-by-line
  execution was not possible here.
- Whether `taskkill /PID` (without `/F`) actually delivers a signal
  Python's own handlers catch gracefully on Windows, vs. immediately
  falling through to the bounded forced-termination path — this is a
  real, disclosed uncertainty (see `stop_phantom.bat`'s own comments);
  either way the script behaves safely (it always converges to either
  "confirmed stopped" or a forced kill scoped to exactly one pid).
- MT5 terminal auto-detection under `%APPDATA%\MetaQuotes\Terminal\`,
  and the actual MetaEditor compile step (F7 → "0 error(s)" →
  `.ex5` produced) -- this repository has no MT5 installation to test
  against. `install_mt5_files.bat` copies files and prints the exact
  compile steps; it does not and cannot claim to have compiled
  anything itself.
- `WebRequest` connectivity from a real MT5 terminal to the Bridge --
  the EA's endpoint set was verified by direct comparison against
  `phantom/bridge/server.py`'s real handlers (see
  `PHANTOM_MT5_DEPLOYMENT_AUDIT.md`), but no live MT5 process placed an
  actual `WebRequest` call in this environment.

## Remaining real-environment gates before first live use

1. Run this deployment on an actual Windows VPS and confirm each
   `.bat` script's behavior matches this report's description.
2. Compile the EA in a real MetaEditor and confirm "0 error(s)."
3. Attach the compiled EA to a demo chart and confirm a real
   `WebRequest` heartbeat reaches the Bridge (`health_check.bat`
   should show `[PASS] bridge reachable` while MT5's Experts tab shows
   successful heartbeat POSTs).
4. Before any live trading is possible at all: design and implement a
   Market Data Ingestion component (new Accepted ADR required per
   CLAUDE.md §1.10) and wire it into `RuntimeOrchestrator.run_cycle()`
   — see `KNOWN_GAPS.md` §1. Nothing in this deployment layer trades
   until that exists.
