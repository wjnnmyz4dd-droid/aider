# MetaTrader 5 Standard Library — Architectural Research

Research only. No code from any source was copied — every finding
below is described in original prose as an architectural concept or
pattern. Where a source is cited, it is MetaQuotes' own published
reference/book (the standard library ships with every MT5 install; it
is not a third-party or GPL repository, so it is not subject to the
GPL-removal directive that applied to EA31337 and similar reference
repos). This research directly informs the frozen architecture in
`PHANTOM_FINAL_ARCHITECTURE.md`, specifically component 1
(PhantomBridgeEA) and the execution/decision flows there — it does not
change anything already built in `mt5/PhantomBridgeEA.mq5`, which
remains frozen pending real MT5 validation per
`PHANTOM_BRIDGE_EA_PHASE1_VALIDATION_PACKAGE.md`.

Sources consulted:
- [MQL5 Reference — Trade Classes / Standard Library](https://www.mql5.com/en/docs/standardlibrary/tradeclasses)
- [CTrade class reference](https://www.mql5.com/en/docs/standardlibrary/tradeclasses/ctrade)
- [CPositionInfo class reference](https://www.mql5.com/en/docs/standardlibrary/tradeclasses/cpositioninfo)
- [CSymbolInfo class reference](https://www.mql5.com/en/docs/standardlibrary/tradeclasses/csymbolinfo)
- [OnTradeTransaction event handler reference](https://www.mql5.com/en/docs/event_handlers/ontradetransaction)
- [MqlTradeTransaction structure reference](https://www.mql5.com/en/docs/constants/structures/mqltradetransaction)
- [ENUM_TRADE_TRANSACTION_TYPE reference](https://www.mql5.com/en/docs/constants/tradingconstants/enum_trade_transaction_type)
- [MQL5 Programming Book — order execution modes by price and volume](https://www.mql5.com/en/book/automation/experts/experts_execution_filling)
- [MQL5 Programming Book — symbol trading conditions and order execution modes](https://www.mql5.com/en/book/automation/symbols/symbols_execution_filling)
- [MQL5 Cookbook — Processing of the TradeTransaction Event](https://www.mql5.com/en/articles/1111)

---

## 1. The six standard library classes

The standard library's trade classes (`MQL5/Include/Trade/`) exist to
give an Expert Advisor a typed, method-based facade over MT5's raw
`OrderSend`/`PositionGetXxx`/`OrderGetXxx`/`HistoryDealGetXxx` function
calls, rather than every EA re-deriving the same bookkeeping. Each
class owns exactly one read or write responsibility:

| Class | Responsibility | Architectural role |
|---|---|---|
| `CTrade` | Issues trade requests (market/pending orders, modify, close, partial close) and exposes the last request's result (retcode, ticket, fill price, fill volume, deviation, filling type) | The **only** write path to the trade server. `PhantomBridgeEA.mq5` already uses this class exclusively for execution — no direct `OrderSend` calls exist in the frozen file. |
| `CPositionInfo` | A read-only cursor over one open position's properties (ticket, symbol, type, volume, open price, SL/TP, profit, swap, magic, comment, time) once selected | Position-state *reads*. The frozen EA currently uses the raw `PositionGetTicket`/`PositionSelectByTicket`/`PositionGetInteger`/`PositionGetDouble`/`PositionGetString` functions directly rather than this class — functionally equivalent, but the class would remove repeated raw property-key lookups if the EA is ever revisited. |
| `COrderInfo` | The same read-only cursor pattern as `CPositionInfo`, but over *pending* orders | Pending-order reads. The frozen EA similarly uses the raw `OrderGetTicket`/`OrderSelect`/`OrderGetInteger`/`OrderGetDouble`/`OrderGetString` functions directly; Phase 1 never places pending orders (only BUY/SELL market orders), so this class's write-adjacent surface (order lifecycle beyond reading) is not exercised in scope. |
| `CDealInfo` | A read-only cursor over one historical deal (the immutable record of an actual fill, as opposed to a position, which is the live net result of one or more deals) | Historical-fact reads. Not currently used by the frozen EA; relevant to any future reconciliation between what the EA's own `ExecutionReport` claims and what MT5's deal history actually recorded — a stronger version of the drift-detection idea already implemented via `OnTradeTransaction` mirroring. |
| `CAccountInfo` | Account-level properties (balance, equity, margin, leverage, currency, trade-allowed flags) | Account-state reads. The frozen EA uses the raw `AccountInfoDouble`/`AccountInfoInteger`/`AccountInfoString` functions directly for the same data this class would wrap. |
| `CSymbolInfo` | Symbol-level trading conditions (bid/ask, point, digits, volume min/max/step, stops level, filling modes, trade mode) with an explicit `RefreshRates()`/`Refresh()` step | Symbol-condition reads. The frozen EA's `CheckTradingPreconditions`/`CheckVolumeValid`/`CheckStopsValid` (added in the Phase 1 fix round) use the raw `SymbolInfoInteger`/`SymbolInfoDouble` functions directly rather than this class. |

**Architectural takeaway:** the standard library's split mirrors the
frozen bridge's own internal split — one class per data domain, one
authority per responsibility, exactly the "one authority per
responsibility" principle already governing Phantom's own design. The
frozen EA achieves the same effect using MT5's raw functions instead of
these wrapper classes; that is a valid, equally correct implementation
choice (the wrapper classes are convenience, not a different execution
model) and is not something this research recommends changing under
the current architecture freeze.

## 2. `OnTradeTransaction()` — event semantics and hazards

`OnTradeTransaction` fires for a trade request sent by an MQL5 program
(`OrderSend`/`OrderSendAsync`), a manual GUI trade, or a pending/stop
order activating on the server. It receives three parameters: the
`MqlTradeTransaction` describing what changed, plus the original
`MqlTradeRequest` and `MqlTradeResult` — but the latter two are only
meaningful for a `TRADE_TRANSACTION_REQUEST`-type transaction; for
every other transaction type (`ORDER_ADD`, `ORDER_UPDATE`,
`ORDER_DELETE`, `DEAL_ADD`, `DEAL_UPDATE`, `HISTORY_ADD`), only the
`MqlTradeTransaction` struct itself carries real data.

Three hazards documented by MetaQuotes directly bear on Phantom's
design:

1. **No ordering guarantee.** Transactions for the same trade (order
   added, order executed, order removed, deal added, position created)
   can arrive in any order, and a single BUY can legitimately produce
   several distinct transactions. A consumer must never assume "order
   add always precedes deal add" or similar. This is exactly why the
   frozen EA's `SendTradeTransaction` treats every transaction as an
   independent, unsolicited event to mirror — never as a state
   machine step to sequence against its own `ExecuteBuy`/`ExecuteSell`
   call.
2. **State can change mid-handler.** Because the terminal keeps
   processing incoming transactions concurrently with the handler's
   own execution, an order referenced by the transaction currently
   being handled may already be gone (executed and moved to history)
   by the time the handler inspects it. Any logic that needs a
   position/order's *current* state must re-select it fresh
   (`PositionSelectByTicket`, etc.) rather than trust fields cached
   from the transaction event — which the frozen EA's `Execute*`
   retry loops already do (each loop iteration re-selects the position
   before acting), independently arrived at but consistent with this
   documented pattern.
3. **Bounded transaction queue (1024 elements).** A slow
   `OnTradeTransaction` handler risks losing transactions once the
   queue is exceeded. This reinforces that the handler must stay
   fast and non-blocking — the frozen EA's `SendTradeTransaction` does
   one bounded HTTP POST and returns; it does not loop, retry
   extensively, or perform any heavy computation inline.

## 3. Order lifecycle

A single market order's canonical lifecycle, as MetaQuotes documents
it: request accepted for processing -> an order object created on the
account -> the order executed -> the order removed from the active
list -> the order appended to order history -> the corresponding deal
appended to deal history -> a position created or updated from that
deal. A pending order's lifecycle differs only in that "order created"
and "order executed" are separated in time (and may never both occur,
if the pending order expires or is cancelled instead).

**Architectural implication for Phantom:** a "trade" is not one atomic
event but a small graph of order/deal/position records, and MT5 itself
treats the *position* (net exposure per symbol+direction, under
netting, or per ticket under hedging) as the durable object, while
*orders* and *deals* are transient/historical records leading up to
it. Phantom's `TradeCommand`/`ExecutionReport`/`TradeTransactionReport`
split (already built in `phantom/bridge/models.py`) maps directly onto
this: `TradeCommand` is Phantom's own request (not an MT5 order),
`ExecutionReport` is Phantom's own authoritative record of what its
command produced, and `TradeTransactionReport` is the independent
mirror of MT5's own native order/deal/position graph — kept separate
specifically because the two graphs (Phantom's command history vs.
MT5's native trade history) are not the same data model and should
never be silently merged into one.

## 4. Position lifecycle

Under netting accounting (the default for most retail FX/CFD
accounts), a symbol has at most one net position; every new deal on
that symbol adjusts the existing position's volume/average price
rather than creating a second one. Under hedging accounting, multiple
independent positions can coexist per symbol, each with its own
ticket. `CPositionInfo`/`PositionSelectByTicket` work identically in
either mode from the EA's perspective — select by ticket, read
properties — but **volume arithmetic differs**: a partial close under
netting reduces the one position; under hedging, closing part of one
ticket leaves that ticket at a reduced volume while other tickets on
the same symbol are unaffected. Phantom's `PARTIAL_CLOSE` command
already operates strictly by `position_id`/ticket
(`SelectOwnedPosition`/`PositionClosePartial(ticket, closeVolume, ...)`)
rather than by symbol-level aggregate volume, which is correct under
both accounting modes — this is a design property worth stating
explicitly as validated-by-research rather than merely assumed.

## 5. Best execution patterns

- **Filling policy is a symbol- and broker-level constraint, not a
  free choice.** `SYMBOL_FILLING_MODE` reports which of
  `ORDER_FILLING_FOK` (fill the full requested volume or nothing),
  `ORDER_FILLING_IOC` (fill whatever's available immediately, cancel
  the remainder), or `ORDER_FILLING_RETURN` (partially fill, leave the
  remainder working) a given symbol actually supports, as a bitmask.
  If a request's filling type isn't supported, the broker rejects it.
  `CTrade` (and therefore the frozen EA, which never sets a filling
  type explicitly on its `Buy`/`Sell`/`PositionClose*` calls) falls
  back to `ORDER_FILLING_RETURN` when none is specified. **Research
  finding relevant to a future hardening pass (not the current
  freeze):** in Request/Instant execution modes, market orders always
  use Fill-or-Kill regardless of what's requested, while
  Market/Exchange execution modes always allow Return — meaning the
  effective filling behavior actually depends on the broker's
  execution mode, not solely on what the EA asks for. This is a
  documented broker-compatibility variable, not a defect in the frozen
  EA; it belongs in a future, separately-approved hardening item, not
  an unrequested change now.
- **Deviation/slippage is expressed in points, applied only to market
  orders, and only matters under certain execution modes.** The
  frozen EA's `MaxSlippagePoints` input, passed via
  `g_trade.SetDeviationInPoints(...)`, matches this pattern correctly.
- **Never trust the requested price/volume as the outcome.** `CTrade`
  exposes `ResultPrice()`/`ResultVolume()`/`ResultRetcode()`/
  `ResultOrder()` specifically because a market order's actual fill
  can legitimately differ from what was requested (slippage, partial
  fill) even on a fully successful `true` return. This is precisely
  the property Fix #2 in `PHANTOM_BRIDGE_EA_PHASE1_FIX_REPORT.md`
  corrected the frozen EA to respect.

## 6. Error handling patterns

- **Distinguish "the broker said no" from "the request never
  reached the broker."** A `CTrade` call returning `false` with a
  populated `ResultRetcode()` (e.g. `TRADE_RETCODE_INVALID_STOPS`,
  `TRADE_RETCODE_NO_MONEY`) is a real, informative rejection; a
  `WebRequest`/transport-level failure (status <= 0) or a terminal-
  level block (`TERMINAL_TRADE_ALLOWED` false) is a different failure
  class entirely and must be surfaced differently. The frozen EA
  already separates these: pre-flight checks (`CheckTradingPreconditions`
  etc.) short-circuit before ever calling `CTrade`, and only a real
  `CTrade` attempt produces a numeric retcode error.
- **Retry only what is safe to retry.** MetaQuotes' own retcode
  taxonomy separates transient, price-related retcodes
  (`TRADE_RETCODE_REQUOTE`, `TRADE_RETCODE_PRICE_CHANGED`) from
  everything else (rejection, invalid parameters, insufficient
  margin, trade-context contention). Blindly retrying any failure is
  an anti-pattern (it can duplicate execution under some failure
  modes, or waste the bounded retry budget on an error retrying will
  never fix). This is exactly the distinction Fix #4 encodes via
  `IsRequoteRetcode`.
- **Never assume a handler's view of the world is still current by
  the time it acts.** Covered in §2 above; applies equally to any
  future code that inspects `CPositionInfo`/`COrderInfo` state outside
  of `OnTradeTransaction`.

## 7. Broker compatibility

Confirmed variables across brokers/symbols that any execution-layer
component must treat as configuration, never as a hardcoded
assumption: `SYMBOL_TRADE_MODE` (full/close-only/disabled/etc.),
`SYMBOL_FILLING_MODE` (which filling policies are actually accepted),
`SYMBOL_VOLUME_MIN/MAX/STEP`, `SYMBOL_TRADE_STOPS_LEVEL` (minimum
stop distance), `SYMBOL_TRADE_FREEZE_LEVEL` (a related, distinct
"can't modify this close to price" distance the frozen EA does not
currently check — noted as a research finding for a future,
separately-approved hardening item, not an in-scope defect), and
account-level `ACCOUNT_TRADE_ALLOWED`/`ACCOUNT_TRADE_EXPERT`/
`ACCOUNT_MARGIN_MODE` (netting vs. hedging, which changes position
lifecycle semantics per §4). Phase 1's pre-flight checks already cover
most of these; `SYMBOL_TRADE_FREEZE_LEVEL` and explicit filling-mode
negotiation are the two gaps this research surfaces for a possible
future fix round — again, not authorized by this research-only task.

## 8. MT5 best practices, synthesized

1. One class/module per data domain (account, symbol, position,
   order, deal) — never one god-object touching all of them.
2. Treat `OnTradeTransaction` as a fire-and-forget, unordered,
   possibly-stale event stream; never as a synchronous return value
   from a command you issued.
3. Always re-read authoritative state (`PositionSelectByTicket`, etc.)
   immediately before acting on it, never from a cached/earlier read.
4. Report what the trade server actually did (`ResultPrice`/
   `ResultVolume`/`ResultRetcode`), never what was requested.
5. Validate broker/symbol/account trading capability before every
   attempt, not only once at startup — conditions change intraday
   (session close, broker-side trade-mode changes).
6. Retry narrowly (transient, price-related retcodes only) and
   boundedly; treat every other retcode as a terminal outcome for that
   attempt.
7. Keep any event handler that the terminal calls synchronously (like
   `OnTradeTransaction`) fast — offload anything slower than a single
   bounded network call.

None of the above requires or recommends a change to
`mt5/PhantomBridgeEA.mq5` right now — every point either confirms a
design already present in the frozen file, or names a candidate for a
future, separately-scoped and separately-approved hardening pass
(`SYMBOL_TRADE_FREEZE_LEVEL`, explicit filling-mode negotiation,
`CDealInfo`-based reconciliation). This research's only immediate use
is informing the execution/decision flows described in
`PHANTOM_FINAL_ARCHITECTURE.md`.
