# Phantom Windows Deployment — Known Gaps

This deployment layer wires together every real, existing, public
interface in `phantom/` (Bridge, the 5 core trading engines, Runtime
Orchestrator, Reliability) exactly as documented in
`PHANTOM_MT5_DEPLOYMENT_AUDIT.md`. It adds **zero new trading logic,
zero engine modifications, and zero architectural redesign.** Two real
gaps exist in the underlying `phantom/` codebase itself — this
deployment layer cannot close them without inventing new business
logic, which was explicitly out of scope for this mission. They are
recorded here rather than papered over.

## 1. No live market-data ingestion component exists

**What's missing:** `RuntimeOrchestrator.run_cycle()` /
`run_cycle_for_pair()` require the caller to already have, for every
pair, every cycle: OHLC bars, news events, current/average spread,
portfolio state, trade history, and account state. Nothing in the
minimum live package fetches any of this from MT5 or an external
provider.

**Evidence (traced, not assumed):**
- `phantom/bridge/server.py`'s entire HTTP protocol is
  execution-only: `/bridge/heartbeat`, `/bridge/account`,
  `/bridge/positions`, `/bridge/orders`, `/bridge/trade-transaction`,
  `/bridge/error`, `/bridge/execution/report`,
  `/bridge/commands/poll`. Zero endpoints exist for bars, candles,
  OHLC, or market data of any kind.
- `mt5/PhantomBridgeEA.mq5`'s own header comment: *"This EA is a
  transport + execution bridge ONLY: it never generates, scores, or
  [fetches market data]."*
- Grepped every file in `phantom/bridge`, `phantom/runtime`, and
  `phantom/evidence_engine` for `CopyRates`, `MetaTrader5`, or any
  market-data-fetching call — zero hits.

**What this deployment layer does instead:** `run_phantom.py` starts
the Bridge HTTP service (real, live, reachable by the EA) and
constructs the Runtime Orchestrator and all 5 engines (proving the
wiring compiles and the objects are valid), plus starts Reliability
monitoring the process's own liveness. It does **not** call
`run_cycle()` in a loop, and does not fabricate bars/news/spread data
to make one up. `run_phantom.py` and `health_check.py` both report
this honestly: status is always **DEGRADED**, never HEALTHY, and both
print/expose `cycle_loop_active: false` with this exact reason.

**To close this gap:** design and implement a Market Data Ingestion
component (e.g., MT5's `CopyRates`/`CopyTicks` pushed to the Bridge via
a new endpoint, or a separate provider feed) and wire its output into
`RuntimeOrchestrator.run_cycle()`'s per-pair `inputs`. Per this
repository's own CLAUDE.md workflow (§1.10), that is a new pipeline
stage and needs its own Accepted ADR before any implementation begins
— it was not designed or implemented here.

## 2. No multi-provider news system (Trading Economics / Forex Factory)

**What's missing:** the mission asked for a config template with
"Trading Economics primary configuration," "Forex Factory backup
configuration," and "never merge or average both provider feeds."

**Evidence (traced, not assumed):** grepped every file under
`phantom/` for `trading.?economics` and `forex.?factory`
(case-insensitive) — zero hits, anywhere. The Market Intelligence
Engine (`phantom/market_intelligence/`) has exactly one news-trust
signal: `news_feed_trusted: bool`, passed to
`MarketIntelligenceEngine.evaluate()`. There is no `provider` field on
`NewsEvent`, no per-provider trust/disagreement/outage logic, and no
primary/backup failover concept anywhere in the engine.

**What this deployment layer does instead:** `deployment_windows/
config/phantom.config.template.ini`'s `[news]` section exposes only
the fields that actually exist and actually do something
(`news_feed_trusted`, blackout windows, impact/central-bank blackout
toggles), with an explicit comment explaining the gap. It does **not**
fabricate `trading_economics_*` / `forex_factory_*` config keys that
the engine would silently ignore — that would be worse than not having
them, since an operator editing a fake config key would reasonably
believe it does something.

**To close this gap:** a genuine multi-provider news feed with real
primary/backup failover and disagreement detection requires a new
ADR-025 Amendment and new engine code. Not designed or implemented
here, per the same CLAUDE.md §1.10 workflow.

## Everything else in this deployment layer is fully implemented

Setup, dependency installation, folder/configuration/write-access
verification, compileall, import smoke test, Bridge startup, Reliability
monitoring, graceful/forced stop scoped to exactly one recorded pid,
restart sequencing, health checking, and MT5 file installation (short
of MetaEditor compilation, which requires the real GUI) are all real,
working, and were exercised in this environment — see
`PHANTOM_WINDOWS_DEPLOYMENT_VERIFICATION.md` for exactly what was run
and what could only be run on a real Windows/MT5 box.
