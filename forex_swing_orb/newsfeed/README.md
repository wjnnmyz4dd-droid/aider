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
- **Staleness still blocks:** `as_of` is the acquisition time, so a preserved
  last-known-good file eventually ages past the compliance `max_age` and the
  existing gate fails closed. Preservation can never keep trading on stale news.
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

## Tests

`tests/test_newsfeed_9dr1.py` — 64 deterministic tests (no internet): normalization
& impact, provenance & integrity, freshness, every failure mode, atomic write &
last-known-good, restart, retries/backoff/shutdown, config fail-closed, the
network/authority/security boundaries, and the end-to-end integration through the
real `FileNewsDataProvider` + `compliance/news.py` (HIGH event blocks a relevant
pair; unrelated currency does not; disabling preserves the manual workflow).

Run: `pytest forex_swing_orb/newsfeed/tests`
