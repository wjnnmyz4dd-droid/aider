# Titan Protocol Windows Deployment — Known Gaps

This deployment layer wires together every real, existing, public
interface in `titan_protocol/` (Bridge, the 5 core trading engines, Runtime
Orchestrator, Reliability) exactly as documented in
`PHANTOM_MT5_DEPLOYMENT_AUDIT.md`. It adds **zero new trading logic,
zero engine modifications, and zero architectural redesign.** Two real
gaps exist in the underlying `titan_protocol/` codebase itself — this
deployment layer cannot close them without inventing new business
logic, which was explicitly out of scope for this mission. They are
recorded here rather than papered over.

## 1. No live market-data ingestion component is wired into a live entry point

**What's missing:** `RuntimeOrchestrator.run_cycle()` /
`run_cycle_for_pair()` require the caller to already have, for every
pair, every cycle: OHLC bars, news events, current/average spread,
portfolio state, trade history, and account state. `titan_protocol/
market_data_ingestion/` (ADR-033 Part 1) now exists and normalizes raw
bars/ticks down to the frozen `Bar` type, but nothing in this
deployment layer's entry point (`start.py`) constructs or drives it —
it is a tested, standalone package, not yet wired into a running
process.

**Evidence (traced, not assumed):**
- `titan_protocol/bridge/server.py`'s entire HTTP protocol is
  execution-only: `/bridge/heartbeat`, `/bridge/account`,
  `/bridge/positions`, `/bridge/orders`, `/bridge/trade-transaction`,
  `/bridge/error`, `/bridge/execution/report`,
  `/bridge/commands/poll`. Zero endpoints exist for bars, candles,
  OHLC, or market data of any kind.
- `mt5/TitanProtocolEA.mq5`'s own header comment: *"This EA is a
  transport + execution bridge ONLY: it never generates, scores, or
  [fetches market data]."*
- `start.py` constructs the Bridge, the 5 core engines, and the Runtime
  Orchestrator, but never imports or constructs anything from
  `titan_protocol/market_data_ingestion/` — grep `start.py` for
  `market_data_ingestion` to confirm.
- `health_check.py`'s "market-data readiness" check always reports
  **NOT AVAILABLE** for the same reason -- it is not a probe that could
  someday come back healthy on its own; there is no feed for it to
  probe.

**What this deployment layer does instead:** `start.py` starts
the Bridge HTTP service (real, live, reachable by the EA) and
constructs the Runtime Orchestrator and all 5 engines (proving the
wiring compiles and the objects are valid), plus starts Reliability
monitoring the process's own liveness. It does **not** call
`run_cycle()` in a loop, and does not fabricate bars/news/spread data
to make one up. `start.py` and `health_check.py` both report
this honestly: status is always **DEGRADED**, never HEALTHY, and both
print/expose `cycle_loop_active: false` with this exact reason.

**To close this gap:** wire `titan_protocol/market_data_ingestion/`'s output
(or a genuine MT5 feed such as `CopyRates`/`CopyTicks` pushed to the
Bridge via a new endpoint) into a live trading-cycle loop that calls
`RuntimeOrchestrator.run_cycle()`'s per-pair `inputs` on a real
schedule. This deployment layer's `start.py` is not the place to add
that loop without a mission scoped to it — this task's own mission
("Replace the Windows batch deployment layer with a Python Deployment
Manager... Do NOT modify any trading engine, runtime logic, bridge
logic, or business rules") explicitly excludes it.

## 2. Multi-provider news system (Trading Economics / Forex Factory) — CLOSED, Phase 3E

**Closed by:** `titan_protocol/news_ingestion/` (ADR-033 Part 2, Phase 3E) —
a real Trading Economics primary / Forex Factory automatic-backup
failover engine, wired into `start.py`'s live-cycle loop and exposed
through `health_check.py`'s "news provider failover" check and
`state/health.json`'s `news` field. `MarketIntelligenceEngine` itself
is unmodified and still has exactly one seam (`news_feed_trusted` +
`events`) — it never knows which provider is active; this package only
supplies it better, failover-protected data through that same existing
seam. Never merges, averages, or votes between providers (verified by
`tests/titan_protocol/news_ingestion/test_failover.py`'s
`TestNoMergeAverageOrVote`).

**Residual limitation:** `forex_factory_base_url` defaults to empty in
the shipped example config — an operator must point it at a real JSON
calendar feed (shape documented in
`titan_protocol/news_ingestion/providers/forex_factory.py`'s own
docstring) for the backup provider to actually be reachable. Until
configured, a Trading Economics outage fails closed immediately (no
functioning backup), which is the same safe behavior as before this
phase, not a regression.

## Everything else in this release is fully implemented

Setup, dependency installation, folder/configuration/write-access
verification (including the new `data\` folder), compileall, import
smoke test, Bridge startup and bind verification, Reliability
monitoring (including real Bridge command-queue depth via
`ReliabilityEngine.report_queue_depth`), graceful/forced stop scoped to
exactly one recorded pid, restart sequencing, health checking (Bridge,
Runtime, Reliability, configuration, API-key-env-var presence,
news-feed trust state, queue health, duplicate-process detection), MT5
file installation with automatic `.set` personalization (short of
MetaEditor compilation, which requires the real GUI), and desktop
shortcut creation (Windows only) are all real, working, and were
exercised end-to-end in this environment before this release was sent.
