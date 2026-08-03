# Phantom Bridge EA — Phase 1 Final Verification Audit

**No code was modified to produce this report.** Everything below is
either (a) executed and observed directly against the actual Python
bridge code, or (b) manual, line-by-line code review of the MQL5 EA
(this sandbox has no MetaEditor/MT5 terminal — disclosed explicitly
everywhere it applies, not glossed over).

**Headline finding: `mt5/PhantomBridgeEA.mq5` will not currently
compile.** A confirmed type-mismatch error exists at line 122. This is
fatal — MQL5 requires the whole file to compile to produce an `.ex5`,
so nothing EA-side has ever actually run. Full detail in §1.

---

## 1. Does `PhantomBridgeEA.mq5` compile cleanly in MetaEditor?

**No.** One confirmed compile-blocking error, found by manual review
and independently confirmed by a corrected structural tokenizer I built
specifically for this audit (see methodology note below).

### Compile error #1 (confirmed, fatal)

**Location:** `mt5/PhantomBridgeEA.mq5:122`

```mql5
StringTrimLeft(StringTrimRight(g_allowedSymbols[i]));
```

**Why this fails:** MQL5's `StringTrimLeft`/`StringTrimRight` signatures
are:
```
int StringTrimLeft(string& str);
int StringTrimRight(string& str);
```
Both **modify `str` in place by reference and return `int`** (the
character count removed) — they do not return a string. The inner call
`StringTrimRight(g_allowedSymbols[i])` evaluates to an `int`. Passing
that `int` as the argument to `StringTrimLeft(...)`, which requires a
`string&` parameter, is a type mismatch the compiler will reject. This
line must instead be two separate statements:
```mql5
StringTrimLeft(g_allowedSymbols[i]);
StringTrimRight(g_allowedSymbols[i]);
```
(Not applied — audit only, per your instruction.)

### Everything else checked and found clean

- **Brace/parenthesis/bracket balance**: verified via a purpose-built
  tokenizer that correctly tracks MQL5 double-quoted strings, single-
  quoted character literals (e.g. `']'`, `'{'`), and both comment
  styles. Result: **0/0/0 — fully balanced.** (My first attempt at this
  check used a naive regex that didn't account for single-quoted
  character literals like `StringGetCharacter(json, pos) == ']'` and
  produced false "unbalanced bracket" warnings — rebuilt it properly
  and reconfirmed. Flagging this so the false-positive is on record and
  not confused with a real finding.)
- **`StringFormat` call correctness**: all 9 `StringFormat` calls in the
  file checked programmatically — every format specifier (`%s`, `%d`,
  `%.2f`, `%.5f`, `%I64u`) count matches the argument count exactly.
  No mismatches found.
- **API signatures used**, checked against documented MQL5 semantics:
  `CTrade::Buy/Sell/PositionModify/PositionClose/PositionClosePartial/
  ResultOrder/ResultPrice/ResultRetcode`, `PositionGetTicket/
  PositionSelectByTicket/PositionGetInteger/PositionGetDouble/
  PositionGetString`, `OrderGetTicket/OrderSelect/OrderGetInteger/
  OrderGetDouble/OrderGetString`, `AccountInfoDouble/Integer/String`,
  `TerminalInfoInteger`, `WebRequest` (7-arg `uchar[]` form),
  `StringToCharArray/CharArrayToString`, `MqlTradeTransaction`/
  `MqlTradeResult` field access (`trans.symbol`, `trans.deal`,
  `trans.order`, `trans.type`, `result.volume`, `result.price`) — all
  match real, documented signatures. `OnTradeTransaction`'s handler
  signature matches the required event-handler form exactly.
- One low-confidence, non-blocking style note: `g_trade.SetDeviationInPoints(MaxSlippagePoints)`,
  `PositionClose(ticket, MaxSlippagePoints)`, `PositionClosePartial(ticket, closeVolume, MaxSlippagePoints)`
  pass an `int` input where a `ulong deviation` parameter is expected.
  This is an extremely common, normally-silent implicit widening
  conversion in real-world MQL5 code — I do **not** believe this blocks
  compilation, but I cannot verify with 100% certainty without a real
  compiler, so I'm disclosing it rather than asserting either way.

