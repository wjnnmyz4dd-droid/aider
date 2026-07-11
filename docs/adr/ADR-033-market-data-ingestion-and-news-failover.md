# ADR-033 — Market Data Ingestion & News Provider Failover

Status: Accepted

Acceptance Date: 2026-07-11

Accepted By: Software Architect / Phantom Engineering Council (full
spec supplied in one message, per the `ADR-029`/`ADR-030`/`ADR-031`/
`ADR-032` "complete spec accepted in one pass" precedent).

Owner: Backend Architect (transport/normalization/ordering — a data
pipeline concern) jointly with SRE (feed health, failover state,
Reliability integration).

Reviewed by: Software Architect (mandatory cross-cutting reviewer),
Minimal Change Engineer (Consulted — this ADR's own scope discipline,
§0, is this role's charter), Application Security Engineer (Consulted
— §8 Security Model: API keys, payload validation, bounded retries).

Depends on: `ADR-024` Evidence Engine, `ADR-025` Market Intelligence
Engine, `ADR-031` Runtime Orchestrator, `ADR-032` System Reliability
Engine (all Accepted — this ADR feeds all four, modifies none).

---

## 0. Scope discipline (read first)

Phase 3B's `PHANTOM_MT5_DEPLOYMENT_AUDIT.md` and
`deployment_windows/KNOWN_GAPS.md` named exactly two gaps:

1. No production live-market-data ingestion path into Runtime.
2. Market Intelligence has no approved primary/backup news-provider
   design.

**This ADR closes exactly those two gaps and nothing else.** No
strategy is added, no trading rule is changed, no existing engine is
redesigned. Per the mission's own explicit constraint, **Evidence
Engine, Market Intelligence Engine, Strategy Engine, Risk Engine,
Compliance Engine, Runtime Orchestrator, Bridge, and Reliability Engine
are all frozen for this phase** — verified true at the end of this
document (§11) via `git diff --stat`, not merely asserted.

Both new packages are built to be consumed by, not merged into, the
frozen pipeline:

- **`phantom/market_data_ingestion/`** owns transport, validation,
  normalization, ordering, freshness, deduplication, and warmup
  tracking for OHLCV bars (and, where genuinely required, ticks). Its
  only output relevant to Evidence Engine is `phantom.evidence_engine.
  models.Bar` — the exact, unmodified, already-existing type Evidence
  Engine's `evaluate()`/`evaluate_snapshot()` already accept. Evidence
  Engine remains the only authority that interprets market data (ADR-
  024 Hard Rule, unchanged); this package never scores, classifies
  trend, or detects structure.
- **`phantom/news_ingestion/`** owns the Trading Economics/Forex
  Factory provider abstraction, health tracking, and the failover state
  machine. Its only output relevant to Market Intelligence is
  `phantom.market_intelligence.models.NewsEvent` (adapted down from a
  richer internal `NormalizedNewsEvent`) plus the existing
  `news_feed_trusted: bool` flag `MarketIntelligenceEngine.evaluate()`
  already accepts. Market Intelligence Engine's own news/blackout/
  scoring logic (`news.py`, `peg_policy.py`) is untouched — it already
  consumes only normalized `NewsEvent`s and a trust boolean, which is
  exactly what "must consume only normalized events, no provider-
  specific parsing logic" requires; nothing needed to change there.

Both packages integrate with the frozen Reliability Engine **only**
through its existing public API (`report_heartbeat(component, now)`) —
no new field, method, or behavior is added to `phantom/reliability/`.
Richer feed/provider health detail (per-symbol freshness, provider
trust state, failover count) lives entirely in each new package's own
health-snapshot type, mirroring how `RuntimeAuditRecord`/`CycleReport`
carry Runtime's own rich detail while Reliability consumes only a
summarized heartbeat.

**Runtime Orchestrator is not modified.** `run_cycle_for_pair()`
already takes bars/events/spread/portfolio/account state as caller-
supplied arguments — that is precisely the seam this ADR's new
packages feed. Actually driving a continuous live cycle loop (wiring
ingestion output into a running supervisory loop) is `deployment_
windows/run_phantom.py`'s concern, extended in this phase (see §9);
still not a Runtime code change.

## 1. Mission

Provide the minimum infrastructure required to deliver validated,
normalized, fresh, ordered live market data and failover-protected news
events to the existing, frozen pipeline — closing the two gaps named
above, without adding trading features, licensing, dashboards, cloud
services, or commercial capability.

