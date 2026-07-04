# ADR-002 — Scanner

Status: Proposed

Owner: Software Architect

Date: 2026-07-04

Depends on: `ADR-001-single-authority-architecture.md` (Accepted)

---

# Pipeline position

Market Data → **Scanner** → Strategy Engine → Scoring Engine → Risk Engine
→ Compliance Engine → Execution Validator → MT5 Bridge → Position Manager
→ Analytics

This ADR defines only the Scanner stage. It consumes Market Data's output
and produces input for the Strategy Engine (ADR-003). It does not define
either neighbor.

---

# 1. Scanner mission

The Scanner observes raw market data for one symbol at one instant and
produces a structured, factual description of current market conditions —
structure, trend, volatility, session, liquidity, and data quality. It
answers **"what is the market doing right now"**, never **"what should we
do about it."** It has no trading authority of any kind. Per ADR-001's
Single Sources of Truth, the Scanner's mandate is exactly: signal
generation, market structure, session detection — this ADR elaborates
that mandate into a concrete contract.

The Scanner is the foundation every downstream stage depends on being
correct, deterministic, and honest about its own uncertainty. A wrong
score or a bad trade is recoverable; a Scanner that silently fabricates
structure from insufficient data corrupts everything built on top of it.

---

# 2. Inputs

Supplied by the Market Data stage (ADR-013); the Scanner does not fetch,
cache, or validate raw feeds itself — it consumes what it's given and
fails closed (§8) if what it's given is inadequate.

- **Symbol** — one instrument identifier per observation. The Scanner is
  called once per symbol; it does not itself iterate a universe.
- **Timeframes** — a set of OHLCV series keyed by timeframe label (e.g. an
  execution timeframe plus one or more higher timeframes for trend
  context). The Scanner does not hard-code which timeframes exist; the
  set is a configuration concern of the caller.
- **OHLCV bars** — timestamped open/high/low/close/volume, oldest→newest,
  per timeframe. Must be timezone-aware.
- **Spread** — current spread in price units for the symbol.
- **Session time** — the current instant, timezone-aware, in a form the
  Scanner can compare against configured session windows.
- **Market status** — whether the venue is currently tradeable (open,
  halted, weekend, holiday, connectivity-degraded). Supplied, not
  computed: the Scanner trusts this flag rather than inferring market
  status from bar gaps or timestamps.

---

# 3. Outputs — `ScannerObservation`

One `ScannerObservation` per symbol per call. See §6 for the data model.
Conceptually:

- **Market structure** — presence and direction of structural signals
  (break of structure, change of character, liquidity sweep, fair value
  gap, order block, or equivalent). Generic, playbook-agnostic — see §4.
- **Trend state** — per-timeframe direction and strength, computed
  independently per timeframe (no cross-timeframe bias resolution — that
  is the Strategy Engine's job, since "bias" is a trading judgment, not a
  market fact).
- **Volatility state** — a classified state (e.g. compressed / healthy /
  elevated / extreme) plus the underlying ratio it was derived from.
- **Session state** — which configured session(s) are currently active
  and how far into/from their boundaries the current instant is.
- **Liquidity events** — detected liquidity-relevant conditions (a sweep
  beyond a prior extreme, proximity to a known liquidity pool). Reported
  as facts, not as trade signals.
- **Data quality flags** — explicit, structured indication of warm-up
  state, missing-timeframe state, or any other condition under which the
  rest of the observation should be treated as unreliable (§8).

---

# 4. Explicit non-responsibilities

The Scanner does **not**:

- Score a trade, or compute anything resembling a composite confidence
  number.
- Approve, block, or otherwise decide on a trade.
- Size a trade or touch anything risk-related.
- Execute a trade or communicate with a broker/MT5.
- Apply prop-firm compliance, drawdown, or kill-switch logic.
- **Contain playbook-specific logic.** This is a correction over the
  reference material: `phantom/orb.py`'s opening-range tracking is
  strategy-specific state (idempotency, session-confirmation bookkeeping)
  that does not belong in the Scanner. The Scanner reports generic,
  playbook-agnostic facts (a breakout of a session's opening range is a
  **liquidity/structure event**, not an "ORB signal"); which playbooks
  consume that fact, and how, is entirely the Strategy Engine's concern
  (ADR-003). The Scanner must not know that ORB, Liquidity Reversal, or
  any other playbook exists.
- Maintain any per-strategy state (no idempotency tracking, no
  "confirmed session" bookkeeping — that is Strategy Engine state).

---

# 5. Interface contract

- One entry point: given a symbol and its current market-data snapshot
  (§2), return exactly one `ScannerObservation` (§6).
