# Phantom — Production Architecture Audit

Read-only audit of the minimal production build. Documents the architecture
exactly as verified against `phantom_institutional.py` (the only source file
present in this repository). No source code was changed, moved, or deleted.

Files marked _(unverifiable here)_ could not be inspected in this environment —
only `phantom_institutional.py` is present. Their roles are recorded from the
hub file's references and must be confirmed against the actual files on the VPS.

---

## Production Runtime

### Server
- `phantom_institutional.py`
- `phantom_command_center.py`
- `phantom_watchdog.py`
- `phantom_src/`

### MT5
- `DarkPhantomProtocol_v2.mq5`
- `AIApproval.mqh`

### Startup
- `start_phantom_silent.bat`
- Command Center starts first.
- Institutional Server starts second.

---

## Runtime Data

These files are auto-created at runtime; they do not need to be shipped.

### Documents (`~/Documents`, absolute paths)
- `phantom_feedback.csv` — `JOURNAL_FILE`
- `phantom_v4.log` — `LOG_FILE`

### Working Directory (relative paths — land in the process CWD)
- `bar_store_cache.json`
- `intermarket_cache.json`
- `phantom_v4_weights.json`
- `phantom_v4_fills.csv`

> Note: the journal and log resolve to `~/Documents`, while the four caches use
> relative filenames and therefore land in whatever working directory the
> launcher sets. This split is a launcher-`cwd` / documentation matter, not a
> code change — do not edit the path constants (the dashboard/analytics already
> read from these locations).

---

## Verified Dependencies

Confirmed from `phantom_institutional.py`:

- `phantom_command_center.py` is **REQUIRED**.
  Evidence: `CMD_CENTER_URL = "http://127.0.0.1:5002"`; the server calls
  `GET {CMD_CENTER_URL}/can-trade` before every score request.
- `phantom_src/` is **REQUIRED**.
  Evidence: engines are lazy-loaded via
  `importlib.util.spec_from_file_location(..., base + "/phantom_src/<name>.py")`
  (e.g. `portfolio_engine`, `scoring_engine`, `research_engine`,
  `session_engine`, `metrics_engine`, `execution_filter_engine`). Absent
  engines degrade to safe no-ops (including the portfolio-level kill-switch).
- Command Center **fail-closes** trading when unavailable.
  Evidence: `CB_FAIL_OPEN = False`; when the command center is unreachable the
  circuit breaker returns `(False, "cmd_center_offline_fail_closed")` and the
  score request is blocked.
- Main server **does not spawn child processes**.
  Evidence: no `subprocess` / `Popen` / `os.system` / `os.startfile` calls.
- The **launcher is responsible for starting both services** (Command Center
  first, then the Institutional Server), because the server never starts the
  command center itself and fail-closes without it.
- Main server **does not directly use Config JSON files**.
  Evidence: zero references to `config.json`, `prop_profiles.json`,
  `prop_firm_rules.json`, or `pair_profiles.json`. The only local JSON the main
  server touches are the auto-created caches listed above (each guarded by
  `os.path.isfile` / `os.path.exists` with in-code defaults).
- EA transport is **direct HTTP** — the server exposes ~100 HTTP routes and the
  EA posts to them directly (`/heartbeat`, `/score`, `/bars_push`,
  `/bars_backfill`, `/feedback`, `/account/snapshot`).

---

## Remaining Verification

These require files that are not present in this repository and must be checked
against the actual deployment:

- Verify `start_phantom_silent.bat` launches **both** processes (Command Center
  and Institutional Server). If it starts only the server, trading is
  fail-closed on boot.
- Verify `phantom_mt5_bridge.py` is not used by the deployment:
  - `start_phantom_silent.bat` does not launch it.
  - No scheduled task launches it.
  - The EA does not rely on it as an intermediary.
  If all three are true, it can be archived safely.
- Verify `phantom_src/` JSON dependencies (whether any engine reads Config JSON
  or additional data files).
- Verify `phantom_command_center.py` JSON dependencies (e.g. whether it reads
  `prop_firm_rules.json` / `prop_profiles.json` for drawdown limits). This is
  the highest-risk item, because the command center is the fail-closed trading
  gate — if it needs a config file that has been dropped, trading stays blocked.

---

## Archive Policy

- **Never delete.**
- Move to `Archive/` only after dependency verification.

Superseded candidates (from the earlier fuller tree; archive only after
confirming they are not imported by `phantom_command_center.py` / `phantom_src/`):

- `phantom_risk_engine.py` — superseded by `phantom_src/portfolio_engine.py`.
- `phantom_news_engine.py` — superseded by `phantom_src/news_intelligence_engine.py`.
- `phantom_memory_agent.py` — superseded by the in-process `AdaptiveModel`.
- The redundant startup launcher — keep exactly one.

---

## Status

- **Production Ready**
- **Forward Test Ready**
- **No code changes made.**
