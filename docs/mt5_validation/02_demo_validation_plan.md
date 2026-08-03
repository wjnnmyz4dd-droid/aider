# 02 — Demo Account Validation Plan

**Status: DEPRECATED.** Written for `mt5/PhantomBridgeEA.mq5` (ADR-023's
original HTTP-only-transport EA), which no longer exists in this
repository -- it was replaced by `mt5/TitanProtocolEA.mq5` (socket
transport by default, with automatic HTTP fallback; ADR-034). See
`deployment_windows/REAL_MT5_VALIDATION_CHECKLIST.md` for the current
real-MT5 validation checklist. Kept for historical reference only.


**Every test in this file requires a real MetaTrader 5 demo account,
a running instance of the Python bridge server (`phantom.bridge.server`),
and the compiled `PhantomBridgeEA.ex5` attached to a chart. None of it
has been executed in this sandbox — see the package index for why.**

## Prerequisites (set up once, before any test below)

- [ ] A demo account on a broker that permits `WebRequest` calls (MT5
      requires the bridge's host — e.g. `http://127.0.0.1:8787` — to be
      added under **Tools -> Options -> Expert Advisors -> Allow
      WebRequest for listed URL**, or the EA's `HttpPost`/`HttpGet`
      calls will fail with `status <= 0` on every attempt).
- [ ] `AutoTrading` enabled in the terminal toolbar (a disabled
      AutoTrading button makes `TERMINAL_TRADE_ALLOWED` false, which
      `CheckTradingPreconditions` now correctly rejects with
      `TERMINAL_TRADE_NOT_ALLOWED` — useful for test N9 below).
- [ ] The bridge server running locally and reachable at the
      `BackendUrl` input's address, with a known `ApiKey` and
      `MagicNumber` matching `BridgeConfig.api_key` /
      `BridgeConfig.magic_number` on the Python side.
- [ ] `AllowedSymbolsCsv` set to include the chart's symbol (or left
      empty, which defaults to the current chart symbol only).
