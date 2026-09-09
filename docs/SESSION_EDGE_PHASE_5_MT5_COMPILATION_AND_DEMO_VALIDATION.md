# Session Edge — Phase 5: Windows MetaEditor Compilation & MT5 Demo Validation

**Status of this document:** Static compile-readiness review + operator runbook.
**Platform reality:** This repository's CI/development environment is Linux with
**no MetaEditor, no MetaTrader 5 terminal, no MQL5 compiler, no Wine, and no
broker/demo account.** The actual compilation and live demo validation therefore
**cannot be executed here** and have **not** been executed. Every result field in
the matrices below that depends on the real terminal is marked `☐ PENDING
(operator, Windows)` and must be filled in by a human operator running the
procedure on a Windows MT5 installation. Nothing in this document claims that
MetaEditor compilation or MT5 terminal testing has occurred.

This is the deliberate, consistent posture of the whole Session Edge project: the
MQL5 Expert Advisor targets a real terminal and is verified there; on this
platform the **executable Python reference** (`execution_consumer.py`,
`position_manager.py`) plus the **programmable mock MT5** (`mock_mt5.py`) are the
testable proxy, and they are green (105 EA/PM + 45 spec + 44 bridge tests).

---

## 1. Scope of what Phase 5 can and cannot establish here

| Deliverable | Producible on Linux? | This document provides |
|---|---|---|
| Static MQL5 compile-readiness review | ✅ Yes | §3 (completed) |
| Windows MetaEditor compilation | ❌ No terminal | §4 procedure (operator runs) |
| MT5 demo validation matrix | ❌ No terminal | §5 fillable checklist |
| Broker compatibility matrix | ❌ No broker | §6 fillable checklist |
| Position-manager validation | ⚠️ Reference only | §7 (ref green; terminal PENDING) |
| Filesystem-bridge validation | ⚠️ Reference only | §8 (ref green; terminal PENDING) |
| Restart/recovery validation | ⚠️ Reference only | §9 (ref green; terminal PENDING) |
| Performance measurements | ❌ No terminal | §10 fillable |
| Unchanged / no-net / no-AI confirmations | ✅ Yes | §11 (verified) |

---

## 2. Prerequisites (operator, Windows)

1. MetaTrader 5 terminal (build ≥ 3800 recommended), logged in to a **demo**
   account. **Live-money trading is NOT authorized by this phase.**
2. Files placed in the terminal's data folder (open via *File → Open Data Folder*):
   - `MQL5\Experts\SessionEdge\SessionEdgeExecutionEA.mq5`
   - `MQL5\Experts\SessionEdge\JsonBridge.mqh` (same folder as the `.mq5`, so
     the relative `#include "JsonBridge.mqh"` resolves).
