# Real-MT5 Validation Checklist (Final Release Hardening, requirement 5)

Every item below requires a real Windows MetaTrader 5 terminal, a real
(demo or funded) broker account, and this software actually running
against it. **Nothing in this document has been executed.** No result
here is fabricated: every item is marked **PENDING REAL MT5** until an
operator runs it and records the real outcome. This checklist exists so
that when that happens, there is one exact, pre-agreed list of gates to
run through -- not an ad-hoc verification invented after the fact.

Everything that *can* be verified without a real MT5 terminal already
has been, elsewhere in this repository's test suite (`tests/`) and in
`PHANTOM_FINAL_PRODUCTION_CERTIFICATION_AUDIT.md`. This document only
covers what that suite structurally cannot reach.

## How to use this document

1. Work through the sections in order -- each one depends on the
   previous one having actually passed (e.g. there is no point testing
   heartbeat/reconnect before the EA compiles and attaches).
2. For each item, record: the exact date/time run, the MT5 build
   number, the broker/server name, and the observed result (not just
   pass/fail -- paste the actual log line, health.json snippet, or
   screenshot reference).
3. Change **PENDING REAL MT5** to **PASSED** or **FAILED** only after
   it has actually been run. A checklist with items silently left as
   PENDING is more honest than one with guessed PASSED marks.
4. If an item fails, do not edit the code to make the checklist look
   better -- fix the real defect, note it under "Failures found" at the
   bottom, and re-run from the earliest affected section.

---

## 1. Compilation and artifact generation

| # | Item | Status |
|---|------|--------|
| 1.1 | `mt5/TitanProtocolEA.mq5` compiles in MetaEditor with **0 errors** (warnings should be reviewed but do not block) | PENDING REAL MT5 |
| 1.2 | Compilation produces `TitanProtocolEA.ex5` in the expected `MQL5/Experts/` location | PENDING REAL MT5 |

**Why this can't be checked here:** MetaEditor is Windows-only; no
instance is available in this development environment. Source-level
checks already done instead (brace/paren balance, no undefined
identifiers referenced, protocol contract tests in
`tests/mt5/test_titan_protocol_ea_emergency_stop.py`) are a proxy, not
a substitute, for a real compile.

## 2. Demo attach and live data flow

