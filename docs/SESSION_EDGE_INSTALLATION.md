# Session Edge — Installation & DEMO Deployment Runbook

The **one authoritative** human install/run document for Session Edge on a Windows +
MetaTrader 5 **DEMO** machine. Every step below is derived from source at HEAD
`fba006c`/`79b11fe`+ and cross-checked against the code — it invents nothing.

- Live DEMO **validation matrix** (18-item execution matrix, broker/symbol matrix,
  restart/recovery, disposition): see
  `docs/SESSION_EDGE_PHASE_5_MT5_COMPILATION_AND_DEMO_VALIDATION.md` — this runbook
  references it rather than duplicating it.
- Phantom is a **separate quarantined system** — see
  `docs/SESSION_EDGE_PHANTOM_SEPARATION.md`. It is NOT part of any Session Edge step.

> This phase is **DEMO deployment and validation only**. Nothing here authorizes
> live-money trading.

---

## NORMAL STARTUP (zero-friction)

Once the machine is set up (§A–§G, done once):

1. Start **MT5** and log into your **DEMO** account.
2. Confirm the Session Edge **EA is attached** to a chart and **Algo Trading** is on.
3. **Double-click `run_session_edge.bat`** — no arguments, no command line.
4. Watch the startup screen run its real checks (MT5 / DEMO / account identity /
   **capital base** / timezone / bridge), then start newsfeed + producer + manager.
5. If you see **`SESSION EDGE STARTED` / `STATUS: WAITING FOR VALID MARKET
   CONDITIONS`**, leave it running.
6. If you see **`SESSION EDGE DID NOT START`**, follow the printed **Action required**.

**Capital base is automatic.** On the **first run for an account**, the launcher
captures the current DEMO balance and **pins** it as the FTMO starting capital
(`SESSION_EDGE_INITIAL_BALANCE`); every later start reuses that pinned value — it is
**never** re-read from the live balance, so a drawdown can never weaken your max-loss
floor (H3 preserved). See **First-run initialization** below for when to override.

### First-run initialization (only if needed)

- If your **true FTMO starting capital differs** from the current demo balance (e.g.
  you have already traded the demo), pin it explicitly the first time:
  `run_session_edge.bat --initial-balance 50000`.
- To **correct** an already-pinned value later (deliberate reset):
  `run_session_edge.bat --reinitialize 50000`.
- A plain `--initial-balance` that **conflicts** with an already-pinned base is
  **refused** (fail closed) — use `--reinitialize` to change it on purpose.
- **Switching to a different DEMO account** is detected automatically: the previous
  account's base is never reused; the new account gets its own pinned base
  (`ACCOUNT CHANGED — initializing a NEW capital base`).

The pinned record lives in `…\MQL5\Files\session_edge_runtime\capital_base.json`
(one immutable record per account identity; owned solely by `runtime/capital.py`).

---

## A. Prerequisites

- **Windows 10/11** (the launcher/producer/manager attach to a running MT5 terminal
  via the `MetaTrader5` Python package — Windows only; `runtime/launcher.py:154`).
- **MetaTrader 5 terminal** installed, running, and **logged into a DEMO account**.
  The launcher **refuses any non-DEMO account** (`launcher.py:234`, `runner.preflight`).
- **Python 3.9+** (stdlib `zoneinfo`; 3.11 is fine). Verified by
  `python -m forex_swing_orb.runtime.preflight`.
- The Session Edge repository present on the machine (see §B).
- Your **true FTMO challenge starting capital** number (e.g. 50000) — you pass it
  explicitly; it is pinned and never read from the live account (`launcher.py:268`).

## B. Fresh-machine installation

1. Put the repo on the machine (git clone, or copy the deployment set from §10).
2. Install Python 3.9+ and add it to PATH.
3. Install dependencies (§C) — **including `tzdata`**.
4. Install + compile the EA (§F) and attach it (§F).
5. Run the preflight (§J) and the pre-flight checklist (§K).
6. Start Session Edge (§H).

## C. Python setup

A virtual environment is **recommended** (isolation), not required:

```
python -m venv .venv
.venv\Scripts\activate
```

Install the **exact** runtime dependencies (derived from source imports):

```
pip install MetaTrader5 pandas numpy tzdata
```

- `MetaTrader5` — terminal attach + read-only rates/account/deal history
  (`live/mt5_client.py`), and the launcher connection (`launcher.py:156`).