3. The bridge tree must exist under `MQL5\Files\session_edge_bridge\` (or the
   terminal *common* `Files` folder if `UseCommonFolder=true`). The strategy
   engine / producer owns and creates this tree — the EA never creates it.
4. *Tools → Options → Expert Advisors*: "Allow automated trading" enabled.
   No URL is added to the WebRequest allow-list — the EA makes no network calls
   (see §11.4).

---

## 3. Static MQL5 compile-readiness review (COMPLETED)

Both files were reviewed line-by-line against the MQL5 language and standard
library. **No hard compile errors were identified.** The EA is written as a
one-to-one mirror of the validated Python reference and uses only documented MQL5
APIs. Findings below are candidate compiler *warnings* to confirm on the real
MetaEditor; none is a behavior change and none is fixed speculatively (editing
accepted, capital-critical source without a compiler to verify against would be
riskier than leaving verified code intact).

### 3.1 API surface — verified present in MQL5

- Trade: `CTrade` (`<Trade\Trade.mqh>`), `.Buy/.Sell/.SetExpertMagicNumber/`
  `.ResultRetcode/.ResultRetcodeDescription/.ResultOrder/.ResultPrice/.ResultVolume`.
- Positions: `PositionsTotal`, `PositionGetTicket`, `PositionGetString`,
  `PositionGetDouble`.
- Symbol/account/terminal: `SymbolSelect`, `SymbolInfoDouble`,
  `AccountInfoInteger`, `TerminalInfoInteger(TERMINAL_CONNECTED)`,
  `TerminalInfoString(TERMINAL_NAME)`, `MQLInfoInteger(MQL_TRADE_ALLOWED)`.
- Files (sandboxed): `FileOpen/Close/Seek/Flush/Size/ReadArray/WriteArray/`
  `IsExist/Move/Delete/FindFirst/FindNext/FindClose`.
- Crypto: `CryptEncode(CRYPT_HASH_SHA256, …)`.
- Time/string: `TimeGMT`, `TimeToStruct`, `StringToTime`, `StringFormat`,
  `StringToCharArray/CharArrayToString` (`CP_UTF8`), `StringGetCharacter`,
  `StringFind/Substr/Replace/Len`, `StringToDouble/StringToInteger`.
- Events: `EventSetTimer/EventKillTimer`, `OnInit/OnDeinit/OnTick/OnTimer`.
- Trade retcodes used (`TRADE_RETCODE_DONE/REQUOTE/REJECT/PRICE_OFF/`
  `PRICE_CHANGED/MARKET_CLOSED/TIMEOUT/TOO_MANY_REQUESTS/INVALID_VOLUME/`
  `INVALID_STOPS/NO_MONEY/CONNECTION/TRADE_DISABLED`) are all predefined MQL5
  constants — no local redefinition needed.

### 3.2 Candidate warnings to confirm at compile time (non-blocking)

| # | Location | Observation | Recommended handling |
|---|---|---|---|
| W1 | `.mq5`/`.mqh` `#property strict` | `strict` is an MQL4 directive; MQL5 is always strict and typically ignores it silently. | If MetaEditor emits "deprecated/ignored", it is safe to delete the line. No behavior effect. Left in place (documents intent). |
| W2 | `WriteAck`/`WriteResult`/`Execute` — `%I64d` with `ulong` ticket values | `%I64d` (signed) is used for some `ulong` values. MQL5 accepts `%I64d`; strictly `%I64u` matches unsigned. Ticket values are small positives, so output is identical. | Confirm no warning. If warned, change those specifiers to `%I64u` — string output unchanged for real ticket ranges. |
| W3 | `OnInit` — `EventSetTimer(MathMax(1, PollSeconds))` | If the resolved `MathMax` overload returns `double`, an implicit `double→int` narrowing warning is possible. | If warned, wrap as `EventSetTimer((int)MathMax(1, PollSeconds))`. Behavior identical. |
| W4 | `Execute` — `g_trade.SetExpertMagicNumber(MagicNumber)` where `MagicNumber` is `input long` | `SetExpertMagicNumber` takes `ulong`; a signed→unsigned conversion warning is possible. | If warned, declare `input ulong MagicNumber` **or** cast `(ulong)MagicNumber`. Value is a positive constant — no behavior change. |

> **Operator rule:** apply a fix from the "Recommended handling" column **only if
> the real compiler actually emits that diagnostic**, keep it minimal, record it
> in §12 "MQL5 compatibility fixes applied", and re-run the reference test suite
> intent check (the fixes above are output-preserving). Do not alter any trade
> logic, validation, dedup, audit, or arithmetic.

### 3.3 Behavior-preserving notes (NOT changes)

- `Recover()` reads `PositionGetDouble(POSITION_PRICE_OPEN/VOLUME)` immediately
  after `BrokerTicketByComment(sid)`; that helper leaves the matched position
  selected, so the reads are correct. If a future refactor moves these apart,
  add an explicit `PositionSelectByTicket(ticket)` first. (No change now.)
- `g_trade.ResultOrder()` records the order ticket in `broker_order_id`;
  ticket↔signal correlation for recovery uses `POSITION_COMMENT`, which is the
  authoritative path. Consistent with the Python reference.

---

## 4. Windows MetaEditor compilation procedure (operator)

