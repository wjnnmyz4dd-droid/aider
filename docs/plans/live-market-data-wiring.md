# Plan: Live Market Data Wiring (MT5 EA → Bridge → MarketDataIngestionEngine → RuntimeOrchestrator)

Status: Planned
Owner (Plan phase): Software Architect
Touched components: `mt5/TitanProtocolEA.mq5`, `titan_protocol/bridge/`, `deployment_windows/start.py`, `deployment_windows/health_check.py`

---

## Research

**Affected files and their dependencies:**
- `mt5/TitanProtocolEA.mq5` — currently sends heartbeats and relays trade
  commands only. No market-data messages exist today (confirmed by its
  own header comment: "transport + execution bridge ONLY").
- `titan_protocol/bridge/server.py` — routes POSTs through a single
  `_POST_ROUTES` dict (`/bridge/heartbeat`, `/bridge/account`,
  `/bridge/positions`, `/bridge/orders`, `/bridge/trade-transaction`,
  `/bridge/error`, `/bridge/execution/report`). Zero bar/tick/candle
  routes exist. Adding one is additive to this table, not a redesign.
- `titan_protocol/market_data_ingestion/engine.py`
  (`MarketDataIngestionEngine`) — fully built and tested (ADR-033,
  Accepted). Public methods already do everything needed:
  `ingest_bar()`, `ingest_tick()`, `is_ready()`, `get_bars()`,
  `latest_spread()`, `health_snapshot()`. It already imports and
  produces `titan_protocol.evidence_engine.models.Bar` — the exact type
  `RuntimeOrchestrator.run_cycle_for_pair()` takes as its `bars`
  parameter. Nothing here needs to change.
- `titan_protocol/runtime/engine.py`
  (`RuntimeOrchestrator.run_cycle_for_pair`) — already accepts `bars:
  Sequence[Bar]`, `market_safety_inputs`, `portfolio_state`,
  `trade_history`, `account_state`, `profile`, `now`, `cycle_id` and
  already executes Evidence → Market Intelligence → Strategy → Risk →
  Compliance → Bridge in fixed order (ADR-031, Accepted). This method
  is not being changed — it is being called, for the first time, on a
  real schedule with real inputs instead of only in tests.
- `deployment_windows/start.py` — constructs the Bridge and all 5 core
  engines plus the Runtime Orchestrator already, but never constructs
  `MarketDataIngestionEngine` and never calls `run_cycle_for_pair()` in
  a loop (`KNOWN_GAPS.md` section 1).

**Touched stage's ADR status (must be Accepted, `CLAUDE.md` §1.10):**
- ADR-031 (Runtime Orchestrator): Accepted — unchanged by this plan.
- ADR-033 (Market Data Ingestion): Accepted — unchanged by this plan;
  reused exactly as built.
- ADR-023 (MQL5 EA Bridge): Accepted, but its built implementation is
  scoped execution-only — no market-data message type or endpoint
  exists in what was actually shipped. Adding a bar/tick-reporting
  endpoint **extends this stage's scope** and needs a short ADR-023
  Amendment describing the new message type and endpoint *before*
  implementation begins, per §1.10. This plan does not implement
  anything until that amendment is written and accepted.

**Duplicate logic / potential regressions found:** none — every
validation/normalization/gap/freshness/warmup rule already lives
exclusively in `MarketDataIngestionEngine`. This plan adds a transport
path to it, not a second copy of its logic.

**`python3 scripts/check_architecture.py` result:** PASS (checked
before writing this plan; unaffected by this plan's scope since it
inspects `phantom_pipeline/`, not `titan_protocol/`).

---

## Plan

**Approach — single canonical data path, four touch points, nothing else:**

```
TitanProtocolEA.mq5  --(new POST message)-->  Bridge (+1 endpoint)
                                                    |
                                                    v
                                      MarketDataIngestionEngine.ingest_bar()/ingest_tick()
                                      (existing, unmodified)
                                                    |
                                                    v (get_bars(), latest_spread(), is_ready())
                                        start.py's new live-cycle loop
                                                    |
                                                    v (bars=... into existing signature)
                                RuntimeOrchestrator.run_cycle_for_pair()
                                      (existing, unmodified)
                                                    |
                                                    v
                     Evidence -> Market Intelligence -> Strategy -> Risk -> Compliance -> Bridge
                                      (existing, unmodified)
```

1. **EA (`TitanProtocolEA.mq5`):** on each new closed bar (and optionally
   each tick, for spread), POST it to a new Bridge endpoint. Same
   API-key header, same JSON-body convention every existing message
   already uses — no new transport pattern invented.
