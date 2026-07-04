# ADR-013 — Data Pipeline

Status: Proposed

Owner: Backend Architect (data contracts/reliability — matches the
ownership `ADR-015` §6 already assigns to the MT5 Broker Feed and
Database entries)

Reviewed by: Software Architect (mandatory — a new stage crossing
package boundaries requires this per `TEAM.md` §3), SRE (Consulted —
health/heartbeat integration with Watchdog, `ADR-011`)

Date: 2026-07-04

Depends on: `ADR-001-single-authority-architecture.md` (Accepted —
this ADR is the formal definition of ADR-001's own first pipeline stage,
named "Market Data" in its diagram), `ADR-002-scanner.md` (Accepted —
§4 already forward-declares this ADR by name as the supplier of
Scanner's inputs; this ADR must match that input contract exactly, not
redefine it), `ADR-006-compliance-engine.md` (Accepted — §2 already
establishes Compliance Engine as a direct, parallel consumer of raw
market data, independent of `ScannerObservation`; see §9 below),
`ADR-007-execution-validator.md` (Accepted — §2's "fresh market
snapshot" requirement is fulfilled by this ADR's `MarketSnapshot`
output), `ADR-008-mt5-bridge.md` (Accepted, including Amendment 1 —
the other stage `ADR-015` §6 permits to open an MT5 connection
directly), `ADR-011-watchdog-recovery.md` (Accepted — this ADR's health
signal is one of the "liveness proxy" per-stage inputs `ADR-011` §2's
boundary note already anticipates), `docs/adr/ADR-015-external-data-
sources-api-governance.md` (Accepted — owns the MT5 Broker Feed/Calendar
vendor relationship, the Adapter Forbidden Responsibilities this ADR's
ingestion adapters must honor, and already states the exact rule this
ADR restates in §1: "Only the Market Data stage and MT5 Bridge touch the
MT5 Broker Feed directly")

---

# Pipeline position

**Market Data** → Scanner → Strategy Engine → Scoring Engine → Risk
Engine → Compliance Engine → Execution Validator → MT5 Bridge →
Position Manager → Analytics

This ADR is the formal definition of the "Market Data" stage `ADR-001`
already named as the pipeline's first stage, and the stage `ADR-002` §4
already forward-referenced by number ("Supplied by the Market Data stage
(ADR-013)"). It defines only this stage. It does not redefine Scanner's
input contract (`ADR-002` §4) — it fulfills it.

---

# 1. Mission

**The Data Pipeline answers exactly one question: "What is the
authoritative market data available to Phantom?"**

**It never answers:** Should we trade? Should we score? Should we size?
Should we execute? Should we manage positions? Those are, respectively,
Strategy Engine's, Scoring Engine's, Risk Engine's, the Execution
Validator's/MT5 Bridge's, and Position Manager's questions — each
already answered by its own Accepted ADR. The Data Pipeline produces
facts about market data; it never interprets them.

**It is the only producer of normalized market data**, and — per
`ADR-015` §6's already-Accepted rule — one of exactly two stages
permitted to open a connection to the MT5 Broker Feed directly (the
other being MT5 Bridge, for order submission, `ADR-008`). No other stage
may open such a connection.

---

# Hard Rules

These override any other requirement in this document if they ever
appear to conflict:

- **The Data Pipeline SHALL NEVER:** generate trade ideas, generate
  `CandidateTrade`s, generate scores, generate risk, generate compliance
  decisions, generate execution decisions, generate AI conclusions,
  generate portfolio decisions, mutate any downstream object, or bypass
  Scanner (§9's multi-consumer model states precisely what "bypass"
  does and does not mean here).
- **Facts only, never fabricated.** A gap-repaired bar, a synthesized
  value, or any non-observed data point must be explicitly flagged as
  such (§7) — never presented indistinguishably from directly-observed
  data. This is the same "never fabricate a plausible-looking reading"
  discipline `ADR-002` §10 already established for Scanner, applied one
  stage earlier.
- **No business, strategy, scoring, risk, compliance, or AI logic in any
  ingestion adapter.** This ADR's adapters are the concrete instance of
  the adapters `ADR-015`'s "Adapter Forbidden Responsibilities" section
  already governs — translation only.
- **Determinism.** Given identical raw inputs (ticks/bars) and
  configuration, historical loading and replay production must be
  byte-for-byte reproducible — the same requirement `ADR-002` §14
  already imposes on Scanner, extended one stage earlier so Scanner's
  own determinism has a deterministic foundation to rest on.

---

# 2. Responsibilities

The Data Pipeline SHALL own:

- Tick ingestion, bar construction, historical loading, historical
  cache.
- Multi-timeframe aggregation.
- Gap detection, gap repair (§7 — bounded and disclosed, never silent).
- Timestamp normalization, timezone normalization.
- Market session normalization, holiday handling, weekend handling.
- Spread normalization, volume normalization, symbol normalization.
- Corporate action handling (future — not designed here; flagged as an
  explicit future concern, not a present gap, since MT5 forex/CFD
  symbols are not corporate-action-bearing instruments in Phantom's
  current scope).
- Data validation, data quality assessment (§7).
- Replay data production, historical replay support (§10).
- Market snapshot generation (§5, §9).

---

# 3. The Data Pipeline shall never

| Forbidden action | Owned instead by |
|---|---|
| Generate trade ideas / `CandidateTrade`s | Strategy Engine (`ADR-003`) |
| Generate scores | Scoring Engine (`ADR-004`) |
| Generate risk | Risk Engine (`ADR-005`) |
| Generate compliance decisions | Compliance Engine (`ADR-006`) |
| Generate execution decisions | Execution Validator (`ADR-007`) |
| Generate AI conclusions | Nobody in the live pipeline — excluded by construction per `ADR-001`'s LLM-free decision path |
| Generate portfolio decisions | Position Manager (`ADR-009`) / future Portfolio Manager (`ADR-017`, recommended, not yet drafted) |
| Mutate downstream objects | Nobody — every downstream object is immutable at its own source stage |
| Bypass Scanner | Nobody — see §9 for exactly what other stages *are* permitted to consume directly, and why that isn't a bypass |

---

# 4. Inputs

- **MT5 Broker Feed** (`ADR-015` §6) — live ticks/bars, spread, and
  `market_status`; the primary live source.
- **Historical Data** — bulk historical OHLCV for backtesting, walk-
  forward validation, and warm-up/cold-start (§11).
- **Replay Data** — previously-captured live data, replayed through the
  same ingestion path for determinism verification (§10).
- **Approved External Market Data (future, via `ADR-015` §12)** — no
  such source is approved today; any addition requires `ADR-015` §12's
  four-step gate before this ADR gains a new input source.

---

# 5. Outputs

One record per event, never discarded — the same discipline established
at every prior stage.

- **`NormalizedTick`** — a single normalized tick: symbol, timestamp
  (timezone-aware), bid/ask (or last/volume as applicable), source.
- **`NormalizedBar`** — a single OHLCV bar, timezone-aware, per symbol
  per timeframe, carrying a quality flag (§7) indicating whether it was
  directly observed or gap-repaired (§7).
- **`MarketSnapshot`** — the shared, instant-in-time object multiple
  stages consume independently for their own purpose (§9): current
  price, current spread, `market_status`, timestamp. This is the object
  Scanner, Compliance Engine, and Execution Validator/MT5 Bridge each
  read on their own cadence — never routed through `ScannerObservation`
  for the latter two.
- **`HistoricalSeries`** — a bounded historical OHLCV series for a
  symbol/timeframe, used for warm-up and backtesting.
- **`ReplaySeries`** — a captured sequence of historical
  ticks/bars/snapshots, replayable through the same ingestion path
  (§10).
- **`DataQualityReport`** — completeness, freshness, latency,
  continuity, and confidence assessment (§7) for a symbol/timeframe over
  a window, distinct from the per-record quality flag on `NormalizedBar`.
- **`PipelineHealth`** — this stage's own operational health signal,
  the input Watchdog (`ADR-011`) observes for this stage (§2's boundary
  note in `ADR-011` already anticipates this).

**Type-level guarantee:** none of these output types is structurally
capable of holding a trade idea, a score, a risk decision, a compliance
verdict, an execution instruction, or a portfolio decision — the same
guarantee established for every prior stage's output type, verified by
a dedicated test (§16).

**Immutability:** every output type, once produced, is immutable — a
record of what was observed (or, for `NormalizedBar`, explicitly
flagged as repaired), never a mutable working object.

---

# 6. Normalization

- **Symbol normalization** — maps broker-specific symbol variants (e.g.
  a broker suffix) to Phantom's canonical symbol identifier. This is
  translation only, per `ADR-015`'s Adapter Forbidden Responsibilities —
  it never encodes which symbols are "tradeable" or "preferred" (a
  Strategy Engine / configuration concern, not this stage's).
- **Timestamp normalization, precision normalization, timezone
  normalization** — every timestamp is converted to a single canonical,
  timezone-aware representation before anything downstream sees it,
  fulfilling `ADR-002` §4's requirement that bars arrive "timezone-aware"
  already.
- **Price precision, volume precision** — normalized to a canonical
  precision per symbol, so downstream stages never need vendor-specific
  rounding logic (the same vendor-independence `ADR-015` §3/§4 requires).
- **Missing bar handling** — see §7's gap detection/repair.
- **Duplicate tick handling** — a repeated tick (same symbol, timestamp,
  and price) is deduplicated at ingestion; counted, not silently dropped
  without a metric (§15).
- **Out-of-order tick handling** — a tick arriving with an earlier
  timestamp than the last-processed tick for that symbol is reordered if
  within a bounded window, or flagged and dropped if outside it — never
  silently accepted as if in-order, which would corrupt bar construction.

---

# 7. Data quality

- **Completeness** — whether all expected timeframes/bars for a
  window are present.
- **Freshness** — time since the last received tick/bar relative to the
  expected update cadence.
- **Latency** — time between a tick's exchange/broker timestamp and its
  ingestion timestamp.
- **Continuity** — absence of gaps in a timeframe's bar sequence.
- **Confidence** — an explicit, structured signal (mirroring
  `ADR-002` §5's qualitative confidence-label discipline) describing how
  much of the above this stage can vouch for, never a numeric score.
- **Gap detection** — a missing bar in an otherwise-continuous sequence
  is detected by timestamp-interval comparison, not inferred from
  downstream symptoms.
- **Gap repair policy** — bounded and explicitly disclosed, never a
  silent fabrication:
  - Only a single missing bar within an otherwise-continuous sequence
    may be repaired (e.g. forward-filled from the prior bar's close);
    multiple consecutive missing bars are never repaired — they are
    reported as a genuine gap (`DataQualityReport`), left absent, and
    flagged for the consuming stage to handle via its own fail-closed
    behavior (e.g. `ADR-002` §9's "missing-timeframe" failure mode).
  - **Every repaired bar carries an explicit `is_repaired` flag on the
    `NormalizedBar` record itself** — a repaired bar is never
    indistinguishable from a directly-observed one to any downstream
    consumer. This is the concrete mechanism behind the Hard Rules'
    "never fabricate" requirement: repair is permitted, silent repair is
    not.
  - Gap repair never occurs during warm-up (insufficient prior bars to
    repair from) — an insufficient-history condition is reported as
    warm-up, per `ADR-002` §9, never papered over with a repaired bar.
- **Validation rules** — reject non-monotonic timestamps, zero/negative
  prices, and impossible OHLC ordering (low > high) at ingestion —
  **the same three checks `ADR-002` §9 lists as Scanner's own failure
  modes.** See §8 for why this is intentional defense-in-depth, not a
  duplicated responsibility.
- **Failure modes** — feed disconnect, malformed record, gap exceeding
  repair policy, symbol not recognized. Every failure mode fails closed:
  the affected symbol/timeframe's data is marked with the specific
  condition, never silently substituted with a plausible-looking value.

---

# 8. Relationship to Scanner's own validation — defense-in-depth, not duplication

**`ADR-002` §9 already lists "malformed candles: non-monotonic
timestamps, zero/negative prices, impossible OHLC ordering" as one of
Scanner's own failure modes — the same three conditions §7 above
requires this stage to reject at ingestion.** This is not a duplicated
responsibility. It is the same reasoning `ADR-008` §7 already applied to
its own two independent idempotency layers ("either one failing alone
must not produce a duplicate order"): this stage is the primary,
upstream authority for catching malformed data at the source: Scanner's
own check remains as a second, independent, cheap structural
verification specifically *because* Scanner's Purity Principle (`ADR-002`
§2) already forbids it from trusting any input, including this stage's
output, without verifying its own invariants. If this stage's own
validation ever has a bug, Scanner's guarantee that it "never fabricates
structure from bad data" must still hold — it cannot depend on this
stage having validated correctly. Neither layer is redundant to remove;
both are required, independently, for the same reason two independent
brakes are not "duplicate braking."

`ADR-002` §9's other failure modes (insufficient bar history, a
timeframe missing entirely, clock/session ambiguity, symbol not
recognized by the caller's configuration) are **not** duplicated here —
those are Scanner-specific conditions relative to what a particular
*call* was given (its configured timeframe set, its symbol
registration), not conditions this stage can detect about the data
itself.

---

# 9. Multi-consumer model — who reads this stage's output

**Scanner is the sole consumer of this stage's structural/historical
output** (`NormalizedBar`, `HistoricalSeries`) for market-structure
analysis — this is what "Scanner consumes Data Pipeline output only"
means, correctly scoped.

**It does not mean this stage has exactly one consumer overall.**
`ADR-006` §2 (Accepted, drafted before this ADR existed) already
established that Compliance Engine receives `market_status` and current
spread **directly from Market Data, not routed through
`ScannerObservation`** — "the same fact Scanner already consumes as a
raw input." `ADR-007` §2 (Accepted) requires Execution Validator to read
"a fresh, at-this-instant read of price, spread, and `market_status`,
independent of whatever snapshot Scanner... observed earlier." `ADR-008`
§4/§6 (Accepted) requires MT5 Bridge to read current broker/connection
state for its own submission-time checks.

**This ADR resolves that as a deliberate multi-consumer model, not a
conflict with a narrower "Scanner only" reading of the source material:**
`MarketSnapshot` (§5) is the shared output object Scanner, Compliance
Engine, and Execution Validator/MT5 Bridge each independently read, on
their own cadence, for their own already-Accepted purpose. None of them
opens a second connection to the MT5 Broker Feed to get it — they all
read this stage's already-normalized output, which is precisely what
keeps `ADR-015` §6's rule ("only the Market Data stage and MT5 Bridge
touch the MT5 Broker Feed directly") intact. **"No other stage may
access broker market data directly" means exactly that — no direct
broker connection — not "no stage besides Scanner may read anything
this stage produces."** Reading `NormalizedBar`/`HistoricalSeries` for
structural analysis remains Scanner's exclusive lane; reading
`MarketSnapshot` for a live-state check is available to any stage whose
own Accepted ADR already requires it.

---

# 10. Replay

**Replay data originates here.** This stage produces `ReplaySeries`
(§5) — captured historical ticks/bars/snapshots, replayable through the
same ingestion path used for live data, so replay exercises the same
normalization/validation logic live data does, not a separate code path.

**Three distinct, non-overlapping "replay" ownership claims exist across
this session's ADRs, restated here for clarity, not redefined:**

- **This stage** owns replay **data production** — the raw
  ticks/bars/snapshots a replay run needs.
- **Analytics (`ADR-010` §8)** owns replay **decision inputs** — the
  archived `ScannerObservation` through `PositionManagementDecision`
  chain a replay run needs to verify each stage's actual historical
  decisions, not just the market data that produced them.
- **`ADR-018` (Replay & Certification Engine, recommended by the Gap
  Audit, not yet drafted)** is the forward-declared consumer of both —
  the actual engine that re-runs stage logic against this stage's
  `ReplaySeries` and Analytics' archived decisions, and certifies the
  result matches. This ADR does not claim that execution/certification
  scope, the same restraint `ADR-010` §8 already exercised for its own
  replay-input ownership.

**Analytics consumes replay history. `ADR-018` consumes replay history.
Research (`ADR-019`) consumes replay history** — all as read-only
consumers of `ReplaySeries`, never as a source that could alter it.
**Replay never modifies live data** — replay runs operate on captured
`ReplaySeries` snapshots, structurally separate from the live ingestion
path's current state.

---

# 11. Caching

- **Historical cache** — bounded, retained per symbol/timeframe for a
  configured window; not unbounded, mirroring the same TTL-pruning
  discipline established for every other bounded-state exception in this
  pipeline (`ADR-002` §2's session clock, `ADR-007`/`ADR-008`'s
  idempotency records).
- **Warm cache** — pre-populated historical data available immediately
  at startup, avoiding a cold-start warm-up gap for every symbol
  simultaneously.
- **Cold start** — the condition when no warm cache is available (first
  run, or cache invalidated); symbols pass through `ADR-002` §9's
  warm-up failure mode until sufficient history accumulates, exactly as
  Scanner already expects.
- **Cache invalidation** — an explicit, logged event (e.g. detected
  vendor data revision, configuration change to a symbol's timeframe
  set); never a silent cache clear.
- **Retention** — a configured maximum age/size per symbol/timeframe;
  exceeding it evicts the oldest data, never silently growing unbounded.
- **Memory limits** — the cache has a configured maximum footprint;
  exceeding it triggers eviction per the retention policy, never an
  unbounded-growth condition that could exhaust available memory.

---

# 12. Adapter compliance

Every vendor-facing component of this stage (the MT5 Broker Feed
ingestion adapter, any future approved external market data adapter per
`ADR-015` §12) is an adapter in `ADR-015`'s sense and is bound by its
**Adapter Forbidden Responsibilities** section without exception:
translation only, no business/strategy/scoring/risk/compliance logic,
no AI reasoning, no mutation of pipeline objects, no bypass of pipeline
stages. This ADR does not restate that section — it confirms this
stage's own adapters are exactly the adapters it governs.

---

# 13. Security

- **Pipeline owns no trading authority. No broker order capability. No
  strategy capability. No AI capability.** (Hard Rules.)
- **Credentials** for the MT5 Broker Feed connection are scoped,
  per `ADR-015` §9's least-privilege principle, to market-data
  read-access only — structurally incapable of order placement, the
  same "sole stage with order-placement capability" boundary `ADR-008`
  §10 already establishes for MT5 Bridge specifically (this stage is
  not that stage, and must never be granted its capability).
- **No network egress beyond the approved sources in §4** — any future
  source requires `ADR-015` §12's four-step gate before this stage may
  connect to it.

---

# 14. Logging

Every ingestion event includes:

- `trace_id`
- `symbol`
- `timeframe`
- `timestamp`
- `source`
- `quality`

This is the point at which a trading `trace_id` chain begins — the same
chain `ADR-002` §8 onward propagates through every subsequent stage.

---

# 15. Metrics

- Latency
- Gap count
- Gap repair count
- Duplicate ticks
- Dropped ticks
- Out-of-order ticks
- Cache hit ratio
- Replay readiness
- Export-only, additive — the same discipline established at every prior
  stage.

---

# 16. Testing

- **Unit tests** — isolated, fixture-based, no dependency on a live
  broker connection.
- **Gap detection test** — a synthetic gap in a bar sequence is
  correctly detected and reported (`DataQualityReport`).
- **Gap repair test** — a single missing bar is repaired and carries
  `is_repaired`; consecutive missing bars are never repaired, only
  reported.
- **Duplicate removal test** — a repeated tick is deduplicated and
  counted, not silently dropped.
- **Replay consistency test** — replaying a captured `ReplaySeries`
  reproduces byte-identical `NormalizedTick`/`NormalizedBar` output to
  the original live run.
- **Historical consistency test** — repeated historical loads of the
  same range produce identical `HistoricalSeries`.
- **Normalization correctness test** — symbol/price/volume normalization
  produces the documented canonical representation for known vendor
  input variants.
- **Timestamp correctness test**, **timezone correctness test** —
  vendor timestamps in varying formats/zones normalize to the same
  canonical, timezone-aware representation.
- **Multi-timeframe correctness test** — aggregation from a base
  timeframe into higher timeframes produces bars consistent with
  directly-ingested bars at that timeframe, where both exist.
- **Boundary/type-level test** — no output type (§5) can hold a trade
  idea, score, risk decision, compliance verdict, execution instruction,
  or portfolio decision.

---

# 17. Architectural invariants

- The Data Pipeline is the sole authority for normalized market data.
- Scanner never reads broker feeds directly.
- Every downstream stage consumes normalized data only — never a raw
  vendor feed (§9 clarifies this is compatible with more than one stage
  consuming `MarketSnapshot`).
- Replay data originates here.

---

# 18. Acceptance criteria

ADR-013 is acceptable only if it guarantees:

- ✓ Every market event normalized (§6).
- ✓ Every downstream stage consumes one canonical model — `NormalizedBar`/
  `HistoricalSeries` for Scanner, `MarketSnapshot` for the other
  permitted consumers (§9), never a raw vendor shape.
- ✓ Replay deterministic (§10, §16).
- ✓ Historical loading deterministic (§16).
- ✓ No trading authority (§1, §3, §13).

---

# 19. Reference material — ideas only, not authority

- **No dedicated market-data ingestion/normalization module exists
  anywhere in this repository** (verified: no tick/bar-construction or
  gap-repair logic in `phantom/` or `phantom_institutional.py` beyond
  what `Scanner`/`Guards` consume as already-supplied bars). As with
  `ADR-008`, `ADR-009`, `ADR-011`, and `ADR-012`, there is no legacy
  module to mine for ideas — this stage is designed entirely from first
  principles.
- `ADR-002` §4's already-Accepted description of Scanner's expected
  input shape (timezone-aware OHLCV bars, oldest→newest, supplied
  `market_status`) is the direct specification this ADR's normalization
  output must satisfy — not a reference idea, a binding contract this
  ADR fulfills.
- `ADR-015` §5's data-flow diagram and §6's MT5 Broker Feed entry are
  the direct source of this ADR's access-control model (§1, §9) and are
  restated, not reinvented, here.
- `phantom/regime.py`'s `INSUFFICIENT_DATA` handling (cited as an idea
  in `ADR-002` §17) is the same idea this ADR's warm-up/cold-start
  handling (§11) extends one stage earlier.

---

Per `ADR-001` and `CLAUDE.md` §1.10, **no implementation begins until this
ADR's Status changes from Proposed to Accepted.**
