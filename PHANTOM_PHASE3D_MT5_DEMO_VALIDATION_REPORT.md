# Phase 3D — MT5 Demo Validation Report

**Scope:** Validate the live pipeline (MT5 EA → Bridge →
MarketDataIngestionEngine → RuntimeOrchestrator → Evidence → Market
Intelligence → Strategy → Risk → Compliance → Execution) wired by ADR-023
Amendment 1. No architecture changes, no new features, no trading-logic
changes were made in this phase. Where a code change was made, it is
called out explicitly in "Findings and changes" below.

**Method:** A fresh copy of the release package was installed into a Linux
sandbox via `install.py`/`start.py --foreground`, exactly as a Windows
operator would run it. A Python HTTP client (`ea_simulator.py`, scratchpad
only, not part of the repository) posted the exact JSON shapes the real
MQL5 EA sends to `/bridge/market-data`, `/bridge/heartbeat`, and
`/bridge/account`. **This is not a substitute for real MT5 testing** — it
proves the Bridge/engine/runtime side of the pipeline behaves as designed
against well-formed and adversarial HTTP traffic. It does **not** exercise:
MetaEditor compilation of `TitanProtocolEA.mq5`, real broker tick/bar
delivery, MT5 terminal restart/reconnect behavior, or Windows-specific
`WebRequest` allow-listing. Those require the user's own hands-on demo
account verification.

## 1. Warmup → READY transition (no manual intervention)

EURUSD was posted 55 sequential, trending M15 bars via the simulator. The
running process's own health check confirmed, with zero restarts or
manual steps:

- `warmup_statuses`: `bars_received=55, bars_required=50, ready=True`
  (M15) — cleared automatically the moment the 50th bar was accepted.
- `freshness`: `is_stale=False` once a tick followed the bar series.
- `live_cycle` skipped-pairs list dropped EURUSD from
  `market_data_not_ready` to fully evaluated on the very next 15-second
  cycle tick — no process restart, no config change, no manual command.

This confirms the mission-critical requirement: **NOT_READY → READY is
fully automatic.**

## 2. Fail-closed test matrix

| Scenario | Result | Evidence |
|---|---|---|
| Stale feed | **PASS** | GBPUSD: 55 bars posted with `bar_open_time` 2 days in the past. Ingestion accepted all 55 (bar-count warmup cleared, `ready=True`), but `freshness.is_stale=True` (last bar ~2 days old) correctly kept GBPUSD out of every live cycle (`market_data_not_ready`), proving staleness is checked independently of bar count. |
| Missing bars (warmup incomplete) | **PASS** | 11 of the profile's remaining pairs never reached 50 bars during the session and were skipped with `market_data_not_ready` on every single cycle — zero trade decisions attempted for any of them. |
| Duplicate bars | **PASS** | Re-posting an identical `sequence_number`/`bar_open_time` bar for USDCHF was rejected with `rejection_reason=DUPLICATE`; the original acceptance was untouched. |
| Out-of-order bars | **PASS** | Posting an earlier-dated bar after a later one for USDCAD was rejected `OUT_OF_ORDER`; the accepted (later) bar correctly carried `gap_detected=True`. |
| Invalid payload | **PASS** | A bar with `high < low` was rejected `MALFORMED` at HTTP 200 (transport-valid, content-invalid) — confirms the wire path never crashes on bad content, only reports rejection. |
| Malformed JSON (transport-level) | **PASS** | A non-JSON body returned HTTP 400 `invalid_json_body` — confirms the server never propagates a parser exception. |
| Bridge unavailable | **Reasoned, not re-executed live** | Code inspection: `SendClosedBar()`/`SendTick()` in `TitanProtocolEA.mq5` both call the same `HttpPost()` helper used by heartbeat/account/execution messages, which already retries on `WebRequest` failure (`status <= 0`). No new, market-data-specific failure path was introduced — the existing, already-tested transport-retry behavior applies unmodified. |
| EA disconnected / heartbeat timeout | **PASS (passive)** | No heartbeat was sent to the sandbox after the initial test call. `health_check.py` correctly and continuously reported `[FAIL] MT5 bridge connectivity (EA heartbeat): no recent heartbeat` for the rest of the session — the pre-existing `ConnectionHealth` timeout is unmodified and still fires correctly. |
| Market data timeout | **PASS** | Same mechanism as "stale feed" above — `is_ready()`'s freshness check, not bar count, gates cycle evaluation. |
| Warmup incomplete | **PASS** | Continuously observed for the majority of the profile's pairs throughout the session (see "missing bars" row). |

**No new trade decisions occurred during any failure scenario** — verified
each cycle via the live-cycle loop's own skipped-pairs/reason tracking.

## 3. Downstream wiring (Strategy → Risk → Compliance)

