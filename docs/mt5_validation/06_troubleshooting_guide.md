# 06 — Troubleshooting Guide

**Status: DEPRECATED.** Written for `mt5/PhantomBridgeEA.mq5` (ADR-023's
original HTTP-only-transport EA), which no longer exists in this
repository -- it was replaced by `mt5/TitanProtocolEA.mq5` (socket
transport by default, with automatic HTTP fallback; ADR-034). See
`deployment_windows/REAL_MT5_VALIDATION_CHECKLIST.md` for the current
real-MT5 validation checklist. Kept for historical reference only.


Symptom-first. Each entry names the likely cause in this specific
codebase (not generic MT5 advice) and where to look.

## EA won't attach / sad face on chart

- **Symbol not allowed:** `AllowedSymbolsCsv` doesn't include the
  chart's symbol and isn't empty. `OnInit()` -> `IsSymbolAllowed`
  check. Fix the input, reattach.
- **Empty API key:** `ApiKey` input is blank. `OnInit()` refuses by
  design. Set a real key.
- **AutoTrading disabled:** this doesn't fail `OnInit()` itself, but
  every subsequent `CTrade` call will fail `TERMINAL_TRADE_NOT_ALLOWED`
  via `CheckTradingPreconditions` — check the toolbar toggle first if
  trades silently never execute despite a successful attach.

## No telemetry ever reaches the bridge server

- **`WebRequest` not allow-listed:** by far the most common cause.
  MT5 blocks all outbound `WebRequest` calls to URLs not explicitly
  added under **Tools -> Options -> Expert Advisors**. `HttpPost`/
  `HttpGet` will get `status <= 0` on every attempt and retry
  `MaxRetries` times, then give up silently (by design — see
  `HttpPost`'s final `return("")`). Check the Journal for
  `WebRequest error` entries (MT5 logs these itself even though this
  EA doesn't explicitly `Print` on that path).
- **Wrong `BackendUrl`:** typo, wrong port, or the bridge server bound
  to a different host/port than configured.
- **Bridge server not running / crashed:** check the process directly;
  the EA has no way to distinguish "server down" from "URL blocked" —
  both look identical from the EA's side (`status <= 0`).

## Heartbeats arrive but no commands ever execute

- **Fail-closed still active from a prior outage:** confirm
  `g_lastSuccessfulContact` is actually recent — a single successful
  heartbeat POST does update it, so if heartbeats are landing this
  should not be the cause; if commands still don't execute, check the
  next two items instead.
- **`EmergencyDisable=true`:** check the EA's current input values (not
  just the `.set` file — inputs can be edited per-chart and diverge
  from the template).
- **Server-side emergency stop active:** `GET /bridge/commands/poll`
  will report `"emergency_stop": true` — check the bridge server's
  `engine.emergency_stop_state`.
- **Magic number mismatch:** the EA's poll includes
  `magic_number=<MagicNumber>`; if it doesn't match
  `BridgeConfig.magic_number`, the server's validation layer rejects
  the poll (400 `MAGIC_NUMBER_MISMATCH`), which looks like "no
  commands" from the EA's perspective unless the response status is
  also being checked.

## A command executes but is never reported / reported twice

- **Never reported:** check `ReportExecutionResult`'s own `HttpPost`
  call succeeded — if the bridge server was unreachable at the exact
  moment of execution, the report send fails and is not queued for
  later retry (Phase 1 has no report-resend mechanism; this is a
  known limitation, not a bug — see the Known Limitations section
  below).
- **Reported twice:** should not happen — this is exactly what Fix #4
  in `PHANTOM_BRIDGE_EA_PHASE1_FIX_REPORT.md` and test N6
  (`02_demo_validation_plan.md`) guard against. If observed, this is a
  regression and must be treated as a blocking defect, not something
  to route around.

## `filled_volume` looks wrong

- Confirm which `Execute*` function handled the command. All four
  volume-bearing ones (BUY/SELL/CLOSE/PARTIAL_CLOSE) report
  `g_trade.ResultVolume()`, the real fill — if a report shows the
  requested volume identically every time even across partial fills,
  this is a regression of Fix #2 and blocks sign-off.

## A trade is rejected with a named string instead of a number

- This is by design — any `error_code` that is not purely numeric
  (e.g. `SYMBOL_NOT_ALLOWED`, `VOLUME_BELOW_MIN`,
  `STOP_LOSS_TOO_CLOSE`, `UNKNOWN_OR_FOREIGN_POSITION`,
  `TERMINAL_TRADE_NOT_ALLOWED`, `ACCOUNT_TRADE_NOT_ALLOWED`,
  `EXPERT_TRADE_NOT_ALLOWED`, `SYMBOL_NOT_AVAILABLE`,
  `SYMBOL_TRADE_DISABLED`, `SYMBOL_CLOSE_ONLY`,
  `MARKET_CLOSED_OR_NO_QUOTES`, `VOLUME_ABOVE_MAX`,
  `VOLUME_NOT_STEP_ALIGNED`, `TAKE_PROFIT_TOO_CLOSE`,
  `INVALID_PARTIAL_CLOSE_VOLUME`) came from a pre-flight check
  (`CheckTradingPreconditions`/`CheckVolumeValid`/`CheckStopsValid`)
  and never reached `CTrade` at all. A purely numeric string (e.g.
  `"10004"`, `"10019"`) is a raw MT5 `ENUM_TRADE_RETCODE` value from
  an actual broker-side rejection. Use this distinction to triage
  quickly: named string = this EA's own gate; number = the broker's.

## Server returns 401 unexpectedly

- Check `X-Phantom-Api-Key` header value against `BridgeConfig.api_key`
  exactly — this is a byte-for-byte comparison
  (`validation.check_api_key`), no trimming or case-insensitivity.
  A trailing space or newline copied into either the `.set` file or
  the server's config is a common cause.

## Server returns 400 unexpectedly on a request that "looks right"

- Check `magic_number` type — the server expects an integer; a client
  sending it as a string will fail JSON-shape expectations in the
  handler (`body["magic_number"]` used as an int downstream).
- Check for stale/future timestamps if the failing route is one that
  validates timestamp freshness (`validate_inbound_message`'s
  `check_timestamp_fresh`) — clock skew between the machine running
  MT5 and the machine running the bridge server is a realistic cause
  in a two-host deployment.

## Known limitations to distinguish from defects

- `g_lastTickAt` is set in `OnTick()` but not read anywhere else in
  the file — harmless dead state, not a defect, does not affect
  fail-closed logic (which only depends on `g_lastSuccessfulContact`).
- No report-resend/retry exists if `ReportExecutionResult`'s own HTTP
  call fails after a successful trade execution — the trade itself is
  correct and complete on the MT5 side, but the bridge server may
  never learn about it until the next `/bridge/positions` /
  `/bridge/trade-transaction` telemetry cycle surfaces it indirectly.
  This is a documented Phase-1 scope limitation (see
  `PHANTOM_BRIDGE_EA_PHASE1_REPORT.md`), not something this validation
  package's rules permit fixing as a side effect of a compile/demo
  test.
- Phase 1's transport is plain HTTP by default (see test A9) — secure
  only insofar as it stays on loopback; this is a deployment-topology
  consideration, not a code defect.