- `pandas`, `numpy` — the frozen engine + providers.
- **`tzdata` (REQUIRED on Windows).** Session Edge uses stdlib `zoneinfo`
  (`session/model.py:19`, `compliance/contract.py:304`, `session/profiles.py:101`).
  Windows ships no IANA tz database, so without `tzdata` the required zones
  (`Europe/Prague`, `Europe/London`, `America/New_York`, `Asia/Tokyo`,
  `Australia/Sydney`) fail to load and config/session logic **fails closed**. (Note:
  the older `run_session_edge.bat` comment lists only `MetaTrader5 pandas numpy` —
  add `tzdata`.)

The **newsfeed** calendar acquisition uses only the Python standard library (no
`requests`); no extra dependency is needed for Session Edge.

## D. Session Edge configuration

You normally do **not** hand-edit config: the launcher (§H) auto-discovers the
terminal Files folder + account currency and sets every `SESSION_EDGE_*` variable
(`launcher.py:build_env`), then starts the children. What you must supply:

| Input | How | Required |
|---|---|---|
| FTMO starting capital | **Auto-pinned on first run** (see Normal Startup); override with `--initial-balance <N>`, reset with `--reinitialize <N>` | No (auto) |
| FTMO profile attestation | `--ftmo-verified` (the `.bat` passes it) | **Yes** |
| DEMO account | must be the logged-in terminal account | enforced |
| Symbols | `--symbols EURUSD,GBPUSD` (`.FX` added automatically) | default `EURUSD` |
| Sessions | `--sessions LONDON` / `NEW_YORK` / `ALL` … | default `LONDON` |
| Broker symbol suffix | `--symbol-suffix .a` (only if your broker uses one) | default none |

The canonical env schema and fail-closed validation live in `runtime/config.py`
(required keys: `bridge_root, runtime_dir, symbols, initial_balance,
account_currency, ftmo_rule_source, ftmo_rule_source_verified_at,
ftmo_profile_verified=true, news_file, overlap_mode`). Defaults: `daily_loss_pct
0.05`, `maximum_loss_pct 0.10`, `reset_timezone Europe/Prague`, `cadence_sec 900`
(M15). The **MT5 password is an env var only** (`SESSION_EDGE_MT5_PASSWORD`) and is
never stored/echoed — but normally you just log the terminal in by hand and the
launcher attaches, so no password env is needed.

## E. MT5 setup

1. Open MT5, log into your **DEMO** account, keep it running.
2. Add your trading symbols to **Market Watch** (so history/metadata are available).
3. **Tools → Options → Expert Advisors:** allow automated trading; allow DLL not
   required. Enable the terminal's global **Algo Trading** button.
4. (For auto-start) set MT5 to launch at logon and auto-login to DEMO.

## F. EA installation & compilation

Source (`ea_mt5/README.md` "Deployment notes"):

1. Copy **all three** files into the **same** folder
   `…\MQL5\Experts\SessionEdge\`:
   - `forex_swing_orb/ea_mt5/SessionEdgeExecutionEA.mq5`
   - `forex_swing_orb/ea_mt5/JsonBridge.mqh`
   - `forex_swing_orb/ea_mt5/SessionEdgeManageHandler.mqh`
   (`Trade\Trade.mqh` is stock MQL5, already under `MQL5/Include/`.)
2. In **MetaEditor**, make the **`SessionEdgeExecutionEA.mq5` tab active** and press
   **F7**. Compile **only the `.mq5`** (the two `.mqh` are include fragments; a
   missing `SessionEdgeManageHandler.mqh` causes `ManageRecover/ManageProcessNext`
   errors). Expect **0 errors** (a few candidate warnings — Phase-5 §3.2).
3. Attach the compiled EA to **one** chart (any symbol/timeframe — the EA is
   timer-driven, `OnTick` is empty; a single instance polls the bridge and executes
   every symbol's instruction). One instance is sufficient.
4. EA inputs (operational, not strategy):
   - `BridgeRoot = session_edge_bridge` (default; matches the launcher's path)
   - `UseCommonFolder = false` (default — the terminal's own `MQL5\Files`)
   - `BrokerSuffix = ""` (set only if your broker's symbols carry a suffix — must
     match `--symbol-suffix`)
   - `PollSeconds`, `MagicNumber` — leave defaults
   - `DefaultVolume` — **DEPRECATED / inert** (M9: the instruction's authoritative
     `volume` is executed verbatim; the EA never sizes from risk).
5. Confirm the smiley/Algo-Trading is green on the chart.

## G. Bridge setup

Nothing to create by hand. The producer creates the full tree via
`BridgePaths.ensure()` at:

```
<MT5 data folder>\MQL5\Files\session_edge_bridge\
   outbox\pending  outbox\claimed  inbox\results  inbox\acks
   archive\accepted  archive\rejected  quarantine  health
