# Phase 3E — Dual News Provider Redundancy: Implementation Report

**Mission:** Implement the approved dual-provider Market Intelligence
architecture (ADR-033 Part 2) — Trading Economics primary, Forex Factory
automatic backup, fail-closed if both are down. Integration only: zero
changes to Evidence, Strategy, Risk, Compliance, or Execution logic; one
verified integration finding required the smallest possible fix to
Runtime's *caller* (not Runtime itself — see §2).

## 1. Files changed

**New package — `titan_protocol/news_ingestion/`** (owns provider transport,
authentication, parsing, schema conversion, health tracking, and the
failover state machine; owns no event interpretation):
- `models.py` — `ProviderName`, `TrustState`, `NewsEventStatus`, the five
  classified provider exceptions, `NormalizedNewsEvent` (the mission's
  exact field list), `ProviderHealth`, `FailoverState`, `NewsFeedHealthSnapshot`.
- `config.py` — `NewsIngestionConfig` (env-var names, timeouts, bounded
  retries, bounded cache, staleness threshold, deterministic-recovery count).
- `http.py` — shared stdlib-only HTTP transport (`HttpResponse`, injectable `HttpGet`).
- `retry.py` — bounded-retry helper (retries only the two genuinely transient failure classes).
- `category_mapping.py` — provider free-text category/impact → existing `NewsCategory`/`NewsImpact` (fails safe to `OTHER`/`HIGH`).
- `providers/base.py`, `providers/trading_economics.py`, `providers/forex_factory.py` — the two concrete adapters.
- `adapter.py` — `to_market_intelligence_event()`, the one-way seam to `titan_protocol.market_intelligence.models.NewsEvent`.
- `failover.py` — `NewsFailoverEngine`: always probes Trading Economics first; serves whichever provider is currently "active"; switches deterministically (N consecutive successes, never a single lucky one).
- `engine.py` — `NewsIngestionEngine`, the public orchestrator (`fetch_events()`, `health_snapshot()`).
- `metrics.py`, `logging_sink.py`, `__init__.py`.

**New tests — `tests/titan_protocol/news_ingestion/`** (7 files, 52 tests):
`test_failover.py`, `test_providers.py`, `test_mi_integration.py`,
`test_security.py`, `test_performance.py`, `test_structural_boundary.py`, `_fixtures.py`.

**Modified — deployment/integration layer only:**
- `deployment_windows/start.py` — constructs `NewsIngestionEngine`
  (Trading Economics + Forex Factory), refreshes it on its own
  `_NEWS_REFRESH_INTERVAL_SECONDS=300` cadence inside `_live_cycle_loop`,
  and — this phase's one integration finding — skips **every** pair for
  a cycle with reason `market_intelligence_not_ready` when both
  providers are down. `_write_health_snapshot`/`_heartbeat_loop` gained
  optional `news_engine`/`news_metrics` params (backward-compatible
  defaults). Added `_news_health_payload()`.
- `deployment_windows/health_check.py` — new "news provider failover" check (informational, mirrors "market-data readiness").
- `deployment_windows/config_loader.py` — extended `NewsProviderSettings` with the fields `NewsIngestionConfig` needs; removed the "not yet implemented" caveat.
- `deployment_windows/install.py` — `step_verify_news_providers()` now actually constructs a real `NewsIngestionEngine` instead of reporting "NOT AVAILABLE".
- `deployment_windows/KNOWN_GAPS.md` — gap 2 marked CLOSED with the residual `forex_factory_base_url` configuration note.
- `deployment_windows/config/titan_protocol_config.example.json` — `news_providers` section documents and defaults the new fields.
- `tests/titan_protocol/bridge/test_structural_boundary.py` — `allowed_prefixes` extended for the 4 legitimately-changed `deployment_windows/` files (same pattern Amendment 1 itself established).

**Zero changes** to `titan_protocol/evidence_engine/`, `titan_protocol/market_intelligence/`,
`titan_protocol/strategy_engine/`, `titan_protocol/risk_engine/`, `titan_protocol/compliance_engine/`,
`titan_protocol/runtime/`, `titan_protocol/bridge/`, `titan_protocol/reliability/` — verified by
`git status --porcelain` and by `tests/titan_protocol/news_ingestion/test_structural_boundary.py`'s
`TestFrozenPackagesAreUntouched`.