**Methodology note:** I do not have MetaEditor in this sandbox. The
above is the most rigorous manual-review substitute achievable —
systematic, line-by-line, cross-referenced against real MQL5 API
signatures, with programmatic checks (brace balance, format-specifier
counts) built specifically for this audit rather than asserted from
memory. It is not a substitute for an actual compile pass, which
**must** happen in real MetaEditor before this EA is used for anything.

---

## 2. Verify every HTTP endpoint

All 9 endpoints **executed** against the real `phantom.bridge.server`
code over a live socket (not just code-read):

| Endpoint | Verified |
|---|---|
| `POST /bridge/heartbeat` | ✅ accepts valid, rejects wrong API key (401), rejects wrong magic number (400) |
| `POST /bridge/account` | ✅ accepts valid, stores latest state; rejects missing required field (400) |
| `POST /bridge/positions` | ✅ accepts valid, count reflects submitted array |
| `POST /bridge/orders` | ✅ accepts valid, count reflects submitted array (including empty) |
| `GET /bridge/commands/poll` | ✅ returns empty array when nothing queued; returns queued command after submission; rejects missing API key (401); reflects emergency-stop flag |
| `POST /bridge/execution/report` | ✅ records first report, rejects duplicate (idempotent) |
| `POST /bridge/trade-transaction` | ✅ accepts valid; correctly reports `matched_known_execution` |
| `POST /bridge/error` | ✅ accepts valid, stored and retrievable via `engine.errors` |
| `POST /bridge/emergency-stop` | ✅ activate/deactivate both work, requires API key, immediately reflected in the next poll |
| Unknown path | ✅ 404 |
| Malformed JSON body | ✅ 400 |
| JSON array instead of object | ✅ 400 |

## 3. Verify every trade command

**Python-side command lifecycle — executed and confirmed for all six:**
`BUY`, `SELL`, `MODIFY_SL`, `MODIFY_TP`, `CLOSE`, `PARTIAL_CLOSE` are
all submittable, validated identically (symbol/volume/SL-TP/timestamp),
enqueue/poll/report correctly for every kind — confirmed via a loop
submitting one of each `CommandKind` and asserting acceptance.

**EA-side execution — code-reviewed only, cannot be executed without
MT5. One confirmed defect found:**

- **`ExecuteBuy`/`ExecuteSell`** (lines ~438-475): report
  `filled_volume` using the **requested** `volume` parameter, not
  `g_trade.ResultVolume()` (the actual broker-filled volume `CTrade`
  provides). **On a genuine partial fill, this misreports the fill as
  fully executed at the requested size.**
- **`ExecuteClose`** (lines ~508-522): reports `filled_volume` using
  the position's volume **captured before the close attempt**, not
  `g_trade.ResultVolume()`. Same misreporting risk if the closing order
  itself partially fills.
- **`ExecutePartialClose`** (lines ~524-543): reports `filled_volume`
  using the **requested** `closeVolume`, not `g_trade.ResultVolume()`.
  Same risk.
- **`ExecuteModifySL`/`ExecuteModifyTP`**: no volume concept involved —
  not affected.
- **Magic-number ownership check**: confirmed by code review that
  `SelectOwnedPosition()` is called at the top of every one of
  `ExecuteModifySL`/`ExecuteModifyTP`/`ExecuteClose`/`ExecutePartialClose`
  before any `CTrade` call — a position not owned by this EA's magic
  number is never touched by any of the four operations that act on an
  existing position. (Unlike the audited `dwx-zeromq-connector`
  reference, which enforces this for selective close but not for its
  bulk-close/list-all operations — this EA has no unscoped bulk
  operation at all in Phase 1.)

## 4. Verify the named safety/security mechanisms

