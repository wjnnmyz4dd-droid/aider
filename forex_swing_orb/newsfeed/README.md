# Session Edge — Autonomous Economic-Calendar Acquisition (Phase 9D-R1)

**DEMO-ONLY. DATA-ONLY.** Closes audit gap **D-1**: Session Edge can now
autonomously obtain, normalize, verify, persist, refresh, and health-check the
economic-calendar data the **existing** compliance news gate consumes — without a
human editing files.

This layer supplies data. It never approves/rejects trades, computes signals, or
changes compliance/risk/positions. **`compliance/news.py` remains the sole
trade-blocking news authority.**

## Architecture (one-way data flow)

```
external source
  → CalendarProvider              (the ONLY networking seam — http_provider.py)
  → freshness / validation        (freshness.py — fail closed)
  → normalization                 (normalize.py — impact/currency/ids; D-2)
  → provenance + integrity digest (acquire.py)
  → atomic news_file              (writer.py — temp+fsync+rename; last-known-good)
  → existing FileNewsDataProvider (live/providers.py — UNCHANGED)
  → existing compliance/news.py   (UNCHANGED — the sole news authority)
  → existing compliance decision
```

The acquirer runs as its **own process** (`python -m forex_swing_orb.newsfeed`),
separate from the producer, so acquisition failure cannot crash trading.

## Provider selected: ForexFactory weekly JSON — and why

Free, no API key, stable schema, currency-coded events with `forecast`/`previous`
(and `actual` after release). The HTTP call is **host-locked** to
`nfs.faireconomy.media`, bounded by timeout, refuses cross-host redirects, and is
**injectable** so tests never touch the network. A local `StaticFileCalendarProvider`
and an `InjectableCalendarProvider` cover offline/deterministic use.

## Normalized bundle (schema_version 2)

Additive to the v1 bundle the gate already reads — every extra key is ignored by
`compliance/news.py`:

```jsonc
{
  "schema_version": 2,
  "as_of": "<ISO-Z acquisition time>",   // drives existing compliance freshness
  "verified": true,                      // bundle-level fallback (true iff trusted source)
  "provenance": { source_name, source_identifier, source_as_of, fetched_at,
                  normalized_at, bundle_as_of, provider_version, schema_version,
                  completeness, event_count, trusted_source, normalization_warnings },
  "events": [ { event_id, event_name, country, currency,
                impact: "HIGH|MEDIUM|LOW", event_timestamp, verification_state,
                previous, forecast, actual, revision,   // informational only
                source_event_key } ],
  "integrity_digest": "<sha256>"          // tamper-evident; gate does not require it
}
```

## Guarantees

- **Impact (D-2):** every provider encoding (`High/high/H/3/RED/…`) is normalized
  to canonical `HIGH/MEDIUM/LOW` before the gate sees it. **Unknown** impact →
  conservative **HIGH** (never a silent downgrade) + a recorded warning.
- **Provenance/identity:** stable per-event id (`sha256(source|currency|name|ts)`);
  a repeated id with **differing content fails closed** (never merged).
- **Freshness (fail closed):** missing/future/stale source timestamps, empty/
  malformed payloads, invalid currency/impact/timestamp, non-finite result values,
  duplicate conflicts — all raise and **preserve the last-known-good file**.