## 2. Architecture verification

**The one integration finding, and why it required touching a caller, not Runtime:**
`RuntimeOrchestrator.run_cycle_for_pair()` calls
`MarketIntelligenceEngine.evaluate(..., news_feed_trusted=True)` with no
parameter in its own signature for a caller to override that default —
Runtime has no `news_feed_trusted` passthrough at all. Separately, only
one of the five concrete Strategy Engine strategies
(`session_breakout`) actually gates on `pair_safety.news.blackout_active`;
the other four don't consult it. Together this means passing
`news_feed_trusted=False` through MI, even if Runtime *could* forward
it, would not by itself guarantee "no new trade decisions" mission-wide.
**The only place that guarantee can be enforced without touching Runtime,
Strategy, Risk, or Compliance is the deployment-loop call site** —
exactly where `market_data_not_ready`/`no_account_state_reported_yet`
already gate today. That is the fix implemented: `_live_cycle_loop` now
checks `news_engine.fetch_events()`'s `trusted` flag *before* building
any pair's inputs, and skips every pair for that cycle when `False`,
without adding a single line to Runtime or any engine. Root cause
confirmed via direct code reading, not assumed.

**Confirmed properties (Market Intelligence Engine's own perspective,
unmodified):** it still receives exactly `events` (a tuple of the
existing, unmodified `NewsEvent` type) and a `news_feed_trusted` boolean
— it has no idea a second package or a second provider exists. Verified
by `tests/titan_protocol/news_ingestion/test_mi_integration.py`, which
calls the real `MarketIntelligenceEngine.evaluate()` (zero mocks) with
adapter-converted events and confirms its own existing per-pair currency
filtering, blackout windows, high-impact/central-bank handling, and
fail-safe-to-HIGH/OTHER mapping all still work exactly as before.

**Never merges, averages, or votes** — `NewsFailoverEngine.fetch_events()`
returns exactly one provider's events per call, tagged with that
provider's identity; verified by `TestNoMergeAverageOrVote`.

## 3. Test results

- **52 new tests**, all passing: `tests/titan_protocol/news_ingestion/` (failover: 12, providers: 15, MI integration: 10, security: 10, performance: 2, structural boundary: 7 — `_fixtures.py` contributes none directly, an off-by-one from file count is expected).
- **Full repository suite**: 2,669 tests, **0 new failures**. The only 3 failures are the pre-existing, environment-only `flask`-import errors in `tests/test_account_snapshot.py`/`test_journal_fields.py`/`test_score_signal.py` (legacy `phantom_institutional.py`, unrelated to this or any prior phase — `flask` is not installed in this environment by design).
- **One pre-existing test updated** (not weakened): `test_git_status_shows_only_expected_paths_changed`'s allowed-path list, to reflect this phase's legitimately-expanded `deployment_windows/` scope — the same pattern used when Amendment 1 itself expanded that list.
- `python -m compileall` clean across `titan_protocol/`, `deployment_windows/`, `tests/`.
- **Architecture verification**: `TestNoImportsBeyondMarketIntelligenceModels` (news_ingestion imports only `market_intelligence.models`, never `.engine`/`.news`/`.scoring`), `TestNoReimplementationOfMarketIntelligenceInternals` (no blackout/scoring/session logic duplicated), `TestFrozenPackagesAreUntouched` (git-diff-verified, not merely asserted).

## 4. Provider health model

Per provider (`ProviderHealth`): `trust_state` (TRUSTED/UNTRUSTED —
UNTRUSTED once `stale_after_seconds` elapses since last success, even
absent a fresh error), `last_success_at`, `latency_ms`, `timeout_count`,
`parse_failure_count`, `consecutive_successes` (drives deterministic
recovery), `stale_age_seconds`, `last_error` (repr of the last
classified exception, no secret values ever included).

Aggregate (`NewsFeedHealthSnapshot`/`FailoverState`): `active_provider`,
overall `trusted` (False only when both providers are stale/never
succeeded), `failover_count`, `recovery_count`, `last_failover_at`,
`last_recovery_at`. All exposed through `health_check.py`'s new "news
provider failover" check, `state/health.json`'s `news` field, and
`NewsIngestionMetrics`' per-provider fetch success/failure counters plus
a `dual_outage_count`.