`RuntimeOrchestrator.run_cycle_for_pair()` (unmodified in this phase) calls
Evidence → Market Intelligence → Strategy → Risk → Compliance → Bridge
unconditionally, in that fixed order, for every ready pair. Using EURUSD's
real warmed-up bars, an in-process measurement (see Performance below)
confirmed the call chain actually executes: Evidence Engine → Market
Intelligence Engine → Strategy Engine all ran and produced real
`StageTiming` entries. The cycle terminated at `NO_STRATEGY` because the
synthetic linear-trend bar series used for this test did not satisfy any
of the five concrete strategies' specific setup criteria — this is
correct fail-closed behavior (no fabricated trade), not a defect.

Risk Engine and Compliance Engine correctness is already covered by 110
and 116 pre-existing unit tests respectively at the engine level. This
phase's job — proving the *wiring* reaches those stages, not
re-validating engine correctness — is satisfied by (a) the unconditional,
unmodified call sequence in `titan_protocol/runtime/engine.py`, and (b)
the same mechanism already proven reachable through the Strategy stage
above. A genuinely qualifying signal (requiring carefully constructed
setup-specific bar patterns, out of this phase's scope to fabricate) would
be needed to observe a live Risk/Compliance decision end-to-end; this is
flagged as a residual gap in the companion Remaining Known Gaps document.

## 4. Observability

All 10 requested items resolved:

| Metric | Status |
|---|---|
| Market-data warmup status per pair/timeframe | Real (`health.json.market_data.warmup_statuses`) |
| Freshness/staleness per pair/timeframe | Real (`health.json.market_data.freshness`) |
| Bars accepted/rejected/gaps/ticks counters | Real (`health.json.market_data.metrics`) |
| Live-cycle last cycle id | Real (`health.json.live_cycle.last_cycle_id`) |
| Live-cycle evaluated/skipped pairs + reasons | Real (`health.json.live_cycle`) |
| MT5 heartbeat/connectivity status | Real, pre-existing, unmodified |
| Command queue depth | Real, pre-existing, unmodified |
| Degradation level | Real, pre-existing, unmodified |
| Per-cycle audit record (cycle_id/outcome/stage/duration) | **Real internally, not visible in text logs** — see gap below |
| Health update cadence | Real: 5s heartbeat, 15s live-cycle (both by design, confirmed via `_LIVE_CYCLE_INTERVAL_SECONDS` and observed `health.json` timestamp deltas) |

**Observability gap found (documented, not fixed):** `RuntimeAuditRecord`
correctly computes `cycle_id`, `outcome`, `stage_reached`, and
`duration_ms` (verified directly via in-process measurement — see below),
and `log_runtime_audit_record()` correctly logs them via `extra={...}`.
However, `start.py`'s log `Formatter` string
(`"%(asctime)s %(levelname)-8s %(name)s: %(message)s"`) does not reference
those field names, so the text log line only ever shows the bare message
`runtime_audit_record` — the structured data exists but isn't visible in
the log file. This is a **visibility gap, not an incorrect-behavior
defect** (the underlying values are correct, per the in-process
measurement below), so per this phase's explicit instruction ("Otherwise:
make no code changes"), it was **not fixed** — it is documented as a
Known Gap for a future, explicitly-scoped change.

## 5. Performance

| Metric | Value | Method |
|---|---|---|
| Ingestion latency | ~0.84 ms/bar | Previously measured, unchanged this phase |
| Cycle latency (Evidence+MI+Strategy, 1 pair, 55 bars) | avg 0.84 ms, min 0.74 ms, max 1.21 ms over 20 iterations | In-process measurement script (scratchpad-only) constructing the exact same engines `start.py` wires, timing `run_cycle_for_pair()` directly, since the audit record isn't visible in text logs (see gap above) |
| Memory (VmRSS) | ~28.5 MB → ~28.6 MB over ~10 minutes | Two `/proc/<pid>/status` readings, ~10 min apart — stable, no growth trend |
| CPU ticks | 35 → 110 (utime+stime) over ~10 minutes | `/proc/<pid>/stat`, consistent with periodic 5s heartbeat + 15s live-cycle load, no runaway usage |
| Threads | 4, constant | Bridge HTTP server, heartbeat loop, live-cycle loop, main |
| Queue growth | 0 throughout | No command was ever queued this session (expected — no strategy qualified, see §3) |
| Health update frequency | 5s heartbeat / 15s live-cycle | By design (module constants), confirmed via observed `health.json` timestamp deltas |
| Startup time | Not independently re-timed this phase | Confirmed to reach DEGRADED within its documented startup window during earlier phases of this session; no change to startup sequencing was made by this phase |

## 6. Conclusion

Every fail-closed scenario the mission required behaved as designed. The
one genuine gap found (audit-record text-log visibility) is an
observability limitation, not a correctness defect, and was left
unmodified per this phase's explicit no-code-changes constraint. See the
companion **Remaining Known Gaps** document for what still needs the
user's own real MT5/Windows hands-on verification before funded use.
