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

## 3. Live-cycle `PortfolioState` position adapter — CLOSED (count-based gating), residual approximations remain

`deployment_windows/start.py`'s live-cycle loop previously constructed
`PortfolioState()` with no arguments on every cycle, so
`portfolio_state.open_positions` was permanently empty regardless of what
the EA actually had open. `check_position_limits()` could therefore never
reject a duplicate entry for an already-open pair, and
`RuntimeOrchestrator` (which generates a fresh `TradeCommand`/
`correlation_id` every cycle whenever `compliance.ready_for_bridge` is
true, with no in-flight-command check of its own) would keep submitting
new commands for the same signal indefinitely.

Fixed: `_map_bridge_positions_to_open_positions()` now maps
`BridgeEngine.latest_positions` (real, EA-reported `PositionReport`s) into
`risk_engine.models.OpenPosition`, wired into the `PortfolioState` built
each cycle. This closes the specific defect (`check_position_limits()`
can now see and reject an already-open pair). Three approximations remain,
documented rather than silently assumed correct:

- **`OpenPosition.size_r` is fixed at `0.0`.** It represents risk
  allocated to the position *in R*, which cannot be derived from
  `PositionReport`'s volume/open_price/stop_loss without also knowing the
  account's risk-per-R at the time the position was opened -- the EA does
  not report this, and no existing module in this repo computes it from
  raw volume alone. Fabricating a value would inject an unverified number
  into `compute_exposure_summary()`/`check_safety_limits()`/
  `compute_correlation_status()` -- real capital-preservation gates --
  which would be worse than the previous gap, not better. Those three
  functions therefore remain blind to already-open positions' risk
  contribution; only count-based gating is fixed.
- **`OpenPosition.opened_at` uses the position's last `received_at`**
  (report time), not true open time -- drifts up to one report cycle
  (~5s). Not consumed by `check_position_limits()`.
- **"Positively reported zero positions" vs. "never reported" is
  structurally ambiguous** from `BridgeEngine.latest_positions` alone (both
  produce an empty tuple). Resolved via `BridgeEngine.is_connection_healthy`
  (heartbeat freshness) as a proxy: healthy heartbeat -> trust
  `latest_positions` as-is (including empty); no recent heartbeat -> every
  pair is skipped this cycle (`no_recent_position_report`, fail-closed).
  This proxy cannot detect `/bridge/positions` specifically failing while
  heartbeat keeps succeeding. Closing this precisely would need a
  dedicated `last_positions_received_at` on `BridgeEngine` -- out of scope
  for this change (would touch `titan_protocol/bridge/`, deliberately not
  modified here).

A separate, related gap -- `RuntimeOrchestrator` has no pair-level
in-flight-command guard covering the window between command delivery and
the next valid position report -- is **not** addressed by this change and
remains open.

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
