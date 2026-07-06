# Start Phantom

How to start the deployed package via `scripts/start_phantom.py` — the
current runtime's entry point ("EA" driver). See `LIVE_DEPLOYMENT_GUIDE.md`
for the fuller operator background this file assumes.

## 1. One-time setup

1. Copy the profile template you need
   (`config\DEV.env.template`/`PAPER.env.template`/`LIVE.env.template`)
   to `config\<PROFILE>.env` and fill in real values — never commit or
   copy a filled-in `.env` back into version control.
2. `pip install -r requirements.txt`.

## 2. Start — DEV (construction-only smoke test)

```
scripts\start_phantom.bat DEV
```

Constructs every engine, attempts service startup, prints each service's
health, and exits — no continuous loop, nothing submitted anywhere.
Use this to confirm the package itself is wired correctly before
touching a real MT5 terminal.

## 3. Start — PAPER

```
scripts\start_phantom.bat PAPER
```

Runs continuously: connects (refusing to proceed unless
`confirm_demo_account` confirms a genuine MT5 **demo** account — checked
before every single cycle, not just once at startup), then calls
`PipelineOrchestrator.run_scan_cycle` once per
`PHANTOM_CYCLE_INTERVAL_SECONDS` (default 60) per configured symbol,
skipping non-trading-day windows via `SessionManager`. Stop with Ctrl+C
for a graceful `stop_all()` shutdown.

If a cycle raises, a structured crash dump is written to
`PHANTOM_CRASH_DUMP_DIR` and the loop continues to the next cycle — it
does not exit on a single bad cycle. Check the crash dump directory
regularly.

## 4. Start — LIVE

```
scripts\start_phantom.bat LIVE
```

Validates configuration (aborts on any missing secret, invalid MT5
login, wrong broker profile, or paper trading left enabled), starts the
`mt5_terminal`/`phantom_core` services, then runs all 10
`DeploymentValidator` go-live checks with real probes wired to the
constructed engines (including `emergency_stop_functional`, which
exercises `PositionManager`'s real `EMERGENCY_CLOSE` path against a
synthetic, isolated probe position — never a real one).

**Read this before running LIVE:** this command validates and starts
services — it does **not** run a continuous live-order-submission loop.
No such scheduler exists anywhere in `phantom_pipeline` yet; only a
single-shot `run_scan_cycle` call and `PaperTradingRunner`'s
demo-account-guarded paper loop exist today. If every check passes, the
script prints confirmation and exits — an operator (or a scheduler you
build and review separately, outside this packaging task's scope) is
still required to actually drive `run_scan_cycle` against the live
account. Do not interpret "all checks passed" as "orders are now being
placed automatically" — they are not.

## 5. Environment variables reference

| Variable | Meaning |
|---|---|
| `PHANTOM_PROFILE` | `DEV`/`PAPER`/`LIVE` |
| `MT5_LOGIN`/`MT5_PASSWORD`/`MT5_SERVER`/`MT5_TERMINAL_PATH` | MT5 credentials — required for PAPER/LIVE |
| `PHANTOM_SYMBOLS` | comma-separated symbol list |
| `PHANTOM_SPREAD_THRESHOLD`/`PHANTOM_SLIPPAGE_THRESHOLD`/`PHANTOM_MAX_SPREAD`/`PHANTOM_CORRELATION_BUCKET` | uniform per-symbol thresholds passed to Compliance/Execution Validator/Risk Engine config |
| `PAPER_TRADING_ENABLED` | must be `false` for LIVE |
| `BROKER_PROFILE`/`ALLOWED_BROKER_PROFILES` | broker identity check |
| `PROMETHEUS_BASE_URL` | optional; omit to use the in-memory fake read port |
| `PHANTOM_LOG_DIR`/`PHANTOM_LOG_ARCHIVE_DIR`/`PHANTOM_CRASH_DUMP_DIR`/`PHANTOM_BACKUP_DIR` | filesystem paths |
| `PHANTOM_MT5_SERVICE_UNIT`/`PHANTOM_CORE_SERVICE_UNIT` | Windows Service names, if registered (see `VPS_SETUP_GUIDE.md` §3) |
| `PHANTOM_CYCLE_INTERVAL_SECONDS` | PAPER profile's loop interval, default 60 |
| `PHANTOM_DAILY_RESET_HOUR_UTC` | PAPER profile's `SessionManager` trading-day boundary |

## 6. Stopping

- Foreground console (PAPER): Ctrl+C — triggers `ProductionDeploymentManager.stop_all()`.
- Registered Windows Service: `scripts\stop_phantom.bat <ServiceName>`.