```

The launcher points the producer at exactly this path
(`launcher.bridge_root_from_data_path`), and the EA's `BridgeRoot` default reads the
same folder. Find the data folder in MT5 via **File → Open Data Folder**.

## H. Starting Session Edge

**The one correct launcher is `forex_swing_orb.runtime.launcher`.** Do **not** use
`run_demo.py` (that launches *Phantom*).

Double-click friendly — **normally no arguments** (capital base is auto-pinned on
first run):

```
run_session_edge.bat
run_session_edge.bat --symbols EURUSD,GBPUSD --sessions LONDON,NEW_YORK
run_session_edge.bat --initial-balance 50000      (first-run override only)
run_session_edge.bat --reinitialize 50000         (deliberate reset)
```

Equivalent explicit command:

```
python -m forex_swing_orb.runtime.launcher --ftmo-verified --symbols EURUSD --sessions LONDON
```

Auto-start at logon (optional): run `setup_autostart.bat` **once** after editing
`autostart_run.bat` to set `INITIAL_BALANCE` (it uses `--wait-for-terminal 900`).
`remove_autostart.bat` undoes it.

## I. Startup order

The launcher spawns three children **together**, in this order
(`launcher.CHILDREN`): **`newsfeed` → `producer` → `manage`**. They run concurrently
under one graceful shutdown; if any child exits the launcher stops the pipeline.
The `newsfeed` must write a fresh `news_bundle.json` before the producer's news gate
can pass — until then the news gate fails closed (no trade), which is expected.

## J. Readiness verification

`SYSTEM STARTED` ≠ `READY TO AUTHORIZE NEW TRADES`. Distinguish them:

- **STARTED**: the three processes are up and writing health files under
  `…\MQL5\Files\session_edge_runtime\` (`producer_health.json`,
  `compliance_status.json`, `session_status.json`, `manager_health.json`).
- **READY TO AUTHORIZE** requires, on a just-closed M15 bar, ALL of:
  - account snapshot **fresh** (≤ `max_account_age_sec` = 60 s) and **DEMO**;
  - **fresh news bundle** present (newsfeed has run);
  - **≥ 60 closed M15 bars** of history for the symbol (`min_history_bars`,
    `runner.py:235`) plus H4/D1 history (broker supplies on connect);
  - inside an **eligible session** and **not** past the M12 Friday entry cutoff;
  - **bridge healthy** (H5) and terminal connected;
  - every compliance gate passes (kill→market→ftmo→session→news→broker-health→risk).
  A trade occurs only when a qualified ORB setup additionally forms.

Run the read-only self-check any time (see §K).

## K. DEMO pre-flight checklist

Run the canonical read-only self-check (no trades, no process start):

```
python -m forex_swing_orb.runtime.preflight
```

It reports `PASS` / `FAIL` / `ENV VALIDATION REQUIRED` for: Python≥3.9, pandas,
numpy, MetaTrader5, timezone/`tzdata`, config, bridge folders, MT5 connection, DEMO
account, symbol metadata (tick size/value, volume min/max/step), M15 bar
sufficiency, and the B2 UTC time-base item. Exit code `0`=all PASS, `1`=any FAIL,
`2`=ENV items remain. **No fake green** — anything needing the live terminal is
reported `ENV VALIDATION REQUIRED`, not PASS.

Manual checklist (tick before enabling DEMO trading):

- [ ] Python 3.9+ and deps installed (incl. `tzdata`)
- [ ] MT5 open, logged into **DEMO**, Algo Trading green
- [ ] EA compiled (0 errors) and attached to one chart
- [ ] Symbols in Market Watch; `--symbol-suffix` matches broker (`BrokerSuffix`)
- [ ] `--initial-balance` = your true FTMO starting capital
- [ ] Bridge folder present under `MQL5\Files\session_edge_bridge`
- [ ] `producer_health.json` / `manager_health.json` / `compliance_status.json`
      appear and read healthy
- [ ] news bundle present and fresh
- [ ] account freshness OK (≤60 s), no unexpected open positions
- [ ] not inside the Friday/weekend no-entry window unless intended

## L. First safe startup

Start the launcher (§H); watch the launcher console banner (account/init/symbols/
bridge). Confirm health files appear, the EA prints "Session Edge Execution Adapter
initialised", and the bridge `outbox/pending` starts receiving instructions on
closed M15 bars during an eligible session. The first order is placed by the EA only
after a fully-gated instruction is written and claimed.

## M. Normal shutdown

Press **Ctrl+C** in the launcher window (or stop the scheduled task). The launcher
terminates newsfeed/producer/manager gracefully. The EA can stay attached; it simply
finds no new pending instructions. No state is lost — all state is on disk.

## N. Restart / recovery

Session Edge is **restart-safe** — state is reconstructed from the filesystem bridge
+ broker truth, never memory:

- The manager **adopts** open positions and re-derives truth via `pm.recover()`
  (closed is only ever confirmed from broker deals — H1).
- The EA/consumer **recovers** stranded claims against broker truth and **never
  double-sends** (bridge dedup + point-of-execution check + recovery).
- The outcome reconciler is **idempotent** (one `execution_outcome` per signal_id).

Just re-run the launcher. Restart is safe at any time.

## O. Weekend behavior

Two **separate** owners (do not conflate):

- **ENTRY cutoff (M12)** — per-session, local, DST-aware: SYDNEY **19:00**, TOKYO
  **21:00**, LONDON **20:00**, NEW_YORK **20:00** local. No new entries after the
  cutoff (`producer/runner.py:201`, reason `R_FRIDAY_NO_NEW_ENTRY`).
- **MANAGEMENT weekend flatten (M13)** — the Position Manager protectively closes
  open positions at **Friday 20:00 UTC** (`position_manager._weekend_due`,
  `position/contract.py:129`).

**Sunday / market-closed start is SAFE:** with no fresh ticks the account snapshot
and bars are stale → the producer fails closed → **no trades** until the market
opens with fresh data inside an eligible session. Use `--wait-for-terminal` so
auto-start survives MT5 opening a little later.

## P. Troubleshooting

- `bridge_root '…' not found under the terminal Files folder` — informational; the
  producer creates it on start. If it persists, the producer isn't running or
  `UseCommonFolder` disagrees between EA and launcher.
- `MetaTrader5 unavailable` — open + log into the DEMO terminal; `pip install
  MetaTrader5`.
- `account is not DEMO` — the launcher refuses non-demo (by design).
- `--initial-balance is REQUIRED` — pass your FTMO starting capital.
- timezone/`ZoneInfoNotFoundError` — `pip install tzdata`.
- EA compile errors about `ManageRecover`/`JsonGetLong` — you compiled a `.mqh` or
  the header is missing; make the `.mq5` tab active and keep all three files together.
- No trades — check §J readiness (session eligibility, news bundle freshness, bar
  count, account freshness, bridge health) via the health files and preflight.

## Q. Health / status interpretation

Under `…\MQL5\Files\session_edge_runtime\`:
`producer_health.json`, `compliance_status.json`, `session_status.json`,
`manager_health.json`, plus audit logs (`runner_audit.jsonl`,
`compliance_audit.jsonl`, `pm_audit.jsonl`) and the bridge `health/audit.jsonl`.
These are read-only status snapshots (never secrets). A blocked cycle records a
reason code (e.g. `R_DATA_STALE`, `NEWS_IMPACT_UNKNOWN`, `RISK_MONETARY_UNVERIFIABLE`,
`BRIDGE_UNHEALTHY`) — that is the system working as designed (fail-closed), not an error.

## R. Fail-closed behavior (expected, capital-safe)

The system **blocks rather than guesses** on: stale/future/gapped bars
(`R_DATA_*`), stale/future account (`R_ACCOUNT_*`), unknown news impact
(`NEWS_IMPACT_UNKNOWN`), missing FTMO anchor, unverifiable monetary risk / missing
tick metadata (`RISK_MONETARY_UNVERIFIABLE`), invalid symbol geometry (H6/M11 — no
digit/pip fallback), bridge unhealthy / ack missing, terminal disconnect, ambiguous
execution (`RETRY_PENDING`/`RECONCILIATION_REQUIRED`), and the weekend window. None
of these are failures to fix on the machine — they are safety gates.

## S. ENV validation checklist (needs the live Windows/MT5 DEMO terminal)

These cannot be proven off-Windows and are marked **MANUAL DEMO VALIDATION
REQUIRED**. Execute them per the Phase-5 matrix
(`docs/SESSION_EDGE_PHASE_5_MT5_COMPILATION_AND_DEMO_VALIDATION.md` §5/§6/§9) and the
read-only probes:

- **B2 — MT5 time-base is true UTC**: `python -m
  forex_swing_orb.validation.mt5_timebase_probe` (offset ≈ 0 confirms the UTC
  assumption; production applies no offset).
- **Outcome/deal semantics** (ticket↔position_id, `history_deals_get`,
  DEAL_ENTRY/REASON enums, partial-close/net-flat, deal-history latency):
  `python -m forex_swing_orb.validation.mt5_outcome_probe` (read-only).
- **Symbol metadata on the real broker**: `SYMBOL_TRADE_TICK_SIZE`,
  `SYMBOL_TRADE_TICK_VALUE` (and whether `SYMBOL_TRADE_TICK_VALUE_LOSS`'s omission is
  safe — the code reads only `trade_tick_value`), `SYMBOL_POINT`, `SYMBOL_DIGITS`,
  `SYMBOL_VOLUME_MIN/MAX/STEP`.
- **Currency denomination**: confirm `trade_tick_value` is in the deposit currency
  (the loss-at-stop math assumes this).
- **Volume behavior**: requested vs filled volume, partial-fill reporting, MQL5
  volume-step rejection, and **no volume normalization that increases risk**
  (round-down only).
- **Geometry**: JPY (3-digit) vs non-JPY (5-digit); the known caveat that on 3-digit
  JPY the break-even stop can equal entry (fails **closed** — capital-safe); exotic
  tick grids.
- **Broker stop acceptance + read-back** (F2), and stop-modify tick-grid reconcile.
- **Execution/reconciliation**: BUY/SELL fills with SL/TP and `comment==signal_id`;
  market-closed/requote/off-quotes/invalid-volume rejections; terminal
  disconnect/reconnect; restart mid-flight in each recovery state.
- **[ENV] source-parity guards** (m9 volume, pr4a1 bridge, pr3f/pr3f1 protocol) —
  assert the shipped `.mq5` shape only; real broker execution remains operator-verified.

> Note: an item sometimes referred to as "P3A-4" does **not** exist in the source.
> The real deferred item is **B2** (above) plus the Phase-5 matrices; do not treat a
> non-existent P3A-4 as a gate.

## T. What NOT to run

- ❌ `run_demo.py` — launches **Phantom**, not Session Edge.
- ❌ `phantom_institutional.py` / any `phantom/` service — separate quarantined system
  (PR-3R); never on the Session Edge trading VPS.
- ❌ Phantom env vars (`PHANTOM_*`, `TWELVE_DATA_API_KEY`, `TELEGRAM_*`) — not used
  by Session Edge.
- ❌ bare `pytest` at the repo root — collects Phantom's tests (needs uninstalled
  deps). Run Session Edge tests scoped: `pytest forex_swing_orb/`.
- ❌ a non-DEMO / live account — the launcher refuses it by design.

## U. Rollback / recovery & fast update (see also §9/§10)

- **Version identity**: `git rev-parse HEAD` on the machine records the deployed
  commit.
- **Fast update**: `git pull` (simplest), or copy only the deployment set (§10). Do
  this **only when no instruction is mid-execution** — verify the bridge
  `outbox/pending` and `outbox/claimed` are empty first.
- **Never** delete/overwrite the runtime state under `MQL5\Files\session_edge_bridge`
  or `…\session_edge_runtime` (bridge pending/claimed/results, execution_outcome
  history, daily anchor). These live on the target only and are excluded from the
  deployment manifest.
- **Rollback**: `git checkout <previous-commit>` (or redeploy the prior manifest
  set) and restart the launcher; runtime state is preserved.

### Deployment manifest (the sole deployment-file authority)

`forex_swing_orb/runtime/deploy_manifest.py` defines exactly which files belong on
the trading machine. List them with:

```
python -c "from forex_swing_orb.runtime import deploy_manifest as m; print('\n'.join(m.deployment_files('.')))"
```

It **includes** the `forex_swing_orb/` runtime package (producer, manager, newsfeed,
launcher, live client, compliance, bridge, position, session, the EA sources under
`ea_mt5/`, and the frozen engine under `run_dir/code/`) plus the four `.bat`
launchers; it **excludes** `phantom/`, `phantom_institutional.py`, the Phantom root
docs/scripts, `research/`, all `tests/`, `__pycache__`/caches, logs, secrets, and the
live runtime-state directories.