- **Pure with respect to trading state.** The only state the Scanner may
  hold internally is computational (e.g. a session-window clock), never
  anything that encodes a trading decision or a strategy's memory. Two
  calls with identical inputs at the same instant must produce identical
  output.
- **No side effects beyond logging and metrics**, both of which are
  required (§9, §10), not optional instrumentation.
- **No network egress, no file I/O beyond the declared logging sink.**
- The Scanner must not raise on bad input; every failure mode in §7
  degrades to a well-formed `ScannerObservation` with `data_quality_flag`
  set (§8), never an exception that could halt the pipeline.

---

# 6. Data model

`ScannerObservation` (conceptual — no implementation code per this ADR's
scope):

- `schema_version` — explicit version marker, so the Strategy Engine can
  evolve independently of the Scanner without a silent breaking change.
  Not present in any reference material; new discipline for this
  pipeline.
- `symbol`, `timestamp` (timezone-aware).
- `trend` — map of timeframe → (direction, strength), independent per
  timeframe.
- `structure` — list of structural signals, each with kind, direction,
  and a human-readable detail string (mirrors the shape of
  `phantom/structure.py`'s `StructureSignal` as an idea, not as an
  authoritative type).
- `volatility` — classified state plus underlying ratio.
- `session` — active session name(s) and window position.
- `liquidity_events` — list of detected events (kind, direction, price
  level where applicable).
- `data_quality_flag` — boolean or enum (warm-up / stale / missing
  timeframe / nominal); see §8.
- No field in this model may represent a score, a decision, a size, or an
  approval, structurally — this is a type-level guarantee the acceptance
  criteria (§15) must be able to verify by inspection, not just by
  behavioral testing.

---

# 7. Failure modes

- Insufficient bar history for a requested timeframe (warm-up).
- A requested timeframe missing entirely from the supplied snapshot.
- Stale, zero, or missing spread.
- Malformed candles: non-monotonic timestamps, zero/negative prices,
  impossible OHLC ordering (e.g. low > high).
- Clock/session ambiguity: current instant doesn't unambiguously resolve
  session windows (e.g. daylight-saving transition edge cases).
- Symbol not recognized by the caller's configuration (session/ORB-window
  definitions absent for it).
- `market_status` indicating the venue is not currently tradeable.

---

# 8. Fail-closed behavior

On any failure mode in §7, the Scanner emits a `ScannerObservation` with
`data_quality_flag` set to the specific condition, and every other field
either omitted or set to an explicit "unknown" state — **it never
fabricates a plausible-looking structure, trend, or volatility reading
from incomplete data.** This generalizes `phantom/regime.py`'s
`INSUFFICIENT_DATA` handling (an idea worth keeping) to every field in
the observation, not just regime.

Downstream stages must treat any non-nominal `data_quality_flag` as an
automatic non-trade signal — that is a contract this ADR establishes for
the Strategy Engine (ADR-003) to honor, not something the Scanner
enforces itself (the Scanner has no authority to block anything; it can
only report honestly).

---

# 9. Logging requirements

- Structured, one record per `ScannerObservation`, machine-parseable
  (JSONL or equivalent).