1. Open **MetaEditor** (F4 from the terminal, or *Tools → MetaQuotes Language Editor*).
2. In the Navigator, open `Experts\SessionEdge\SessionEdgeExecutionEA.mq5`.
3. **Compile** (F7). Expected: `0 errors`. Record the exact build number and the
   full compiler output in §12.
4. `JsonBridge.mqh` is compiled transitively via `#include`. To lint it in
   isolation you may temporarily create a throwaway `.mq5` that only
   `#include "JsonBridge.mqh"` — do not commit that file.
5. If any error/warning appears, resolve **only** genuine language issues per
   §3.2, document each, recompile to `0 errors`, and paste final output in §12.

**Compiler results — to be filled by operator**

```
MetaEditor build:            ☐ __________
SessionEdgeExecutionEA.mq5:  ☐ ____ errors, ____ warnings
JsonBridge.mqh:              ☐ ____ errors, ____ warnings
Full compiler log:           ☐ (attach)
Compatibility fixes applied: ☐ (list, or "none")
```

---

## 5. MT5 demo validation matrix (operator)

Attach the terminal *Experts* log and the bridge `health\audit.jsonl` /
`dedup.jsonl` as evidence. "Ref proxy" names the reference/mock test that already
exercises the same behavior on this platform (green today).

| # | Requirement | Procedure (demo) | Expected | Ref proxy (green) | Result |
|---|---|---|---|---|---|
| 1 | EA initialization | Attach EA to a chart | `OnInit` logs "initialised", timer armed; `INIT_FAILED` if auto-trading off | `test_execution_consumer` init paths | ☐ PENDING |
| 2 | Bridge connectivity | Point `BridgeRoot` at the tree | EA sees `outbox\pending`; warns if absent | bridge path tests | ☐ PENDING |
| 3 | Instruction ingestion | Producer drops a valid `<sid>.json` in `pending` | Claimed → `claimed`, `claim` audited | `test_process_next_*` | ☐ PENDING |
| 4 | Acknowledgements | On claim of a valid instruction | `<sid>.<ackid>.ack.json` in `inbox\acks`, `ack` audited before any order | ack tests | ☐ PENDING |
| 5 | Execution | Valid LONG/SHORT | One market order; `EXECUTED` result; archived to `accepted` | execute tests | ☐ PENDING |
| 6 | Audit logging | After any action | Append-only `health\audit.jsonl` lines (claim/ack/process/…) | audit tests | ☐ PENDING |
| 7 | Restart recovery | Kill terminal mid-flow, relaunch | `Recover()` reconciles from bridge+broker; **no second order** | `test_recover_*` | ☐ PENDING |
| 8 | Break-even | Price reaches BE trigger | Stop moves to BE exactly once; audited | `test_breakeven_*` (PM) | ☐ PENDING |
| 9 | Profit lock | Price reaches lock trigger | Stop advances to lock; never loosens | `test_profit_lock_*` (PM) | ☐ PENDING |
| 10 | Trailing stop | Structure advances (fresh bars) | Trail tightens only; `DATA_STALE` if structure stale | `test_trail_*`, `test_f6_*` (PM) | ☐ PENDING |
| 11 | Manual intervention detection | Operator changes SL by hand | Manual tighten adopted+audited; manual loosen rejected/escalated | `test_manual_*` (PM) | ☐ PENDING |
| 12 | Reconciliation | Broker-applied SL differs | Within one tick → no false reconcile; weaker → `RECONCILIATION_REQUIRED`, no retry | `test_f1_*`, `test_f2_*` (PM) | ☐ PENDING |
| 13 | Protective closes | Weekend / kill / max-duration | Protective close only (never a new trade); audited | PM protective-close tests | ☐ PENDING |
| 14 | Weekend handling | Approach weekend per policy | Weekend policy applied (protective) | PM weekend tests | ☐ PENDING |
| 15 | Max-duration handling | Position exceeds max duration | Protective close per policy | PM max-duration tests | ☐ PENDING |
| 16 | Duplicate prevention | Re-drop same `sid`; also re-claim | `SeenTerminal`/broker-comment guard → `DUPLICATE`, no 2nd order | dedup + `X_ADOPTED` tests | ☐ PENDING |
| 17 | Broker reconnect | Pull network during flow | `X_DISCONNECTED`; on reconnect, recovery finalizes, no dup | disconnect tests | ☐ PENDING |
| 18 | Terminal restart | Restart terminal between instructions | State reconstructed from bridge+broker only | `test_recover_*` | ☐ PENDING |