- [ ] A packet capture or proxy (e.g. Fiddler, mitmproxy, or the
      bridge server's own structured logs) available to inspect the
      actual HTTP traffic during the negative tests, since several of
      them are only observable at the wire/log level, not on the
      chart.

## How to read each test entry

Every test below states: **Purpose**, **Steps**, **Expected result**,
**Pass criteria**, **Fail criteria**, **Recovery behavior**. Record the
actual outcome of each in the sign-off template
(`08_signoff_template.md`), not in this file — this file is the
procedure, not the record.

---

## A. Functional / lifecycle tests

### A1. EA loads successfully

- **Purpose:** confirm the compiled EA attaches to a chart without
  `INIT_FAILED`, given a valid `ApiKey` and an allowed symbol.
- **Steps:** attach `PhantomBridgeEA.ex5` to a chart whose symbol is
  either in `AllowedSymbolsCsv` or is the chart's own symbol with
  `AllowedSymbolsCsv` empty; set a non-empty `ApiKey`; confirm.
- **Expected result:** smiley-face icon in the top-right of the chart;
  Journal shows `PhantomBridgeEA initialized. Symbol=... Magic=...`.
- **Pass criteria:** `OnInit()` returns `INIT_SUCCEEDED`; the Journal
  line above appears exactly once per attach.
- **Fail criteria:** a sad-face icon, or `INIT_FAILED` in the Experts
  log, with either of the two `Print` rejection messages in
  `OnInit()` (`"chart symbol ... is not in AllowedSymbolsCsv"` or
  `"ApiKey is empty"`).
- **Recovery behavior:** none needed on success. On failure, fix the
  input (symbol or key) and reattach — `OnInit()` performs no partial
  setup before its checks, so there is no state to clean up.

### A2. `OnInit()` — symbol rejected

- **Purpose:** confirm the EA refuses to run against a symbol not on
  its allowlist rather than silently trading it.
- **Steps:** set `AllowedSymbolsCsv=GBPUSD` and attach the EA to a
  `EURUSD` chart.
- **Expected result:** `INIT_FAILED`, Journal message naming
  `EURUSD` as not in the allowlist.
- **Pass criteria:** EA does not attach (sad face); no heartbeat, no
  polling, no trade ever occurs on this chart.
- **Fail criteria:** EA attaches successfully despite the mismatch.
- **Recovery behavior:** correct `AllowedSymbolsCsv` or attach to the
  right chart; no other state exists to roll back.

### A3. `OnInit()` — empty API key

- **Purpose:** confirm the EA refuses to run with no credential rather
  than sending requests with a blank `X-Phantom-Api-Key`.
- **Steps:** leave `ApiKey=""` and attach the EA to an allowed symbol.
- **Expected result:** `INIT_FAILED`, Journal message
  `"ApiKey is empty -- refusing to run."`
- **Pass criteria:** EA does not attach.
- **Fail criteria:** EA attaches and begins sending requests with an
  empty key (which the server should separately reject as
  `MISSING_API_KEY`/401 — see test N1 — but the EA is expected to
  never even try).
- **Recovery behavior:** set a real key and reattach.

### A4. `OnTick()`

- **Purpose:** confirm ticks are received; note this handler has no
  externally observable side effect by design (it only updates the
  internal `g_lastTickAt` timestamp, which is not currently read
  anywhere else in the file — this is a harmless dead-state variable,
  not a functional defect, and does not require a code change under
  this package's rules).
- **Steps:** watch the chart during active market hours with the EA
  attached.
- **Expected result:** no crash, no Journal errors, ticks visibly
  moving the chart.
- **Pass criteria:** EA remains attached (no `OnDeinit` triggered) for
  the duration of tick activity.
- **Fail criteria:** EA detaches or the terminal reports an error
  attributable to `OnTick()`.
- **Recovery behavior:** none needed; if it detaches, treat as a
  crash and capture the Experts log before reattaching.

### A5. `OnTimer()` — heartbeat/telemetry cadence

- **Purpose:** confirm the 1-second timer (`EventSetTimer(1)`) drives
  heartbeat/account/position/order sends at the configured
  `HeartbeatIntervalSeconds` cadence, and command polling on every
  timer tick when not fail-closed.
- **Steps:** set `HeartbeatIntervalSeconds=5`; observe the bridge
  server's logs or the network capture for five minutes.
- **Expected result:** a heartbeat/account/positions/orders POST burst
  roughly every 5 seconds; a poll (`GET /bridge/commands/poll`) on
  every timer firing (approximately once per second) as long as
  `IsFailClosed()` is false.
- **Pass criteria:** cadence matches `HeartbeatIntervalSeconds` within
  normal network jitter; polling frequency matches the 1-second timer.
- **Fail criteria:** no telemetry sent at all, or cadence drifts far
  outside the configured interval.
- **Recovery behavior:** none needed if timing is within tolerance;
  otherwise capture logs and treat as a defect for the compile/demo
  gate, not a code change made speculatively.

### A6. `OnTradeTransaction()`

- **Purpose:** confirm the independent MT5-native trade-event mirror
  fires and is sent to `/bridge/trade-transaction`, separate from the
  EA's own `ExecutionReport` for the same trade.
- **Steps:** execute any trade (manually from the terminal, or via a
  BUY command per test T1) and watch for a
  `POST /bridge/trade-transaction` call in the network capture.
- **Expected result:** exactly one `SendTradeTransaction` call per
  native trade transaction event MT5 delivers (MT5 may deliver more
  than one transaction per trade — e.g. `DEAL_ADD` and `ORDER_ADD` —
  each should produce its own mirror send).
- **Pass criteria:** bridge server logs show
  `matched_known_execution: true` when the transaction corresponds to
  a command this EA itself just executed (server-side drift-detection
  cross-check, per `BridgeEngine.handle_trade_transaction`).
- **Fail criteria:** no mirror sent, or a crash inside
  `OnTradeTransaction()`.
- **Recovery behavior:** none required; this handler never blocks or
  alters the trade itself.

### A7. Heartbeat

- **Purpose:** confirm `SendHeartbeat()` keeps
  `g_lastSuccessfulContact` current so the fail-closed check never
  trips during normal operation.
- **Steps:** run the EA continuously for at least
  `2 * FailClosedTimeoutSeconds` (60 seconds at defaults) with the
  bridge server reachable.
- **Expected result:** `POST /bridge/heartbeat` succeeds every
  `HeartbeatIntervalSeconds`; `IsFailClosed()` never returns true.
- **Pass criteria:** command polling continues uninterrupted the whole
  time.
- **Fail criteria:** polling stops despite the server being reachable.
- **Recovery behavior:** none needed on pass.

### A8. API authentication

- **Purpose:** confirm every outbound request carries
  `X-Phantom-Api-Key` and the server enforces it (also see negative
  test N1).
- **Steps:** inspect the network capture headers on any outbound
  `HttpPost`/`HttpGet` call.
- **Expected result:** `X-Phantom-Api-Key: <ApiKey>` present on every
  request; server responds 200 for a matching key.
- **Pass criteria:** as above.
- **Fail criteria:** header missing, or present but ignored by the
  server (i.e., a wrong key still returns 200).
- **Recovery behavior:** none needed on pass.

### A9. Secure communication

- **Purpose:** confirm the transport matches what was actually
  deployed — Phase 1 was built and documented as plain HTTP on
  localhost (`BackendUrl` default `http://127.0.0.1:8787`), not TLS.
  This test's job is to record reality, not to assert an HTTPS
  guarantee this component was never built to provide.
- **Steps:** inspect `BackendUrl` and the resulting `WebRequest`
  scheme actually used at runtime.
- **Expected result:** if `BackendUrl` is `http://127.0.0.1:...`
  (loopback), traffic never leaves the machine and TLS is not
  required for the Phase-1 threat model documented in
  `PHANTOM_BRIDGE_EA_PHASE1_REPORT.md`. If the bridge is ever deployed
  across a real network boundary (EA and Python server on different
  hosts), `BackendUrl` must be `https://` and this test must confirm
  MT5's `WebRequest` accepts the certificate (allow-listed under
  **Options -> Expert Advisors**).
- **Pass criteria:** the deployed topology matches one of the two
  above and is documented as such in the sign-off.
- **Fail criteria:** the bridge server and EA communicate across a
  real network boundary over plain HTTP — flag this as a finding, not
  something to silently accept.
- **Recovery behavior:** if failing, this is a deployment-configuration
  fix (use loopback, or add TLS in front of the bridge), not a
  `PhantomBridgeEA.mq5` code change.

### A10. Connection recovery

- **Purpose:** confirm the EA resumes normal operation automatically
  once the bridge server becomes reachable again after an outage,
  with no manual restart of the EA required.
- **Steps:** stop the bridge server process; wait past
  `FailClosedTimeoutSeconds`; confirm the EA has failed closed (test
  A11); restart the bridge server; wait up to
  `HeartbeatIntervalSeconds + one timer tick`.
- **Expected result:** the next successful `HttpPost`/`HttpGet` call
  updates `g_lastSuccessfulContact`, `IsFailClosed()` returns false
  again, and command polling resumes without reattaching the EA.
- **Pass criteria:** polling and telemetry resume automatically.
- **Fail criteria:** the EA remains fail-closed after the server is
  back up and reachable, or requires manual reattachment to recover.
- **Recovery behavior:** this test *is* the recovery-behavior
  verification; there is no further action needed if it passes.

### A11. Fail-closed timeout

- **Purpose:** confirm `IsFailClosed()` correctly halts polling (and
  therefore all new execution) when no successful contact has
  occurred within `FailClosedTimeoutSeconds`.
- **Steps:** block the bridge server's port (stop the process, or
  firewall it) and wait longer than `FailClosedTimeoutSeconds`
  (30s default) past the last successful contact.