- **Every record must carry a `trace_id`** shared with whatever
  downstream Strategy Engine / Scoring Engine records are produced from
  it. This directly closes a defect already on record
  (`.claude/agents/TEAM.md` §8, Missing Observability: "no shared
  `trace_id` across a scan's log lines") rather than repeating it in the
  new pipeline.
- Must include: symbol, timestamp, `schema_version`, a summary of
  structure/trend/volatility/session, and `data_quality_flag`.
- Logging failure must never block or alter the returned observation —
  logging is observability, not a gate.

---

# 10. Metrics requirements

- Count of observations, labeled by `data_quality_flag` state (nominal
  vs. each failure mode in §7) — generalizes the reference material's
  `phantom_warmup_total` counter to every failure mode, not just warm-up.
- Per-symbol scan latency (for §11).
- Counts of structural signals detected, by kind and direction — useful
  denominator for later strategy-layer analytics, without the Scanner
  itself interpreting them.
- All metrics are export-only: incrementing them must have zero effect on
  the returned observation, mirroring the "additive, changes nothing"
  discipline already established for `phantom/metrics.py`.

---

# 11. Performance targets

- The Scanner must complete well within the shortest configured
  timeframe's bar interval, so scans cannot stack up under normal load.
  The exact numeric budget should be set empirically during ADR-002's
  implementation phase (Phase 2, per ADR-001) against real fixture data
  and real symbol counts — asserting a specific millisecond figure now,
  without an implementation to measure, would be exactly the kind of
  guess `CLAUDE.md` §7 prohibits.
- **Each structural/derived computation must be performed once per scan
  and shared across every consumer that needs it within the same
  observation.** This is a load-bearing design constraint, not a
  suggestion: the reference material's `swing_points()` was independently
  recomputed 4 times per scan (`TEAM.md` §8, Duplicate Logic) — ADR-002
  explicitly forbids repeating that pattern in the new Scanner.
- No unbounded per-symbol or per-scan state growth (the reference
  material's per-symbol `_last_decision` dict pattern is acceptable in
  spirit — bounded by symbol count — but any new state must be
  explicitly bounded or TTL-pruned, per the existing `state_ttl_days`
  idea in `phantom/config.py`).

---

# 12. Testing strategy

- **Fully isolated unit tests** — the Scanner must be testable with fixed
  OHLCV fixtures and no dependency on the Strategy Engine, Scoring
  Engine, or any stage downstream of it.
- **Deterministic regression tests** — identical input must produce
  byte-identical output; assert this directly, not just "similar
  decision" the way the reference material's scanner regression check
  did.
- **One test per failure mode in §7**, asserting the correct
  `data_quality_flag` and that no fabricated structure/trend/volatility
  is present.
- **A structural/type-level test** that `ScannerObservation` has no field
  capable of representing a score, decision, size, or approval — enforces
  §4's boundary at the type level, not just behaviorally.
- **A duplicate-computation test** — assert that each structural
  computation (§11) executes exactly once per scan (e.g. via a call-count
  spy in tests), so the swing_points-style regression cannot silently
  reappear.

---

# 13. Security assumptions

- The Scanner consumes only market-data inputs (§2) — no credentials, no
  account/equity data, no broker connection of any kind. Its blast radius
  if compromised or fed adversarial data is bounded to producing bad
  *observations*, never an unauthorized trade, because it has no
  execution capability and no path to one.
- Input validation must treat all supplied market data as untrusted
  (malformed candles, adversarial gaps, spoofed session/market-status
  flags) and fail closed per §8 rather than propagate garbage downstream.
- No network egress, consistent with `phantom/`'s existing stdlib-only,
  no-third-party-dependency posture — worth preserving as a security
  property, not just a style preference.

---

# 14. Reference material — ideas only, not authority

The following inform this design and are explicitly **not** authoritative
over it, per ADR-001:

- `phantom/regime.py` — EMA-based trend read, ATR-ratio volatility
  classification, `INSUFFICIENT_DATA` as its own state rather than a
  degraded `NEUTRAL`. Useful ideas; thresholds and exact formulas are not
  binding.
- `phantom/structure.py` — swing-pivot-based BOS/CHOCH/liquidity-sweep/
  FVG/order-block detection shape (`StructureSignal(found, direction,
  detail)`). Useful shape; the repeated `swing_points()` computation
  pattern is explicitly rejected (§11).
- `phantom/orb.py` — the idea that a session's opening range is a
  meaningful liquidity/structure fact is useful; its idempotency/
  session-confirmation state is explicitly rejected from the Scanner
  (§4) and belongs, if kept at all, in the Strategy Engine (ADR-003).
- `phantom_institutional.py`'s `LiquidityHeatmap` / `RegimeDetector` /
  `compute_regime_v2` — the idea of reporting nearest liquidity pools and
  a regime read with an "early warning" concept is a useful input to
  §3's liquidity-events and volatility-state design; none of its specific
  code, ML dependencies, or thresholds are authoritative, consistent with
  it being reference-only per ADR-001.
- `docs/research/VIBE-TRADING-EVALUATION.md` and
  `docs/research/ECC-EVALUATION.md` — no direct relevance to Scanner
  design; noted for completeness since both are standing reference
  documents.

---

# 15. Acceptance criteria

ADR-002 is satisfied by an implementation that demonstrates all of:

- ✓ Deterministic — identical input produces byte-identical output.
- ✓ Testable in complete isolation from every other pipeline stage.
- ✓ Structurally incapable of representing a score, decision, size, or
  approval (§6, verified by the type-level test in §12).
- ✓ Fails closed on every failure mode in §7 with the correct
  `data_quality_flag`, never fabricating a reading from incomplete data.
- ✓ No structural computation repeated more than once per scan (§11),
  verified by the duplicate-computation test.
- ✓ Every logged record carries a `trace_id` (§9).
- ✓ Contains zero playbook-specific logic or state (§4).
- ✓ Metrics are export-only and additive (§10).
- ✓ No network egress, no credential or account-data access (§13).

Per `ADR-001` and `CLAUDE.md` §1.10, **no implementation begins until this
ADR's Status changes from Proposed to Accepted.**