| Mechanism | Verified how | Result |
|---|---|---|
| Fail-closed timeout | Executed: heartbeat recorded, clock advanced past `heartbeat_timeout_seconds`, `submit_command()` correctly rejected with `BRIDGE_NOT_READY` | ✅ confirmed server-side. EA-side `IsFailClosed()` logic reviewed and is structurally sound (code review only) |
| API-key authentication | Executed: wrong key → 401 `INVALID_API_KEY`; missing key → 401 `MISSING_API_KEY`; correct key → accepted. Uses `hmac.compare_digest` (timing-safe) | ✅ confirmed |
| Correlation IDs | Executed: submitted command's `correlation_id` round-trips through poll and execution-report exactly | ✅ confirmed |
| Idempotency | Executed: duplicate `correlation_id` submission rejected (`DUPLICATE_CORRELATION_ID`); duplicate execution report for a terminal command is a no-op and the **original** result is never overwritten (confirmed by attempting to overwrite a successful report with a "tampered" failing one — original survived) | ✅ confirmed |
| Heartbeat | Executed via HTTP and object-level API | ✅ confirmed |
| Emergency stop | Executed: activation blocks new enqueue and clears pending backlog immediately; poll reflects the flag; requires API key | ✅ confirmed |
| Magic-number isolation | Server-side: executed (rejects mismatched magic number on every route). EA-side: code-reviewed, confirmed present on all 4 position-affecting operations, absent from BUY/SELL by nature (no existing position to check) | ✅ confirmed both sides |
| `OnTradeTransaction` mirroring | Executed at the engine level: a mirror report matching a known execution's broker ticket returns `matched=True`; a mirror report with an unknown ticket returns `matched=False` and increments a drift counter; a mirror with `deal_ticket=None` (e.g. an account-level transaction) is never flagged as drift | ✅ confirmed. EA-side `OnTradeTransaction()` handler itself (whether MT5 actually calls it with the fields I assumed) is code-reviewed only |

## 5. Attempt to break the bridge — results

Executed as real adversarial HTTP/object-level tests against the live
Python server and engine (not simulated in prose):

| Attack | Result |
|---|---|
| Duplicate commands (same `correlation_id`, different content) | Second submission rejected `DUPLICATE_CORRELATION_ID`; first command's content is what survives |
| Invalid API key | 401, correct error code, no state change |
| Timeout (clock advanced past command TTL between enqueue and poll) | Command silently dropped by `poll()`, never delivered |
| Lost heartbeat | `submit_command()` correctly refuses with `BRIDGE_NOT_READY` once the heartbeat timeout elapses |
| Invalid JSON (`{not valid json!!!`) | 400 `invalid_json_body` |
| JSON array instead of object (`[1,2,3]`) | 400 `json_object_required` |
| Malformed field type (`"balance": "not-a-number"`) | 400, caught as `invalid_payload` — no partial state applied |
| Network interruption (simulated as EA not polling for a long window) | Pending command silently expires past its TTL — never delivered stale |
| Emergency stop mid-flight | Immediately empties the pending backlog and blocks new submissions |
| Invalid symbol | Rejected `SYMBOL_NOT_ALLOWED` before ever reaching the queue |
| Invalid volume (zero, negative, over-max) | All three rejected with the correct distinct reason (`INVALID_VOLUME` ×2, `VOLUME_EXCEEDS_MAX`) |
| Partial fills | **Not testable without MT5. Code review found a real bug** — see §3. `filled_volume` is misreported on BUY/SELL/CLOSE/PARTIAL_CLOSE if MT5 only partially fills the order. |
| Broker rejection | Not testable without MT5. Code review: handled generically — any `CTrade` failure reports `IntegerToString(g_trade.ResultRetcode())` as the error code. No rejection-reason-specific handling exists, but nothing is silently swallowed. |
| Requotes | Not testable without MT5. Code review: **no requote-specific retry exists.** A requote (MT5 retcode 10004) is reported once as a generic failure with no automatic re-attempt at an updated price. |
| Trade context busy | Not testable without MT5. Code review: **no pre-flight check exists at all** — no `IsTradeAllowed()`/`AccountInfoInteger(ACCOUNT_TRADE_ALLOWED)`/equivalent gate before any of the six execute functions. Every command goes straight to `CTrade`, relying entirely on `CTrade`'s own return value. This is a real, confirmed gap against a pattern my own prior research (`docs/research/dwx-zeromq-connector-audit.md` §8) explicitly recommended implementing — it was not carried into Phase 1's actual code. |
| Invalid symbol (EA-side redundant check) | Code review: `PollAndExecuteCommands()` does re-check symbol allowlist before dispatch, as designed (defense in depth) |
| Market closed | Not testable without MT5. Code review: same as "broker rejection" — a generic retcode failure, no special handling. |
| Existing position conflicts | **Not a bug — a deliberate scope boundary.** Nothing in Phase 1 prevents two *distinct* commands from opening two positions on the same symbol; deciding "we already have exposure here, don't open another" is a Risk Engine responsibility that doesn't exist yet. Duplicate-*command* execution (the same `correlation_id` twice) **is** prevented; duplicate-*position* prevention across different, independently-valid commands is explicitly out of scope for an execution-only authority. |