- **Freshness is earned, not assumed (F-2):** the bundle's authoritative `as_of`
  is the **effective calendar freshness**, not the download time. It is derived from
  an upstream generated timestamp when present, otherwise from the fetch time **only
  after a COVERAGE check proves the payload is the calendar for the current period**
  (its event span, day-snapped, must include `now`). A successfully-downloaded
  **wrong-week** calendar → `COVERAGE_INVALID` fail closed; freshness that cannot be
  established → `SOURCE_FRESHNESS_UNESTABLISHED` fail closed. In both cases the
  last-known-good file is left untouched, ages past the compliance `max_age`, and the
  existing gate blocks. A repeated HTTP 200 of stale (wrong-week) content can never
  keep trading enabled. A `content_hash` (current/previous/changed/last-change) is
  recorded as provenance — unchanged content is NOT treated as automatically stale
  (weekly calendars legitimately don't change).
- **Completeness (D-3):** reported honestly (`unestablished` for the weekly feed) —
  never claimed just because a fetch succeeded. Cross-source verification is
  wired as an architectural seam (`corroborators`), unused by default.
- **Result fields:** `previous/forecast/actual/revision` are captured when supplied
  but are **informational only** — no gate/strategy/risk/PM logic reads them.

## Configuration (self-contained, fail closed)

Env (or JSON via `SESSION_EDGE_CONFIG`; unknown keys fail closed):

| Env var | Meaning | Default |
|---|---|---|
| `SESSION_EDGE_CALENDAR_ENABLED` | enable acquisition | `false` |
| `SESSION_EDGE_CALENDAR_PROVIDER` | `forexfactory` / `forexfactory_nextweek` / `static` | required when enabled |
| `SESSION_EDGE_CALENDAR_REFRESH_SEC` | refresh interval | `1800` |
| `SESSION_EDGE_CALENDAR_MAX_SOURCE_AGE_SEC` | max `source_as_of` age | `21600` |
| `SESSION_EDGE_CALENDAR_MAX_CLOCK_SKEW_SEC` | future-skew tolerance | `120` |
| `SESSION_EDGE_CALENDAR_OUTPUT_FILE` | news file to write | `SESSION_EDGE_NEWS_FILE` |
| `SESSION_EDGE_CALENDAR_HEALTH_FILE` | health status file | `<news dir>/calendar_acq_status.json` |
| `SESSION_EDGE_CALENDAR_SOURCE_FILE` | raw file (static provider) | — |
| `SESSION_EDGE_CALENDAR_STATIC_TRUSTED` | mark static source trusted | `false` |
| `SESSION_EDGE_CALENDAR_TIMEOUT_SEC` / `_RETRIES` / `_BACKOFF_SEC` | HTTP knobs | `12` / `2` / `2` |

No secrets are stored on the config object, health file, logs, or bundle. Any
future API-key provider must read its key from an env var inside the provider only.

## Disabling

Set `SESSION_EDGE_CALENDAR_ENABLED=false` (default). The service does nothing and
the **existing manual `FileNewsDataProvider` workflow is untouched** — a
hand-maintained news file still reads and gates exactly as before.

## Deployment & supervision (F-4)

The acquirer is a **separate process** from the trading producer (networking must
never be embedded in strategy/compliance/producer). Deploy it under an OS supervisor
that restarts it after a crash and bounds restarts:

- **Windows/VPS (recommended):** a Task Scheduler task running
  `python -m forex_swing_orb.newsfeed` at logon, with *Restart on failure* (e.g.
  every 1 min, up to 3 attempts) and *Do not start a new instance if running*.
  A `single-instance lock` (`calendar_acq.lock`, `SESSION_EDGE_CALENDAR_LOCK_FILE`)
  additionally guarantees at most one instance even if two are launched.
- **Linux:** a `systemd` unit with `Restart=on-failure`, `RestartSec`, and
  `StartLimitBurst`.

Set the refresh interval **below** the compliance `max_age` (default 3600s) so a
coverage-valid calendar stays fresh between refreshes; if the service dies, the file
ages and compliance blocks.

## Operational health (F-6)

`SESSION_EDGE_CALENDAR_HEALTH_FILE` is written atomically each cycle with a single
`status`: `HEALTHY` / `PROVIDER_FAILURE` / `SOURCE_STALE` /
`SOURCE_FRESHNESS_UNESTABLISHED` / `FILE_WRITE_FAILURE`, plus `last_attempt/
last_success/last_failure/last_failure_reason`, `last_failure_detail`, `fetched_at`,
`source_as_of`, `effective_calendar_as_of`, `coverage_start/end/verified`,
`content_hash`, `last_content_change`, `event_count`, `high_event_count`,
`next_refresh`. `last_failure_detail` is a sanitized structured breakdown of the last
failure (e.g. `http_status` for HTTP 403/429/5xx, or `underlying_class` + `errno`/
`winerror` for DNS/TLS/reset/refused) so `ACQ_SOURCE_ERROR` is no longer opaque; it
is cleared on the next successful refresh. The same breakdown is echoed on the
operator `WARNING` line (`code=… http_status=… disposition=FAIL_CLOSED`). A **dead
service** cannot self-report; `derive_service_status(status, now)` returns
`SERVICE_STALE` when `now - last_attempt > 2 * refresh_sec` (rule embedded in the
file as `service_stale_rule`). No credentials are ever written (asserted).

## Live validation (F-1)

`tests/test_newsfeed_9dr1r.py::test_live_forexfactory_probe` contacts the **real**
endpoint through the production hardened fetcher — run only when explicitly enabled:

```
SESSION_EDGE_CALENDAR_LIVE_PROBE=1 pytest \
  forex_swing_orb/newsfeed/tests/test_newsfeed_9dr1r.py::test_live_forexfactory_probe
```

Observed live: HTTP 200 `application/json`, ~99 events, fields
`title/country/impact/date/forecast/previous` (no `actual`/`revision`/generated
timestamp), impacts `High/Medium/Low/Holiday`, current-week coverage verified.

## Completeness (F-3)

`completeness = "unestablished"` and `single_source_completeness_not_provable = true`
for the single free source: a valid current-week calendar can still omit an event,
and that omission is undetectable without a second source. The `corroborators` seam
supports cross-source verification; **SINGLE_SOURCE_COMPLETENESS_NOT_PROVABLE** until
a second source is added (recommended before fully-unattended reliance).

## Tests

`tests/test_newsfeed_9dr1.py` (64) + `tests/test_newsfeed_9dr1r.py` (26, incl. 1
gated live probe) — deterministic, no internet by default: normalization
& impact, provenance & integrity, freshness, every failure mode, atomic write &
last-known-good, restart, retries/backoff/shutdown, config fail-closed, the
network/authority/security boundaries, and the end-to-end integration through the
real `FileNewsDataProvider` + `compliance/news.py` (HIGH event blocks a relevant
pair; unrelated currency does not; disabling preserves the manual workflow).

Run: `pytest forex_swing_orb/newsfeed/tests`