- **Expected result:** `OnTimer()`'s `if(!IsFailClosed())
  PollAndExecuteCommands();` guard stops firing; no
  `GET /bridge/commands/poll` calls occur while blocked. Heartbeat/
  telemetry sends still attempt (and fail) every
  `HeartbeatIntervalSeconds`, since only polling — not telemetry
  sending — is gated by `IsFailClosed()`.
- **Pass criteria:** zero poll calls (and therefore zero new trade
  execution) during the blocked window.
- **Fail criteria:** any command is executed while fail-closed.
- **Recovery behavior:** see A10 — recovery is automatic once contact
  is restored.

### A12. Emergency stop

- **Purpose:** confirm `POST /bridge/emergency-stop {"active": true}`
  halts new command issuance and is surfaced to the EA on its next
  poll, and that `EmergencyDisable=true` (the EA-local manual kill
  switch) independently halts all telemetry/polling/execution even if
  the server-side flag is off.
- **Steps (server-side path):** with a command in flight or queued,
  call the emergency-stop endpoint with `active: true`; observe the
  next `GET /bridge/commands/poll` response.
- **Expected result:** poll response has `"emergency_stop": true` and
  an empty `"commands": []` array (`CommandQueue.poll` empties on
  emergency stop per `phantom/bridge/command_queue.py`); the EA
  executes nothing further until deactivated.
- **Steps (EA-local path):** set input `EmergencyDisable=true` on a
  running EA (requires reattaching with the new input value, since
  MQL5 inputs are not runtime-mutable) and observe `OnTimer()`.
- **Expected result:** `OnTimer()` returns immediately
  (`if(EmergencyDisable) return;`) — no heartbeat, no telemetry, no
  polling at all, independent of server state.
- **Pass criteria:** both paths independently stop all further command
  execution; deactivating the server-side flag
  (`active: false`) resumes normal poll behavior without reattaching
  the EA.
- **Fail criteria:** any command executes after either kill switch is
  engaged.
- **Recovery behavior:** deactivate the server-side flag and/or set
  `EmergencyDisable=false` and reattach; confirm normal operation
  resumes (re-run A7/A5).

---

## B. Trade command tests

Preconditions common to all of B: a demo account with sufficient
margin, the symbol's market open, `AllowedSymbolsCsv` including the
test symbol, and the bridge server able to submit a `TradeCommand` via
its Python-side API (see `phantom/bridge/engine.py`'s
`submit_command`) — this is not exposed as its own HTTP route in
Phase 1; commands are submitted through the Python `BridgeEngine`
object directly. A small Python driver script or an interactive
REPL session calling `engine.submit_command(...)` against the running
server's `BridgeEngine` instance is the expected way to inject test
commands for B and the trade-related items of C.

### T1. BUY

- **Purpose:** confirm a full BUY round-trip: submit -> poll -> execute
  -> report, with pre-flight checks passing and the correct filled
  volume reported.
- **Steps:** submit a `BUY` `TradeCommand` for the test symbol with a
  valid volume, `stop_loss`/`take_profit` at a legal distance; wait for
  the EA's next poll cycle.
- **Expected result:** `ExecuteBuy` passes `CheckTradingPreconditions`,
  `CheckVolumeValid`, `CheckStopsValid`; `g_trade.Buy(...)` succeeds;
  `ReportExecutionResult` is sent with `success:true`,
  `broker_ticket` = the new position's ticket, `filled_price` =
  `g_trade.ResultPrice()`, `filled_volume` = `g_trade.ResultVolume()`.
- **Pass criteria:** a new position appears on the account with the
  requested (or broker-adjusted) volume; the bridge server's recorded
  `ExecutionReport.filled_volume` matches the position's actual
  volume, not merely the requested volume.
- **Fail criteria:** no position opened, or `filled_volume` in the
  report does not match the real position volume.
- **Recovery behavior:** on failure, the `error_code` field carries
  either a named precondition failure (e.g. `SYMBOL_NOT_ALLOWED`) or a
  raw MT5 retcode string; use it to classify the failure per section C.

### T2. SELL

- **Purpose/Steps/Expected/Pass/Fail/Recovery:** identical to T1 with
  `ExecuteSell`/`g_trade.Sell(...)`, `isBuy=false` for stop validation
  (`CheckStopsValid(symbol, false, ...)`), and reference price
  `SYMBOL_BID` instead of `SYMBOL_ASK`.

### T3. MODIFY_SL

- **Purpose:** confirm an existing owned position's stop loss can be
  changed without touching its take profit, respecting the minimum
  stop distance.
- **Steps:** open a position (T1/T2), then submit `MODIFY_SL` with a
  new stop-loss price at a legal distance from the current market
  price.
- **Expected result:** `ExecuteModifySL` re-selects the position by
  ticket (`SelectOwnedPosition`), confirms magic-number ownership,
  validates the new SL via `CheckStopsValid(symbol, isBuy, newSl,
  0.0)`, calls `g_trade.PositionModify(ticket, newSl, currentTp)`
  (take profit unchanged), reports success with the ticket and no
  price/volume (`0, 0`, since this command has no fill concept).
- **Pass criteria:** the position's stop loss updates on the terminal;
  take profit is unchanged; `ReportExecutionResult` shows
  `success:true`.
- **Fail criteria:** take profit is altered, wrong position modified,
  or the SL fails validation for a distance that is actually legal.
- **Recovery behavior:** error path reports `STOP_LOSS_TOO_CLOSE` or a
  raw retcode; correct the submitted price and resubmit.

### T4. MODIFY_TP

- **Purpose/Steps/Expected/Pass/Fail/Recovery:** mirror of T3 via
  `ExecuteModifyTP`, validating only the new take profit
  (`CheckStopsValid(symbol, isBuy, 0.0, newTp)`) and preserving the
  current stop loss.

### T5. CLOSE

- **Purpose:** confirm a full-position close reports the real fill
  price/volume from `CTrade`, not a placeholder.
- **Steps:** open a position, then submit `CLOSE` for its
  `position_id`.
- **Expected result:** `ExecuteClose` re-verifies ownership, runs
  `CheckTradingPreconditions(symbol, false)` (close-only mode must
  still permit this), calls
  `g_trade.PositionClose(ticket, (ulong)MaxSlippagePoints)`, reports
  `filled_price`/`filled_volume` from `g_trade.ResultPrice()` /
  `g_trade.ResultVolume()`.
- **Pass criteria:** the position disappears from the account; the
  reported volume matches the position's full size at close time.
- **Fail criteria:** position remains open after a `success:true`
  report (a correctness bug, not merely a rejection), or reported
  volume is the wrong value.
- **Recovery behavior:** error path reports
  `UNKNOWN_OR_FOREIGN_POSITION` or a raw retcode; verify the
  `position_id` and retry.

### T6. PARTIAL_CLOSE

- **Purpose:** confirm partial-close volume is bounds-checked
  (`0 < closeVolume < ownedVolume`) and the real closed volume is
  reported.
- **Steps:** open a position with volume >= 2x the symbol's minimum
  lot step; submit `PARTIAL_CLOSE` with `close_volume` less than the
  full position size and step-aligned.
- **Expected result:** `ExecutePartialClose` rejects
  `close_volume <= 0` or `>= ownedVolume` up front with
  `INVALID_PARTIAL_CLOSE_VOLUME`; otherwise runs preconditions +
  `CheckVolumeValid`, calls
  `g_trade.PositionClosePartial(ticket, closeVolume,
  (ulong)MaxSlippagePoints)`, reports the real filled price/volume.
- **Pass criteria:** the remaining position volume equals
  `ownedVolume - closeVolume` (broker rounding aside); the report's
  `filled_volume` matches the actually-closed amount.
- **Fail criteria:** full position closed instead of partial, or
  reported volume does not match what was actually closed.
- **Recovery behavior:** error path reports
  `INVALID_PARTIAL_CLOSE_VOLUME`, a volume-precondition code, or a raw
  retcode; adjust `close_volume` and retry.

---

## C. Negative / adversarial tests

### N1. Invalid API key

- **Purpose:** confirm the server rejects a wrong or missing key
  before doing anything else (validate-before-acknowledge).
- **Steps:** send any request (e.g. heartbeat) with a wrong
  `X-Phantom-Api-Key`, then with the header omitted entirely.
- **Expected result:** HTTP 401 with `{"error": "INVALID_API_KEY"}`
  or `{"error": "MISSING_API_KEY"}` per
  `phantom/bridge/validation.py`'s `check_api_key`; no state changes
  on the server (no heartbeat recorded, no command queued/altered).
- **Pass criteria:** 401 in both cases; server state unchanged.
- **Fail criteria:** 200, or any state mutation despite the rejection.
- **Recovery behavior:** none needed server-side — this is by design.
  On the EA side, confirm it does **not** crash or infinite-loop
  retrying an auth failure (a real HTTP response, so `HttpPost`
  returns immediately per its "status > 0: do not retry" branch).

### N2. Invalid JSON

- **Purpose:** confirm malformed request bodies are rejected cleanly.
- **Steps:** POST a non-JSON or truncated body to any route (e.g. via
  `curl` directly at the bridge server, bypassing the EA).
- **Expected result:** HTTP 400 `{"error": "invalid_json_body"}` (see
  `phantom/bridge/server.py`'s `do_POST`); or 400
  `{"error": "json_object_required"}` if the body parses but is not a
  JSON object (e.g. a bare array or string).
- **Pass criteria:** 400 in both cases, no crash, no partial state
  change.
- **Fail criteria:** a 500 error, a hang, or a state change despite
  the malformed body.
- **Recovery behavior:** none needed — this is the server functioning
  correctly. Confirm no exception traceback leaks internal detail to
  the caller beyond the generic message.

### N3. Invalid symbol

- **Purpose:** confirm a command for a symbol outside the allowlist,
  or one MT5 cannot select, is rejected without ever reaching
  `CTrade`.
- **Steps:** submit a `BUY`/`SELL` command for a symbol not in
  `AllowedSymbolsCsv`; separately, submit one for a syntactically
  plausible but nonexistent symbol (e.g. `"ZZZUSD"`).
- **Expected result:** `ExecuteBuy`/`ExecuteSell`'s
  `if(!IsSymbolAllowed(symbol))` check reports
  `SYMBOL_NOT_ALLOWED` immediately for the first case. For the second
  case, `CheckTradingPreconditions`'s `SymbolSelect(symbol, true)`
  call fails, reporting `SYMBOL_NOT_AVAILABLE` — note this second
  case only fires if the nonexistent symbol also happens to be listed
  in `AllowedSymbolsCsv`, since the allowlist check runs first.
- **Pass criteria:** no `CTrade` call is ever attempted in either case
  (verify no MT5-side order ticket is created); `error_code` correctly
  distinguishes the two cases.
- **Fail criteria:** any execution attempt against a disallowed or
  nonexistent symbol.
- **Recovery behavior:** none — correct behavior is rejection.

### N4. Invalid volume

- **Purpose:** confirm volume outside `SYMBOL_VOLUME_MIN`/`MAX`/`STEP`
  is rejected before execution.
- **Steps:** submit `BUY` with volume below `SYMBOL_VOLUME_MIN`, above
  `SYMBOL_VOLUME_MAX`, and at a value not aligned to
  `SYMBOL_VOLUME_STEP` (e.g. `0.013` lots on a `0.01`-step symbol
  where that is off-grid for the pair's actual step).
- **Expected result:** `CheckVolumeValid` reports
  `VOLUME_BELOW_MIN`, `VOLUME_ABOVE_MAX`, or
  `VOLUME_NOT_STEP_ALIGNED` respectively, before any `CTrade` call.
- **Pass criteria:** all three rejected with the correct named reason;
  no order ticket created.
- **Fail criteria:** any of the three reaches `CTrade`.
- **Recovery behavior:** none — correct behavior is rejection.
  Separately, the Python-side `validation.check_volume` should also
  reject an out-of-bounds volume against `BridgeConfig.max_lot_size`
  at submission time — confirm both layers reject independently
  (defense in depth), not just one.

### N5. Market closed

- **Purpose:** confirm the EA detects no-quotes conditions and refuses
  to attempt execution, distinct from a broker-side rejection.
- **Steps:** submit a `BUY`/`SELL`/modify/close command for a symbol
  while its market session is closed (e.g. over a weekend, or a
  symbol with no active session at test time).
- **Expected result:** `CheckTradingPreconditions`'s
  `bid <= 0.0 || ask <= 0.0` check reports
  `MARKET_CLOSED_OR_NO_QUOTES` before any `CTrade` call.
- **Pass criteria:** rejection with that exact reason string; no
  execution attempt.
- **Fail criteria:** execution attempted with stale/zero quotes.
- **Recovery behavior:** none — resubmit once the market reopens.

### N6. Duplicate execution_id (duplicate `correlation_id`)

- **Purpose:** confirm the same command is never executed twice and
  the same execution result is never double-recorded, even under
  retry or resend.
- **Steps:** submit one `TradeCommand`; let it execute; then attempt
  to submit another command reusing the same `correlation_id`.
  Separately, POST the exact same `/bridge/execution/report` body
  twice.
- **Expected result:** `CommandQueue.enqueue` rejects the duplicate
  submission (`DUPLICATE_CORRELATION_ID`, per
  `phantom/bridge/command_queue.py`); a repeated execution report for
  a `correlation_id` already recorded returns `recorded: false`
  without altering the stored result (see
  `TestDuplicateExecutionReportNotRecordedTwice` in
  `tests/phantom/bridge/test_http_server.py`).
- **Pass criteria:** exactly one execution occurs and exactly one
  result is ever stored per `correlation_id`, regardless of resend
  count.
- **Fail criteria:** a second execution occurs, or a second report
  overwrites the first.
- **Recovery behavior:** none — this is the idempotency guarantee
  functioning correctly. This also indirectly re-confirms Fix #4 from
  `PHANTOM_BRIDGE_EA_PHASE1_FIX_REPORT.md`: internal requote retries
  inside one `Execute*` call must never produce more than one
  `ReportExecutionResult` call for that command's `correlation_id`.

### N7. Lost bridge connection

- **Purpose:** confirm behavior when the bridge server process is
  killed mid-session (distinct from N9's slower heartbeat-timeout
  path — this is an abrupt connection loss).
- **Steps:** kill the bridge server process outright while the EA is
  running; observe the next several `HttpPost`/`HttpGet` attempts.
- **Expected result:** `WebRequest` returns a non-2xx/negative status;
  `HttpPost`/`HttpGet`'s bounded retry loop (`MaxRetries` attempts,
  `RetryDelayMs` apart) exhausts and returns `""`; no exception, no
  crash, no partial JSON write. `g_lastSuccessfulContact` stops
  advancing, leading into the fail-closed path (A11) once
  `FailClosedTimeoutSeconds` elapses.
- **Pass criteria:** EA keeps running (no detach), retries bounded
  (observe exactly `MaxRetries` attempts per call, not unbounded),
  eventually fails closed.
- **Fail criteria:** EA crashes/detaches, or retries unboundedly, or
  never fails closed despite the outage.
- **Recovery behavior:** restart the bridge server; confirm A10
  (automatic connection recovery) holds.

### N8. Heartbeat timeout

- **Purpose:** confirm the fail-closed timer is driven by
  *successful* contact, not merely by attempts, and trips correctly
  when heartbeats stop landing.
- **Steps:** simulate a server that accepts TCP connections but never
  responds (or responds slowly enough to exceed the 5000ms
  `WebRequest` timeout) for longer than `FailClosedTimeoutSeconds`.
- **Expected result:** identical mechanism to A11/N7 —
  `g_lastSuccessfulContact` stalls, `IsFailClosed()` trips after
  `FailClosedTimeoutSeconds`.
- **Pass criteria:** polling halts within one timer tick of the
  threshold being crossed.
- **Fail criteria:** polling continues past the configured timeout.
- **Recovery behavior:** see A10.

### N9. Broker rejection

- **Purpose:** confirm a hard broker-side rejection (not a requote) is
  reported as a clean failure with the broker's real retcode, and is
  never retried (retries are scoped to requote/price-changed only).
- **Steps:** trigger a rejection MT5 will not requote for — e.g.
  insufficient margin (`TRADE_RETCODE_NO_MONEY`, 10019) by requesting
  a volume larger than the account can support.
- **Expected result:** `IsRequoteRetcode(retcode)` returns false for
  10019, so the attempt loop breaks immediately (no retry);
  `ReportExecutionResult` sends `success:false`,
  `error_code: "10019"`.
- **Pass criteria:** exactly one attempt made, correct retcode
  reported.
- **Fail criteria:** the EA retries a non-requote rejection, or
  reports the wrong retcode.
- **Recovery behavior:** none — resubmit with a viable volume/margin.

### N10. Trade context busy

- **Purpose:** confirm behavior under MT5's equivalent of the
  MQL4-era "trade context busy" condition. **Note for the operator:**
  MQL5's `CTrade`/`OrderSend` model does not have a direct
  "context busy" return value the way MQL4 did — the closest
  practical equivalents to test are `TRADE_RETCODE_LOCKED` (10028,
  trade request locked for processing) and
  `TRADE_RETCODE_TOO_MANY_REQUESTS` (10024). Confirm which one the
  target broker actually surfaces under contention before treating
  this test as failed for the wrong reason.
- **Steps:** fire two commands for the same account in rapid
  succession from two separate EA instances/charts, or from two
  concurrent test-driver submissions, to try to trigger a locked
  trade context.
- **Expected result:** if the broker returns 10028/10024,
  `IsRequoteRetcode` correctly does **not** treat it as a requote (so
  no retry loop consumes `MaxRequoteRetries` on it); it is reported as
  a clean failure with that retcode.
- **Pass criteria:** reported retcode matches what the broker actually
  returned; no silent retry loop masks the condition.
- **Fail criteria:** the command silently succeeds against a different
  account's context, or the retcode is misreported.
- **Recovery behavior:** resubmit once the concurrent request clears.

### N11. Requote

- **Purpose:** confirm the bounded requote-retry logic (Fix #4) works
  under a real, broker-generated requote — this is the one negative
  test that most needs a live demo, since a requote's timing depends
  on real market volatility and cannot be reliably forced.
- **Steps:** submit a BUY/SELL during a fast-moving market (news
  release on a demo account with realistic spread/requote behavior),
  or use a broker/demo environment known to simulate requotes on
  stale-price submissions.
- **Expected result:** on `TRADE_RETCODE_REQUOTE` (10004) or
  `TRADE_RETCODE_PRICE_CHANGED` (10020), the loop in `ExecuteBuy`/
  `ExecuteSell`/etc. sleeps `RequoteRetryDelayMs` and retries, up to
  `MaxRequoteRetries` additional attempts, then reports whatever the
  final attempt's outcome was. Exactly one `ReportExecutionResult`
  call fires regardless of how many internal attempts occurred.
- **Pass criteria:** at most `MaxRequoteRetries + 1` total `CTrade`
  calls for the one command; exactly one execution report sent;
  successful retry produces a `success:true` report with the
  eventually-filled price/volume.
- **Fail criteria:** more than one execution report sent for the same
  `correlation_id`, or the retry loop does not bound at
  `MaxRequoteRetries`, or a requote is misclassified and not retried.
- **Recovery behavior:** if all attempts exhaust on requotes,
  `ReportExecutionResult` reports `success:false` with the last
  retcode (`"10004"` or `"10020"`); resubmit the command fresh with a
  new `correlation_id` if still desired.

### N12. Partial fill

- **Purpose:** confirm `filled_volume` correctly reflects a genuine
  partial fill rather than the requested volume (this is Fix #2 from
  the fix report, being re-verified live).
- **Steps:** submit a BUY/SELL for a volume large enough that the
  demo/broker's liquidity simulation fills only part of it (broker/
  demo-dependent — not all demo servers simulate partial fills;
  document if the test environment cannot produce one).
- **Expected result:** `g_trade.ResultVolume()` returns less than the
  requested volume; `ReportExecutionResult`'s `filled_volume` carries
  that lesser value, not the original request.
- **Pass criteria:** reported `filled_volume` matches the position's
  actual opened volume exactly.
- **Fail criteria:** reported `filled_volume` equals the requested
  volume despite an actual partial fill (this would be a regression of
  the exact bug Fix #2 addressed).
- **Recovery behavior:** none — a partial fill is a valid outcome, not
  an error; `success:true` is still correct.

### N13. Network interruption

- **Purpose:** confirm graceful handling of a transient network drop
  shorter than `FailClosedTimeoutSeconds` — the recoverable case, as
  opposed to N7's sustained outage.
- **Steps:** disconnect the network interface (or use a proxy to drop
  packets) for a duration shorter than `FailClosedTimeoutSeconds`,
  then restore it.
- **Expected result:** in-flight `HttpPost`/`HttpGet` calls fail and
  retry per `MaxRetries`/`RetryDelayMs`; once connectivity returns
  within the fail-closed window, the next successful call updates
  `g_lastSuccessfulContact` and `IsFailClosed()` never trips.
- **Pass criteria:** no fail-closed halt occurs if the interruption is
  shorter than the configured timeout; normal operation resumes with
  no manual intervention.
- **Fail criteria:** the EA fails closed despite the outage being
  shorter than the configured threshold, or fails to recover once
  connectivity returns.
- **Recovery behavior:** none needed if within tolerance; see A10 for
  the longer-outage path.