## 6. Full failure-mode list

| # | Failure mode | Expected behavior | Actual behavior | Recovery behavior |
|---|---|---|---|---|
| 1 | Python bridge process dies | EA halts new command execution once it can't reach the server | `IsFailClosed()` trips after `FailClosedTimeoutSeconds` (code review; matches the executed server-side equivalent) | Automatic: EA keeps attempting heartbeats; once contact resumes, `g_lastSuccessfulContact` updates and normal operation resumes without restart |
| 2 | EA/terminal goes silent | Server refuses new commands | `ConnectionHealth.is_ready()` → `False`; `submit_command()` returns `BRIDGE_NOT_READY` (executed, confirmed) | Automatic on next heartbeat |
| 3 | Malformed JSON from a client | Request rejected, no state change | 400, confirmed via execution | Client (EA) must resend correctly-formed request |
| 4 | Duplicate execution report (EA retries after a lost ack) | First result is authoritative, second is a no-op | Confirmed via execution: original result unaffected by a tampered duplicate | None needed — this is the correct terminal behavior |
| 5 | Command TTL expires before EA polls | Dropped, never delivered stale | Confirmed via execution | The (future) originating authority would need to detect the missing execution report and resubmit — no automatic re-issuance exists at this layer, by design (Phase 1 has no retry-the-decision authority) |
| 6 | Emergency stop mid-flight | All pending commands cancelled, no new ones accepted | Confirmed via execution | Operator must explicitly deactivate |
| 7 | EA attempts to touch a foreign-magic position | Rejected before any MT5 API call | Code review: `SelectOwnedPosition()` gates all 4 position-affecting operations | N/A — correct rejection is terminal for that command |
| 8 | `WebRequest` fails (DNS/network/not-allowlisted) | Bounded retry, then give up gracefully | Code review: `MaxRetries`/`RetryDelayMs` bounded loop, confirmed no unbounded blocking | Next `OnTimer` cycle retries independently; `IsFailClosed()` eventually trips if this persists |
| 9 | Partial fill on BUY/SELL/CLOSE/PARTIAL_CLOSE | `filled_volume` reflects the true broker-filled amount | **Bug confirmed by code review: reports the requested amount, not `g_trade.ResultVolume()`** | None currently — this needs a code fix, not a runtime recovery path |
| 10 | Requote | Some explicit handling or at minimum a clearly labeled failure | Generic retcode failure, no retry | Would require manual resubmission by a future upstream authority |
| 11 | Trade context busy / trading disabled | Early, clearly-labeled rejection before wasting a round trip | No pre-flight check exists; relies entirely on `CTrade`'s own rejection | Same generic retcode-failure path as any other `CTrade` rejection |
| 12 | Two independent commands open two positions on the same symbol | N/A — this is a Risk Engine decision, not this phase's job | Both would execute if both are individually valid | By design — not a Phase 1 defect |

## 7. Everything that still requires live MT5 testing

1. **Actual compilation in real MetaEditor** — mandatory first step; the
   confirmed error in §1 must be fixed and the file must compile
   cleanly before anything else on this list is meaningful.
2. All six trade-execution functions against a real (demo) account:
   order placement, SL/TP modification, close, partial close — and
   specifically whether `g_trade.ResultVolume()` differs from the
   requested volume under real broker conditions (to confirm/deny the
   §3 finding in practice).