## 2. Data ownership (unchanged division of responsibility)

- **MT5 owns raw broker data** — ticks, bars, timestamps, bid/ask. This
  ADR does not change what MT5 sends; it changes how Phantom receives
  and prepares it.
- **`phantom/market_data_ingestion/` owns**: transport (receiving raw
  bar/tick payloads), validation, normalization (to `Bar`), ordering
  (sequence/out-of-order/duplicate detection), freshness (staleness
  detection), deduplication, and warmup tracking.
- **`phantom/news_ingestion/` owns**: provider transport (HTTP to
  Trading Economics/Forex Factory), schema validation, normalization
  (to `NormalizedNewsEvent`, then adapted to `NewsEvent`), provider
  health tracking, and the failover state machine.
- **Evidence Engine remains the only authority that interprets market
  data.** Neither new package computes trend, structure, liquidity,
  candlestick patterns, or any score.
- **Market Intelligence Engine remains the only authority that
  interprets news/session/liquidity/market-safety facts into pair
  safety.** `phantom/news_ingestion/` never computes a blackout
  decision, a news score, or a trade-readiness verdict — it only
  supplies events and a trust boolean.
- **Runtime coordinates calls but never interprets prices or news.**
  Unchanged.

## 3. Part 1 — Market Data Ingestion

### 3.1 Supported data

Per bar: symbol, timeframe, OHLCV, broker timestamp, bid, ask, spread,
bar-open time, closed-bar vs. forming-bar status, sequence number,
source timestamp, ingestion timestamp. Tick data is supported only for
the one purpose Runtime's own `run_cycle_for_pair()` signature actually
needs a scalar (not bar-series) value for: `current_spread`/
`average_spread` — ticks are never retained as a history, only the
latest bid/ask and a bounded rolling spread average are tracked per
symbol.

### 3.2 Public interface

`phantom.market_data_ingestion.engine.MarketDataIngestionEngine`:

- `ingest_bar(raw: RawBar, now: datetime) -> IngestionResult` —
  validates, checks ordering/duplication, updates warmup and freshness
  state; on success (and only for a closed bar) appends the normalized
  `Bar` to that (symbol, timeframe)'s bounded retention buffer.
- `ingest_tick(tick: TickEvent, now: datetime) -> IngestionResult` —
  updates the latest bid/ask/spread for that symbol.
- `backfill(symbol, timeframe, bars: Sequence[RawBar]) -> WarmupStatus`
  — startup historical warmup; validates continuity, never fabricates
  missing bars.
- `is_ready(symbol, timeframe) -> bool` — `True` only once warmup's
  minimum-history requirement is satisfied for that (symbol, timeframe)
  and the feed is not currently stale.
- `get_bars(symbol, timeframe) -> Tuple[Bar, ...]` — the exact type
  Evidence Engine's `evaluate()`/`evaluate_snapshot()` accept.
- `latest_spread(symbol) -> Optional[Tuple[float, float]]` —
  `(current_spread, average_spread)`, or `None` if no tick/bar has
  established a spread yet.
- `warmup_status(symbol, timeframe) -> WarmupStatus`
- `health_snapshot(now) -> MarketFeedHealthSnapshot`

### 3.3 Fail-closed rules (§ "FAIL-CLOSED RULES" of the mission,
verbatim, each with its enforcement point)