| # | Item | Status |
|---|------|--------|
| 2.1 | EA attached to a real demo-account chart, `EventSetTimer(1)` firing (visible in the Experts log) | PENDING REAL MT5 |
| 2.2 | Live ticks are received and reported to `/bridge/market-data` (confirm via Bridge logs or `state/health.json`'s market-data fields) | PENDING REAL MT5 |
| 2.3 | Live closed bars are received on the configured timeframe and reported the same way | PENDING REAL MT5 |
| 2.4 | Every enabled pair reaches a **50-bar M15 warmup** (`MarketDataIngestionEngine.is_ready()` returns true) before the live-cycle loop stops skipping it -- confirm via `health.json`'s `live_cycle` field or the `titan_protocol.deploy.live_cycle` log | PENDING REAL MT5 |
| 2.5 | Broker server time vs. local/UTC time is sane (no unexplained offset that would corrupt the trading-day boundary calculation in `compliance_state_store`) | PENDING REAL MT5 |
| 2.6 | Stale-feed detection: disconnect the data feed (or wait past `stale_after_seconds`) and confirm the pair is skipped with reason `market_data_not_ready`, never traded on stale data | PENDING REAL MT5 |

## 3. Heartbeat, reconnect, and restart resilience

| # | Item | Status |
|---|------|--------|
| 3.1 | Heartbeat cadence matches `HeartbeatIntervalSeconds`; `g_lastSuccessfulContact` advances on every successful contact | PENDING REAL MT5 |
| 3.2 | Kill the Bridge process, confirm the EA's fail-closed timeout (`FailClosedTimeoutSeconds`) actually halts polling/execution, then restart the Bridge and confirm the EA reconnects and resumes without a manual EA restart | PENDING REAL MT5 |
| 3.3 | **Terminal restart**: close and reopen the MT5 terminal with the EA attached; confirm it re-initializes (`OnInit()`) and resumes heartbeating without operator intervention beyond reopening the terminal | PENDING REAL MT5 |
| 3.4 | **Python process restart**: kill `python start.py` (or the detached process it launches) and restart it; confirm the Bridge rebinds and the EA reconnects on its next poll | PENDING REAL MT5 |
| 3.5 | **VPS/OS restart**: reboot the host machine entirely; confirm both the Python process (if configured to auto-start) and the MT5 terminal/EA recover to a healthy state without manual file edits | PENDING REAL MT5 |

## 4. Server-side emergency-stop synchronization

(Final Release Hardening requirement 3 -- code-level wiring is done
and covered by `tests/mt5/test_titan_protocol_ea_emergency_stop.py`'s
source-inspection tests; this section is the real-environment
confirmation those tests cannot provide.)

| # | Item | Status |
|---|------|--------|
| 4.1 | POST `/bridge/emergency-stop` with `{"active": true}`; confirm the EA's next poll response includes `"emergency_stop": true` and the Experts log prints the `ACTIVATED` line | PENDING REAL MT5 |
| 4.2 | While active, submit a command (e.g. via a manual test cycle) and confirm the EA logs `EMERGENCY_STOP_ACTIVE` and does **not** execute it | PENDING REAL MT5 |
| 4.3 | Confirm existing open positions are **not** auto-closed by the emergency stop | PENDING REAL MT5 |
| 4.4 | POST `/bridge/emergency-stop` with `{"active": false}`; confirm the EA's next poll logs the `CLEARED` line and resumes normal execution | PENDING REAL MT5 |
| 4.5 | Confirm the local `EmergencyDisable` input still independently halts everything (heartbeat, polling, execution) regardless of the server-side flag's state | PENDING REAL MT5 |

## 5. Real command execution

| # | Item | Status |
|---|------|--------|
| 5.1 | BUY command executes, position opens at market, `ExecutionReport` posted back correctly | PENDING REAL MT5 |
| 5.2 | SELL command executes, position opens at market, `ExecutionReport` posted back correctly | PENDING REAL MT5 |
| 5.3 | MODIFY_SL / MODIFY_TP command executes against an open position | PENDING REAL MT5 |
| 5.4 | PARTIAL_CLOSE command executes, remaining position size matches expectation | PENDING REAL MT5 |
| 5.5 | CLOSE command executes, position fully closed | PENDING REAL MT5 |
| 5.6 | A requote/price-changed condition is observed at least once and the bounded retry (`MaxRequoteRetries`/`RequoteRetryDelayMs`) is confirmed to behave as coded (retries, then reports the final result) | PENDING REAL MT5 |

## 6. Day-state persistence across restarts

(Final Release Hardening requirement 2 -- `titan_protocol.
compliance_state_store` is unit/integration tested against a real temp
file in `tests/titan_protocol/compliance_state_store/`; this section
confirms it holds up against the real restart types in section 3.)

| # | Item | Status |
|---|------|--------|
| 6.1 | Trigger a compliance lock (e.g. simulate a daily-loss-limit breach), restart the Python process, confirm the lock is still active after restart (not silently cleared) | PENDING REAL MT5 |
| 6.2 | Restart across an actual broker-time trading-day boundary (per `compliance.daily_reset_hour_utc`) and confirm `daily_starting_balance` resets exactly once, not on every restart | PENDING REAL MT5 |
| 6.3 | Kill the Python process mid-write (e.g. `kill -9` while a cycle is running) and confirm `compliance_state.json` is never left corrupt (atomic write) and the `.bak` recovers correctly on next start if it is | PENDING REAL MT5 |
| 6.4 | Restart the VPS itself (same event as 3.5) and confirm day-state survives that restart too, not only a Python-level restart | PENDING REAL MT5 |

## 7. News provider failover

| # | Item | Status |
|---|------|--------|
| 7.1 | Trading Economics (primary) reachable and returning real events; confirm `news_engine.fetch_events()` reports `trusted=True` sourced from TE | PENDING REAL MT5 |
| 7.2 | Disable/break the Trading Economics credentials or endpoint; confirm automatic failover to Forex Factory and `trusted=True` continues (sourced from FF) | PENDING REAL MT5 |
| 7.3 | Disable both providers; confirm the live-cycle loop skips **every** pair with reason `market_intelligence_not_ready` (fail closed, never stale/fabricated events) | PENDING REAL MT5 |
| 7.4 | Restore at least one provider; confirm the live-cycle loop resumes trading pairs on its own without a restart | PENDING REAL MT5 |

## 8. One-open-position-per-pair invariant (traced duplicate-command regression)

(Confirms the production invariant KNOWN_GAPS.md sections 4-5 describe:
Titan must never have more than one open position per pair, and must
never submit a second command while one is open -- both the compliance
position-limit gate and the in-flight command guard's post-resolution
position-confirmation window.)

| # | Item | Status |
|---|------|--------|
| 8.1 | With `compliance.max_positions_per_pair` at its default (1, absent from config), a qualifying signal submits exactly one command for a pair | PENDING REAL MT5 |
| 8.2 | While that command's position is open, a second qualifying signal for the *same* pair is rejected by compliance (`MAX_POSITIONS_PER_PAIR_EXCEEDED`) -- confirm via `RuntimeAuditRecord`/logs, never a guess | PENDING REAL MT5 |
| 8.3 | Confirm `bridge_submit` is never called for the rejected signal in 8.2 (no second order reaches MT5) | PENDING REAL MT5 |
| 8.4 | Set `compliance.max_positions_per_pair` to `2`, restart, and confirm a *second* position for the same pair is now allowed, and a *third* is rejected | PENDING REAL MT5 |
| 8.5 | Set `compliance.max_positions_per_pair` to `0` in the config file and confirm `start.py` refuses to start (`ConfigError`, fails closed, prints the reason) rather than silently falling back to a permissive default | PENDING REAL MT5 |
| 8.6 | Watch the logs across one full submit-to-execution cycle and confirm the `in_flight_registry_reconciled` / `in_flight_position_confirmation` / `portfolio_state_source` (with `position_report_age_seconds`) / `position_limit_check` lines all appear and their fields make sense relative to each other (in-flight count decrements only after both the ExecutionReport *and* a fresh position snapshot are observed, not the ExecutionReport alone) | PENDING REAL MT5 |
| 8.7 | If achievable in the test environment, deliberately widen the gap between `HeartbeatIntervalSeconds` (EA-side positions cadence) and the Python live-cycle interval to stress the ExecutionReport-vs-PositionReport window, and confirm no duplicate command is submitted even under that stress | PENDING REAL MT5 |

---

## Failures found

*(None recorded -- this checklist has not yet been executed against a
real MT5 environment.)*

## Sign-off

| Role | Name | Date | Result |
|------|------|------|--------|
| Operator who ran this checklist | | | |
| Reviewer (if applicable) | | | |

**Do not mark this document's overall status as PASSED, and do not
assign a Deployment/MT5 Readiness score of 100 in any certification
report, while any item above still reads PENDING REAL MT5.**