2. **Bridge (`server.py` + `models.py`):** one new route (e.g. `POST
   /bridge/market-data`), following the exact shape of the 7 existing
   routes. Its handler deserializes the payload into `RawBar`/`TickEvent`
   (types `MarketDataIngestionEngine` already defines) and calls
   `ingest_bar()`/`ingest_tick()` — zero new validation logic written
   here, all of it delegated to the existing engine.
3. **`start.py`:** construct one `MarketDataIngestionEngine` instance
   (config already has a place for this — `MarketDataIngestionConfig`),
   pass it into the Bridge handler construction, and add a loop that,
   on a fixed interval per pair, calls `is_ready()` — see Fail-closed
   behavior below — and if ready, calls `get_bars()` +
   `latest_spread()` and feeds them into the existing
   `run_cycle_for_pair()` call. This loop is the only genuinely new
   piece of orchestration code in this plan.
4. **Nothing else changes.** Evidence, Market Intelligence, Strategy,
   Risk, Compliance, and Execution Validator logic are not touched.

**Fail-closed behavior:**
`MarketDataIngestionEngine.is_ready(symbol, timeframe, now)` already
returns `False` when warmup isn't complete or the last bar is stale
(`is_stale()`, already implemented). The new live-cycle loop in
`start.py` checks this *before* calling `run_cycle_for_pair()` for a
pair — if not ready, that pair's cycle is skipped for this tick (no
trade decision is made, nothing is fabricated, and this is logged).
This reuses the engine's existing staleness/warmup logic rather than
inventing a second freshness check; the loop only ever asks a question
the engine already knows the answer to.

**Observability:**
`MarketFeedHealthSnapshot` (returned by
`MarketDataIngestionEngine.health_snapshot()`) already carries
`warmup_statuses`, `freshness` (per symbol/timeframe, incl.
`last_bar_open_time` and `is_stale`), and recent gap `reasons`. This
plan exposes that existing snapshot through `health_check.py` — the
same place `queue health` and `market-data readiness` are already
reported — rather than building a new metrics surface. Ingestion
accept/reject/gap counts already exist on
`MarketDataIngestionMetrics`; this plan wires that object through
`start.py` the same way `RuntimeMetrics` and `BridgeMetrics` already
are, so it costs nothing new to build.

**Backwards compatibility:**
The new Bridge route is additive to `_POST_ROUTES` — every existing
route (`heartbeat`, `account`, `positions`, `orders`,
`trade-transaction`, `error`, `execution/report`, `commands/poll`)
keeps its current handler, signature, and behavior unchanged. The EA's
existing heartbeat/execution message types are unmodified; the new
market-data message is a new, independent message type alongside them.
`health_check.py`'s existing checks (bridge reachable, EA heartbeat,
queue health, etc.) are unaffected; only `market-data readiness` goes
from an always-NOT-AVAILABLE stub to a real, live-reported status.

**Files to be touched:**
- `mt5/TitanProtocolEA.mq5` (+ recompiled `.ex5`)
- `titan_protocol/bridge/server.py` (one new route)
- `titan_protocol/bridge/models.py` (request/response shape for the new route, if needed)
- `deployment_windows/start.py` (construct `MarketDataIngestionEngine`, add the live-cycle loop)
- `deployment_windows/health_check.py` (surface `health_snapshot()`)
- New tests under `tests/titan_protocol/bridge/` and `tests/titan_protocol/market_data_ingestion/` for the new endpoint and the fail-closed loop behavior.

**Boundaries (what this change explicitly does NOT do):**
- Does not modify Evidence, Market Intelligence, Strategy, Risk,
  Compliance, or Execution Validator logic.
- Does not modify `MarketDataIngestionEngine`'s validation, ordering,
  normalization, freshness, or warmup logic — reused exactly as built.
- Does not add a second market-data path, cache, or provider — MT5 via
  the EA is the only source this plan wires in (external provider was
  explicitly declined as the approach for this round).
- Does not enable real-money trading by itself — `EmergencyDisable`,
  demo-account use, and every existing Risk/Compliance gate remain the
  actual safety boundary; this plan only makes sure they receive real
  data to evaluate instead of none.
- Does not proceed to implementation before an ADR-023 Amendment
  documenting the new EA↔Bridge message type is written and accepted.

---

## Validation

- `python3 -m compileall titan_protocol tests`:
- `python3 -m unittest discover -s tests/titan_protocol`:
- `python3 scripts/check_architecture.py` (unaffected; run anyway):
- New end-to-end test: EA-shaped payload → Bridge → engine →
  `run_cycle_for_pair()` produces a real `RuntimeAuditRecord` on a demo
  feed.
- New fail-closed test: stale/missing bars → pair's cycle is skipped,
  no trade decision recorded.
- Code Reviewer sign-off:
- Test Results Analyzer sign-off:
- Integration Engineer sign-off (cross-package wiring, per `TEAM.md` §3):