| Condition | Enforcement |
|---|---|
| Stale feed | `is_ready()` returns `False`; `health_snapshot()` reports the stale (symbol, timeframe) with an explicit reason |
| Required timeframe missing | `is_ready()` checks every timeframe in `MarketDataIngestionConfig.required_timeframes` for that symbol |
| Symbol data incomplete | Same — per-timeframe `is_ready()` |
| Timestamps move backward | `ordering.py` rejects with `RejectionReason.OUT_OF_ORDER`, bar never enters the retention buffer |
| Bar sequence corrupted | `ordering.py` rejects with `RejectionReason.OUT_OF_SEQUENCE` when `sequence_number` doesn't monotonically follow the last accepted one for that (symbol, timeframe) |
| Spread data unavailable | `latest_spread()` returns `None`; the caller (deployment layer) must treat this the same as "not ready" before invoking Runtime |
| Clock synchronization untrusted | `validation.py` rejects a bar whose `ingestion_timestamp - source_timestamp` (or `broker_timestamp` vs. the ingestion engine's own clock) exceeds `max_clock_skew_seconds`, reason `CLOCK_SKEW` |

Every rejection produces an `IngestionResult(accepted=False,
rejection_reason: RejectionReason, reason_detail: str)` — never a
silent drop. Existing open positions are untouched by any of the
above: this package has no authority over position management at all
(Compliance/Bridge already own that, unmodified).

### 3.4 Warmup

`phantom.market_data_ingestion.warmup.WarmupTracker`: per (symbol,
timeframe), tracks count of real, validated, closed bars received
against `MarketDataIngestionConfig.min_warmup_bars_by_timeframe`. The
minimum is derived from Evidence Engine's own real lookback
requirements (`EvidenceEngineConfig.internal_structure_lookback = 5`
plus headroom for `support_resistance.py`'s clustering and
`volatility.py`'s ATR window) — a documented, conservative default,
not an arbitrary number. `NOT_READY` until satisfied; **never
fabricates a missing bar** to reach the threshold faster. Warmup status
is exposed per (symbol, timeframe) via `warmup_status()`.

## 4. Part 2 — News Provider Failover

### 4.1 Provider abstraction

`phantom.news_ingestion.providers.base.NewsProvider` (a `Protocol`):
one method, `fetch(now: datetime) -> Tuple[NormalizedNewsEvent, ...]`,
raising one of `ProviderUnavailable`, `ProviderTimeout`,
`ProviderRateLimited`, `ProviderAuthenticationFailed`, or
`ProviderSchemaError` on failure — never a bare, unclassified
exception, since the failover state machine's routing decision depends
on knowing *why* a provider failed.

Two concrete implementations, `TradingEconomicsProvider` and
`ForexFactoryProvider`, both stdlib-only (`urllib.request`), both
taking an **injectable `http_get` callable** (mirrors `phantom.
reliability.resource_monitor`'s injected-sampler pattern) so tests
never perform a real network call, while a real default implementation
exists for production use.

### 4.2 Primary/backup behavior

`phantom.news_ingestion.failover.NewsFailoverEngine`:

- Uses Trading Economics whenever `ProviderHealth.trust_state` for it
  is `TRUSTED` (last fetch succeeded within `stale_after_seconds`, no
  open authentication failure).
- Switches to Forex Factory the moment Trading Economics raises any of
  the six named failure classes.
- **Never merges, never averages, never votes** — `fetch_events()`
  returns exactly one provider's events at a time, tagged with
  `source: ProviderName`.
- Recovery is deterministic, not opportunistic: once Trading Economics
  has produced `recovery_health_check_count` (config, default 3)
  consecutive successful fetches, the engine switches back to it on
  the next scheduled fetch — never mid-fetch, never based on a single
  lucky success (avoids flapping).
- If **both** providers are unavailable/untrusted: `fetch_events()`
  returns `(events=(), trusted=False)`. The caller must pass
  `news_feed_trusted=False` to `MarketIntelligenceEngine.evaluate()` —
  MI's own existing fail-closed path (blackout, score=0) then applies,
  unchanged.

### 4.3 Normalized news event

`phantom.news_ingestion.models.NormalizedNewsEvent`: `event_id,
currency, country, event_name, category, impact, scheduled_time,
actual, forecast, previous, revision, source, source_timestamp,
ingestion_timestamp, confidence, freshness, status` — every field the
mission named. `phantom.news_ingestion.adapter.to_market_intelligence_
event()` maps this down to the existing, unmodified `phantom.
market_intelligence.models.NewsEvent` (`event_id, currency, category,
impact, scheduled_at, released, released_at`) via `category_mapping.py`
(free-text provider category/impact strings → the existing
`NewsCategory`/`NewsImpact` enums, unmapped values failing safe to
`NewsCategory.OTHER`/`NewsImpact.HIGH` — HIGH, not LOW, because an
unclassifiable impact must be treated as the more cautious case, never
silently assumed harmless).

### 4.4 Pair-specific news (unchanged, since MI already does this)

`phantom/news_ingestion/` never introduces a global news score —
matching MI's own existing per-pair design (`pair_currencies()`
filters events to a pair's own two currencies before any blackout/score
computation, ADR-025 Hard Rule 2, untouched). Pair-specific blackout
windows, high-impact blocking, central-bank blocking, peg/policy holds,
and session-aware evaluation are all MI's existing, frozen logic —
this ADR supplies it better events, never new blackout rules.

### 4.5 News health

`phantom.news_ingestion.models.NewsFeedHealthSnapshot`: active
provider, per-provider `ProviderHealth` (last successful fetch, latency,
timeout count, parse-failure count, stale-data age, authentication
state, trust state), `FailoverState` (failover count, recovery count,
last transition timestamps). Exposed via `NewsIngestionEngine.
health_snapshot(now)`.

## 5. Reliability integration

Both new engines' own health-monitoring loops call the frozen
`ReliabilityEngine.report_heartbeat(component, now)` with descriptive
component names (`"market_data_ingestion"`,
`"news_ingestion_trading_economics"`,
`"news_ingestion_forex_factory"`) — using the existing public API only.
`ReliabilityEngine.attempt_recovery()`'s existing `APPROVED_RESTART_
COMPONENTS` allow-list (`evidence_engine`, `market_intelligence`,
`strategy_engine`, `risk_engine`) is unchanged and deliberately does
**not** include either new component — restarting a data-ingestion
process is an infrastructure concern for the deployment layer/operator,
not something this ADR grants Reliability new authority over, and
Reliability continues to never bypass Market Intelligence, Risk, or
Compliance (unchanged, since nothing here touches Reliability's
decision surface at all).

## 6. Security model

- **No API keys in source code.** `NewsIngestionConfig.trading_
  economics_api_key_env_var` names an environment variable; the actual
  key is read at call time via `os.environ.get(...)`, never hardcoded,
  never written to a config file this ADR ships.
- **Never logged.** Every log statement referencing a provider request
  logs the URL host/path and status only, never headers or query
  parameters that could carry the key.
- **All external payloads validated** against an explicit expected
  JSON shape before any field is read; a shape mismatch raises
  `ProviderSchemaError` (triggers failover), never a partial/garbage
  parse.
- **Bounded retries** (`NewsIngestionConfig.max_retries`, default 2,
  with `retry_backoff_seconds` between attempts) — never an unbounded
  retry loop.
- **Bounded caches** — `NewsIngestionConfig.cache_max_entries` caps the
  in-memory normalized-event cache, evicting oldest first (mirrors
  `phantom.market_intelligence.engine._NewsFeedCache`'s own bounded-
  cache pattern).
- **Timeouts** on every HTTP call (`request_timeout_seconds`).
- **Reject unexpected content types** — a response whose
  `Content-Type` isn't `application/json` (or absent) raises
  `ProviderSchemaError` before any parse is attempted.
- **Audit provider failover and recovery** — every transition is logged
  through the new package's own `logging_sink.py` with the failure
  class that triggered it.

## 7. Testing (per mission's own list, §"TESTING")

Both packages ship unit, integration, malformed-data, duplicate/out-
of-order/missing-bar/stale-feed, warmup, concurrency, architecture-
boundary, and regression tests; `news_ingestion` additionally ships
provider-timeout, failover, recovery-to-primary, dual-provider-outage,
pair-specific-news, and security tests. A dedicated end-to-end suite
drives a real `RuntimeOrchestrator.run_cycle_for_pair()` call with
ingestion-produced `Bar`/`NewsEvent` data to prove the seam actually
works, not just each package in isolation. See the Phase 3C deliverables
report for exact counts and results.

## 8. Acceptance criteria

- Zero modification to `phantom/evidence_engine/`, `phantom/
  market_intelligence/`, `phantom/strategy_engine/`, `phantom/
  risk_engine/`, `phantom/compliance_engine/`, `phantom/runtime/`,
  `phantom/bridge/`, `phantom/reliability/` (verified by `git diff
  --stat`).
- Both new packages compile clean, zero third-party dependencies,
  zero import of `phantom_pipeline`.
- Fail-closed behavior for every named condition is covered by a
  deterministic test, not merely asserted in prose.
- Warmup never fabricates a bar; `NOT_READY` is a real, checkable
  state, never silently bypassed.
- News failover never merges/averages/votes; recovery to primary is
  deterministic per §4.2, not opportunistic.
- Full repository test suite remains green (excluding the three
  pre-existing, environment-only `flask`-import failures unrelated to
  this or any prior phase).