---

## 6. Broker compatibility matrix (operator)

Run per symbol on the demo broker. `NormalizeSymbol` maps canonical `XXXXXX.FX`
→ `XXXXXX + BrokerSuffix`; set `BrokerSuffix` to match the broker's naming
(e.g. `.m`, `.pro`). Non-FX instruments (XAUUSD, indices) are validated for
terminal/broker behavior; the canonical `.FX` symbol contract is FX-shaped, so
record any mapping caveat.

| Check | EURUSD (5-digit) | USDJPY (3-digit) | XAUUSD | CFD index |
|---|---|---|---|---|
| Symbol digits reported | ☐ | ☐ | ☐ | ☐ |
| Point / tick normalization correct | ☐ | ☐ | ☐ | ☐ |
| Broker min stop distance honored | ☐ | ☐ | ☐ | ☐ |
| Lot normalization (min/max/step) | ☐ | ☐ | ☐ | ☐ |
| SL/TP accepted | ☐ | ☐ | ☐ | ☐ |
| Requote handled (`X_REQUOTE`) | ☐ | ☐ | ☐ | ☐ |
| Off-quotes handled (`X_OFF_QUOTES`) | ☐ | ☐ | ☐ | ☐ |
| Market-closed handled (`X_MARKET_CLOSED`) | ☐ | ☐ | ☐ | ☐ |
| Invalid stops handled (`X_INVALID_STOPS`) | ☐ | ☐ | ☐ | ☐ |
| Disconnect/reconnect safe (no dup) | ☐ | ☐ | ☐ | ☐ |

> **Known non-5-digit caveat (from Phase 4D-R review):** the Position Manager's
> pip scaling currently assumes 5-digit pricing; on 3-digit JPY the break-even
> stop can compute equal to entry (fails **closed** — capital-safe, never
> loosens). Record USDJPY BE behavior explicitly; treat exotic/non-power-of-ten
> tick sizes as the highest-scrutiny cases (fail-closed → `RECONCILIATION_REQUIRED`).

---

## 7. Position-management validation (operator confirms on terminal; reference green here)

Confirm each invariant on the demo terminal; each is already enforced and
green in the reference/mock suite (named).

- Never widen / never loosen — `is_stop_improvement` gate → `test_never_loosen_*`
- Immutable initial R — `initial_risk` fixed at entry → `test_initial_risk_*`
- Exact break-even trigger — tick-space compare → `test_breakeven_trigger_*`
- Profit-lock trigger → `test_profit_lock_trigger_*`
- Trailing (fresh structure required) → `test_trail_*`, `test_f6_*`
- One action per evaluation → `test_one_action_per_eval_*`
- Phase progression INITIAL→BE→LOCKED→TRAILING→CLOSED → `test_phase_*`
- Restart recovery / reconciliation → `test_recover_*`, `test_f1_*`, `test_f2_*`
- Manual tighten adopt / loosen reject / manual close / partial close →
  `test_manual_*`

**Terminal confirmation:** ☐ PENDING (operator).

---

## 8. Filesystem-bridge validation (operator confirms; reference green here)

- Deterministic serialization (sorted keys, compact) → bridge serialize tests
- Exactly-once processing / dedup → `SeenResolver` + `test_dedup_*`
- Acknowledgement generation → ack tests
- Archive behavior (accepted/rejected) → archive tests
- Recovery after restart, no duplicate execution → `test_recover_*`
- Atomic write (temp → move) & exclusive claim (move without rewrite) →
  `BridgeWriteTextAtomic` / `BridgeClaim` mirror `bridge` atomicity tests

**Terminal confirmation:** ☐ PENDING (operator).