3. `OnTradeTransaction()` actually firing with the expected fields
   populated for each transaction type, and the JSON it builds actually
   parsing correctly server-side end to end.
4. `WebRequest()` actually functioning against a real allow-listed URL
   (this sandbox cannot exercise MQL5's WebRequest allowlist mechanism
   at all).
5. Real requote, trade-context-busy, market-closed, and margin-rejection
   scenarios against a live/demo broker connection.
6. Real partial fills under genuine low-liquidity or ECN/DMA conditions.
7. Multi-symbol behavior if `AllowedSymbolsCsv` lists more than one
   symbol on a single chart-attached EA instance (untested even at the
   design level for Phase 1 — the EA is attached to one chart/symbol
   context per MT5 convention; multi-symbol allowlisting's practical
   behavior needs live confirmation).
8. Timer/tick cadence under real market conditions (whether 1-second-
   granularity `OnTimer` combined with `HeartbeatIntervalSeconds` produces
   the intended telemetry cadence without drift).
9. Behavior under actual terminal restart/reconnect (`TERMINAL_CONNECTED`
   flapping) — only the reporting of that field was reviewable, not its
   real-world triggering.

## 8. Rating: 63 / 100

Broken down, since a single number obscures a genuinely lopsided
result:

- **Python bridge (server, engine, queue, validation, tests):**
  executed, adversarially tested, held up against every attack I could
  run. This half is strong — call it **92/100** on its own.
- **MQL5 EA:** contains one confirmed **fatal** compile error (cannot
  produce an `.ex5` at all as delivered) and one confirmed **real**
  data-integrity bug (partial-fill misreporting on 4 of 6 commands),
  plus a confirmed, known gap (no pre-flight capability check) against
  a pattern my own research explicitly recommended. This half is
  **not currently usable** — call it **35/100**.
- Composite, weighting the EA lower because it is "the single execution
  authority" this phase exists to deliver and it cannot currently run:
  **63/100.**

This is not a vague number — it reflects a system whose transport
design, security posture, and Python-side behavior are genuinely solid
and independently verified, held down by a currently non-functional EA
half that has not been executed even once.

## 9. Every weakness that still exists

**Confirmed, concrete:**
1. Compile-blocking type error at `PhantomBridgeEA.mq5:122` (§1).
2. `filled_volume` misreporting risk on partial fills across BUY, SELL,
   CLOSE, PARTIAL_CLOSE (§3).
3. No pre-flight trading-capability gate before any execution attempt
   (§5, "trade context busy").
4. No requote-specific retry logic (§5).
5. MQL5 side has never been executed even once — every EA-side finding
   in this report is a code-review inference, not an observed result.

**Design-scoped, not bugs (documented boundaries):**
6. No duplicate-*position* prevention across independently-valid
   commands — deliberately deferred to the future Risk Engine.
7. No automatic re-issuance of a command whose execution report never
   arrives — deferred to whatever future authority originates commands.
8. Multi-symbol allowlisting is implemented but has no live-tested
   precedent for how it behaves practically on a single-chart EA
   instance.

**Minor/cosmetic:**
9. `int`→`ulong` implicit conversions passed to three `CTrade` calls —
   very likely harmless, flagged only because I can't verify with 100%
   certainty without a real compiler.

## 10. Recommendation: **Reject as currently delivered.**

Not because the design is wrong — the architecture, security posture,
and Python-side implementation are sound and independently verified
under adversarial testing. But "final verification" cannot pass a
component that **does not compile**, and a data-integrity bug
(mis-reported fill volume) in the one component whose entire job is to
be the trustworthy execution authority is disqualifying on its own,
independent of the compile error.

**Path to approval:** fix the two confirmed defects (§1's
`StringTrimLeft`/`StringTrimRight` type error, §3/§9's `filled_volume`
sourcing), get a clean compile in real MetaEditor, then re-run this
same verification pass against the corrected file plus, ideally, a
real demo-account execution of each of the six commands to close the
§7 gap this sandbox cannot close on its own. No code was changed to
produce this report — these fixes are still pending your instruction.
