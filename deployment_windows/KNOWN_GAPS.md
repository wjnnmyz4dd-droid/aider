# Titan Protocol Windows Deployment — Known Gaps

This deployment layer wires together every real, existing, public
interface in `titan_protocol/` (Bridge, the 5 core trading engines,
Runtime Orchestrator, Reliability, market-data ingestion, news
ingestion) exactly as documented in `PHANTOM_MT5_DEPLOYMENT_AUDIT.md`
(historical) and the ADRs referenced below. It adds **zero new trading
logic, zero engine modifications, and zero architectural redesign.**
Both gaps originally recorded here are now CLOSED in code; one residual
*configuration* limitation remains (section 2) and one residual
*environmental* limitation applies to both (running status requires a
real, connected MT5 EA — see section 1). Recorded here rather than
papered over.

## 1. Live market-data ingestion — CLOSED, Amendment 1 (ADR-023)

**Closed by:** `start.py`'s `_live_cycle_loop()`, fed by
`titan_protocol/market_data_ingestion/` (ADR-033 Part 1). The EA reports
bars/ticks to the Bridge's `POST /bridge/market-data` endpoint
(`titan_protocol/bridge/server.py`'s `_handle_market_data`); once
`MarketDataIngestionEngine.is_ready(pair, timeframe, now)` says a pair's
feed is warmed-up and fresh, `_live_cycle_loop()` pulls its real
bars/spread via `get_bars()`/`latest_spread()` and calls
`RuntimeOrchestrator.run_cycle()` with them — never with fabricated
data. A pair with no data yet is simply skipped for that tick (see
`state/health.json`'s `live_cycle` field and `health_check.py`'s
"market-data readiness" check, which reports real
warmup/fresh/accepted/rejected/gap/tick counts, not a static
placeholder).

**Residual limitation:** this closes the *code* gap, not the
*environment* one — the feed only becomes ready once a real MT5
terminal is running `TitanProtocolEA` and actually reporting bars.
Without a real MT5 EA connected (e.g. in an environment with no MT5
terminal at all), `is_ready()` never returns true for any pair, the
live-cycle loop skips every tick, and overall status stays **DEGRADED**
— this is the live-cycle loop correctly reporting "no real data yet,"
not a bug. Persisted day-start/peak-balance/lock tracking across
restarts (`titan_protocol.compliance_state_store`) is real and
independent of this gap; it does not by itself flip status to HEALTHY
either, since HEALTHY additionally requires a live, currently-connected
EA.

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
