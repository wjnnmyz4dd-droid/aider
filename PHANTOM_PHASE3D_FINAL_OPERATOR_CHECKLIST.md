# Phase 3D — Final Operator Checklist

Day-to-day operation guidance once Titan Protocol is installed and
running on a real MT5 demo account.

## Routine checks

- Run `python health_check.py` at least once per trading day. Expect
  `STATUS: DEGRADED` — this is the correct, honest steady state (see
  Production Readiness Report). `FAILED` or an unexpected new `[FAIL]`
  line warrants investigation.
- Confirm `MT5 bridge connectivity (EA heartbeat)` stays PASS while MT5
  and the EA are running. A flip to FAIL with MT5 open usually means the
  EA was detached, Algo Trading was disabled, or the terminal lost
  connectivity to your broker.
- Confirm `market-data readiness` warmup/freshness counts keep climbing
  or stay `ready` — a pair stuck at `not ready` for longer than its
  configured warmup period (50 bars at your primary timeframe) usually
  means the EA isn't receiving/forwarding bars for that symbol (check
  that the symbol's chart is open and the EA is attached to it).
- Confirm `live trading cycle active` keeps advancing (`last cycle
  live-N` with increasing N) — if it stops advancing, the process may
  have stalled; restart via `stop.py` then `start.py`.

## Distinguishing failure types

| Symptom | Likely cause |
|---|---|
| `MT5 bridge connectivity (EA heartbeat)` FAIL, everything else fine | EA detached, Algo Trading off, or terminal disconnected — check MT5 directly |
| A specific pair stuck at `market_data_not_ready` with a low bar count | EA isn't forwarding bars for that symbol yet — check the symbol has an open chart with the EA attached |
| A specific pair `ready` by count but still skipped | Check `freshness` for that pair — a stale timestamp means bars stopped arriving even though enough were received earlier (e.g., market closed, broker feed gap) |
| `queue health` degraded/critical | Bridge is queuing more commands than it's draining — check for a stuck or crashed EA not polling `/bridge/commands/poll` |
| Process not running at all | `python start.py` again; check `logs/` for the crash reason before restarting blindly |

## When to restart vs. investigate

- Restart (`stop.py` then `start.py`) for: a stalled live-cycle counter, a
  clearly detached/reattached EA, or after any MT5 terminal restart.
- Investigate before restarting for: an unexpected `FAILED` status, a
  queue depth that's growing instead of draining, or any error you don't
  recognize in `logs/` — restarting can mask a real, recurring problem.

## What NOT to do

- Do not fund the account while `STATUS: DEGRADED` items 1-2 in the
  Production Readiness Report remain open (day-start/peak/lock
  persistence, in particular).
- Do not manually edit `state/health.json` or `RELEASE_MANIFEST.json` —
  both are generated, not hand-maintained.