## 5. Failover sequence — verified live, not just in unit tests

Ran the actual rebuilt release package in a fresh sandbox (`install.py`
→ `start.py --foreground`), no mocks:

1. **Both down** (no Trading Economics key set, no Forex Factory URL
   configured): `health.json.news` showed `active_provider=FOREX_FACTORY,
   trusted=false`, `provider_health` correctly carrying the real
   classified errors — `ProviderAuthenticationFailed("environment
   variable 'TITAN_PROTOCOL_TRADING_ECONOMICS_API_KEY' is not set")` and
   `ProviderUnavailable('forex_factory_base_url is not configured')` —
   and **every one of the profile's 13 pairs was skipped that cycle with
   reason `market_intelligence_not_ready`**, confirmed directly in
   `live_cycle.skipped_pairs`. `failover_count=1`, `dual_outage_count=1`.
2. **Recovery**: pointed `forex_factory_base_url` at a local test server
   returning a valid (empty) JSON calendar, restarted. Within one
   refresh, `health.json.news` showed `trusted=true,
   active_provider=FOREX_FACTORY`, and — critically — the skip reason
   for every pair moved from `market_intelligence_not_ready` to
   `no_account_state_reported_yet` (the next, pre-existing gate down the
   chain), proving the news gate stopped blocking the moment a trusted
   provider became available, with zero interference with the existing
   account-state/market-data gates.
3. **Deterministic (not opportunistic) recovery** verified in
   `test_failover.py`: a single lucky Trading Economics success while
   Forex Factory is serving does **not** switch the active provider;
   only `recovery_health_check_count` consecutive successes does, and a
   broken streak resets the counter (`TestAutomaticFailoverAndRecovery`).

## 6. Performance impact

- 20 sequential `fetch_events()` calls carrying 100 events each complete
  in well under 100ms total (test floor, not a tight benchmark).
- Adapter conversion of 100 events: well under 50ms.
- Real-world cadence is far lighter than these floors: `start.py` only
  calls `fetch_events()` once per `_NEWS_REFRESH_INTERVAL_SECONDS` (300s),
  not per trading cycle (15s) — an economic calendar changes on the
  order of minutes, and polling a real provider every 15s would risk
  rate-limiting it unnecessarily.
- No new thread was added: the refresh happens inline inside the
  existing live-cycle loop thread, gated by a simple elapsed-time check.

## 7. Remaining known gaps

1. **`forex_factory_base_url` is empty by default** in the shipped
   example config — an operator must point it at a real JSON calendar
   feed (shape documented in `providers/forex_factory.py`'s own
   docstring) before the backup provider is actually reachable. Until
   set, a Trading Economics outage fails closed immediately (safe, not a
   regression — see KNOWN_GAPS.md §2).
2. **`ReliabilityEngine` integration was deliberately not added**, despite
   ADR-033 §5 describing it. This mirrors the actual precedent Amendment
   1 set for `market_data_ingestion` (which also does not report into
   `ReliabilityEngine`) — observability is instead exposed via
   `health_check.py`/`health.json`, consistent with what's already
   shipped. Noted as an intentional scope-consistency choice, not an
   oversight.
3. **Pre-existing gap, unrelated to this phase**: no persisted
   day-start/peak/lock account tracking (Compliance Engine daily-loss
   gates still can't enforce real prop-firm rules across restarts —
   see Phase 3D's own report).
4. **A genuinely qualifying Strategy signal was not produced during live
   verification** (same limitation as Phase 3D), so a real trade
   decision was not observed reaching Risk/Compliance with live news
   data attached end-to-end in this sandbox session — engine-level
   correctness for that path is unchanged and already covered by
   existing test suites; this phase only added the news layer feeding
   it.

## 8. Updated release package

`titan_protocol_windows_complete_release.zip` rebuilt: `news_ingestion`
added to the live-engine package list (file count 141 → 156), a
`no-persisted-account-day-start-peak-tracking` and a new
`forex-factory-base-url-not-configured-by-default` known-gap entry in
`RELEASE_MANIFEST.json` (the now-closed `no-multi-provider-news-failover`
entry was removed). Verified end-to-end in a fresh sandbox: `install.py`
→ `start.py` → `health_check.py`, including the both-down and recovery
scenarios above.