---

## 9. Restart / recovery validation (operator)

| Scenario | Expected | Result |
|---|---|---|
| Crash after claim, before order | `Recover`: no broker pos, no ack → re-process safely | ☐ PENDING |
| Crash after ack, before order confirmed | ack present, no broker pos → `RECONCILIATION_REQUIRED` (fail closed) | ☐ PENDING |
| Crash after order, before result | broker pos present → finalize `EXECUTED` (`X_RECONCILE`), **no resend** | ☐ PENDING |
| Terminal restart with terminal artifacts present | `SeenTerminal` adopts, `DUPLICATE`, archived | ☐ PENDING |

---

## 10. Performance measurements (operator, demo)

| Metric | How | Value |
|---|---|---|
| CPU (idle poll) | Terminal/OS monitor over 1h | ☐ PENDING |
| Memory (RSS) | OS monitor | ☐ PENDING |
| Bridge latency (drop→claim) | audit timestamps | ☐ PENDING |
| Order latency (claim→result) | audit + trade log | ☐ PENDING |
| Stop-modification latency | PM audit intent→completion | ☐ PENDING |

Poll cadence is `PollSeconds` (default 5s); the EA is timer-driven with no
busy-wait and empty `OnTick`, so idle CPU should be negligible — confirm.

---

## 11. Confirmations (verified in this environment)

**11.1 Strategy unchanged** — `forex_swing_orb/run_dir` last modified in
`c88a5fa` (spec v1.4.0); untouched by Phases 4D/4D-R and by Phase 5.

**11.2 Bridge unchanged** — `forex_swing_orb/bridge` last modified in `d7640ac`
(Phase 3); untouched since. 44 bridge tests green.

**11.3 Position-management arithmetic unchanged** — `position/contract.py` and
`position/spec.py` frozen in `38a57c0` (Phase 4C-R); byte-identical since. 45
spec/contract tests green. Phase 5 makes no arithmetic change.

**11.4 No networking** — Static scan of `SessionEdgeExecutionEA.mq5` and
`JsonBridge.mqh` finds **no** `WebRequest`, `SendMail`, `SendFTP`,
`SendNotification`, sockets, HTTP, REST/RPC, or external process calls. I/O is
the MT5 trade API and the sandboxed MQL5 filesystem only.

**11.5 No AI authority** — No agent/LLM path can move a stop or place/modify an
order. Advisory agents are advisory-only; the single deterministic Position
Manager owns all stop management; the EA executes verbatim validated
instructions and never computes direction/entry/stop/target.

---

## 12. Operator fill-in log (to be completed on Windows)

```
Date / operator:             ☐ __________
Broker / server (demo):      ☐ __________
Account (demo only):         ☐ __________
MetaEditor build:            ☐ __________
Compiler results:            ☐ __________  (attach full log)
MQL5 compatibility fixes:    ☐ __________  (or "none")
Validation matrix (§5):      ☐ __________  (attach Experts log + audit.jsonl)
Broker matrix (§6):          ☐ __________
Restart/recovery (§9):       ☐ __________
Performance (§10):           ☐ __________
Deviations:                  ☐ __________
Blockers:                    ☐ __________
Evidence (screens/logs):     ☐ (attach)
```

---

## 13. Disposition

**Static compile-readiness: PASS** — no hard MQL5 compile errors found; four
candidate warnings documented (§3.2) with output-preserving handling.

**Windows compilation & MT5 demo validation: NOT EXECUTED** — no MetaEditor / MT5
terminal / broker exists in this environment. The behavior the EA mirrors is
fully green in the Python reference + mock MT5 (105 EA/PM + 45 spec + 44 bridge).

**Platform readiness: NOT YET DECLARED.** The platform is **CANDIDATE — pending
terminal validation**. "READY FOR CLOSED BETA DEMO TRADING" must **not** be
declared until an operator completes §4–§10 on a real Windows MT5 demo terminal
and records `0 errors` plus a passing validation matrix. This document is the
gate to that declaration.

**Live-money trading is NOT authorized.**
