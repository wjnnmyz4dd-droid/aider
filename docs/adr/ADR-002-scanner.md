# ADR-002 — Scanner

Status: **Accepted**

Owner: Software Architect

Date: 2026-07-04

Acceptance Date: 2026-07-04

Accepted By: Software Architect, Titan Protocol Engineering Council

Depends on: `ADR-001-single-authority-architecture.md` (Accepted)

**Amendment 1 (2026-07-04):** expanded the market-structure output scope
(external/internal structure, swing hierarchy, equal highs/lows, range
structure, accumulation/distribution, trend acceleration/exhaustion,
market phase, structure confidence) in response to a request for a
separate "Institutional Market Structure Engine." Resolved as an
amendment to this ADR rather than a new pipeline stage (which would have
been proposed as ADR-020), to avoid creating a second authority over
facts this ADR already owns — see §1's mandate and ADR-001's
single-authority principle. **Pipeline position is unchanged: no new
stage was added; Scanner's existing single-stage position is retained and
its authority is expanded, not divided.** Additions appear in §5, §8, §9,
§10, §13, §15, §17, and §18, each marked "Amendment 1" so the originally
Accepted content and this addition remain distinguishable.

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
structure, trend, volatility, session, liquidity, and data quality.

**The Scanner answers exactly one question: "What is the market doing
right now?" It never answers "What should we do?"** Every requirement in
this ADR is a consequence of that one-sentence boundary. Per ADR-001's
Single Sources of Truth, the Scanner's mandate is exactly: signal
generation, market structure, session detection — this ADR elaborates
that mandate into a concrete contract.

The Scanner is the foundation every downstream stage depends on being
correct, deterministic, and honest about its own uncertainty. A wrong
score or a bad trade is recoverable; a Scanner that silently fabricates
structure from insufficient data corrupts everything built on top of it.

---

# 2. Scanner Purity Principle

The Scanner must be **referentially transparent**. Given identical:

- market data
- symbol
- timeframe
- configuration
- timestamp

the Scanner **must always produce the exact same `ScannerObservation`.**

The Scanner may **not** depend on:

- Mutable global state
- Previous scans
- Hidden caches
- Randomness
- External APIs
- Strategy state
- Execution history

The Scanner is a pure observation engine — a function of its declared
inputs (§4) only, nothing else. This is the single authoritative statement
of the Scanner's purity requirement; §7's Interface contract and §14's
Determinism Requirement both build on this principle rather than
restating it.

---

# 3. Facts, Never Decisions

The Scanner only emits observations — facts about market conditions. It
never emits:

- BUY / SELL / LONG / SHORT
- APPROVE / REJECT / BLOCK / WATCHLIST
- Confidence, score, or probability
- Position size
- Stop loss / take profit
- Execution instructions

Example `ScannerObservation` (illustrative only, not a schema — see §8 for
the data model):

- Trend = UP
- Structure = BOS
- Liquidity Sweep = TRUE
- Volatility = NORMAL
- Session = LONDON
- Spread = ACCEPTABLE
- Data Quality = GOOD

These are facts only. Interpretation — what these facts mean for a trade —
belongs entirely to later pipeline stages (Strategy Engine onward). This
section is the concrete, example-driven illustration of the boundary
stated abstractly in §6 (Explicit non-responsibilities); the two must be
read together and must never be allowed to drift apart.

---

# 4. Inputs

Supplied by the Market Data stage (ADR-013); the Scanner does not fetch,
cache, or validate raw feeds itself — it consumes what it's given and
fails closed (§10) if what it's given is inadequate.

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

# 5. Outputs — `ScannerObservation`

One `ScannerObservation` per symbol per call. See §8 for the data model.
Conceptually:

- **Market structure** — presence and direction of structural signals
  (break of structure, change of character, liquidity sweep, fair value
  gap, order block, or equivalent). Generic, playbook-agnostic — see §6.
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
  rest of the observation should be treated as unreliable (§10).

**Amendment 1 (2026-07-04) — expanded market-structure interpretation.**
The following are additional facts, derived from the same primitive
structure/trend/volatility computations above, never a second independent
computation pass (§13):

- **External structure** — the higher-scale structural trend (major swing
  sequence).
- **Internal structure** — the lower-scale structural trend (minor swing
  sequence) within the current external structure.
- **Swing hierarchy** — the ordered sequence of swing highs/lows that the
  existing `structure` facts (BOS/CHOCH) are already computed from,
  exposed directly so downstream consumers never need to re-derive it
  independently.
- **Higher Highs / Higher Lows / Lower Highs / Lower Lows** — the
  classified sequence type of the current swing hierarchy. A factual
  label, not an interpretation of what to do about it.
- **Equal highs / equal lows** — a specific swing-equality condition
  commonly associated with resting liquidity, reported as a fact.
- **Range structure** — an expansion/compression label, extending the
  existing volatility state's underlying ratio into an explicit
  range-structure classification.
- **Accumulation / distribution** — a phase classification derived from
  swing hierarchy, volatility, and range behavior. Explicitly a fact
  about historical price behavior, never an instruction to accumulate or
  distribute anything.
- **Trend acceleration / trend exhaustion** — a classified state
  describing whether the existing trend state's momentum is strengthening
  or weakening.
- **Market phase** — the most composite fact, combining the above into a
  single label (e.g. accumulation / markup / distribution / markdown /
  undefined). Computed last, from the other structure facts in the same
  observation — still a descriptive classification, not a decision.
- **Structure confidence** — a **qualitative label** (e.g. clear /
  ambiguous / insufficient data), never a numeric confidence score. This
  applies the same discipline `ADR-016` §4 and `ADR-019` §4 established
  for their own confidence labels — a qualitative label is far harder to
  mistake for, or quietly evolve into, an implicit scoring mechanism than
  a number is.

---

# 6. Explicit non-responsibilities

The Scanner does **not**:

- Score a trade, or compute anything resembling a composite confidence
  number.
- Approve, block, or otherwise decide on a trade.
- Size a trade or touch anything risk-related.
- Execute a trade or communicate with a broker/MT5.
- Apply prop-firm compliance, drawdown, or kill-switch logic.
- **Contain playbook-specific logic.** This is a correction over the
  reference material: `titan_protocol/orb.py`'s opening-range tracking is
  strategy-specific state (idempotency, session-confirmation bookkeeping)
  that does not belong in the Scanner. The Scanner reports generic,
  playbook-agnostic facts (a breakout of a session's opening range is a
  **liquidity/structure event**, not an "ORB signal"); which playbooks
  consume that fact, and how, is entirely the Strategy Engine's concern
  (ADR-003). The Scanner must not know that ORB, Liquidity Reversal, or
  any other playbook exists.
- Maintain any per-strategy state (no idempotency tracking, no
  "confirmed session" bookkeeping — that is Strategy Engine state).

See §3 for the concrete, example-driven illustration of this boundary.

---

# 7. Interface contract

- One entry point: given a symbol and its current market-data snapshot
  (§4), return exactly one `ScannerObservation` (§8).
- **Referentially transparent**, per the Scanner Purity Principle (§2).
  Two calls with identical inputs must produce identical output; the only
  state the Scanner may hold internally is computational (e.g. a
  session-window clock), never anything that encodes a trading decision
  or a strategy's memory.
- **No side effects beyond logging and metrics**, both of which are
  required (§11, §12), not optional instrumentation.
- **No network egress, no file I/O beyond the declared logging sink.**
- The Scanner must not raise on bad input; every failure mode in §9
  degrades to a well-formed `ScannerObservation` with `data_quality_flag`
  set (§10), never an exception that could halt the pipeline.

---

# 8. Data model

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
  `titan_protocol/structure.py`'s `StructureSignal` as an idea, not as an
  authoritative type).
- `volatility` — classified state plus underlying ratio.
- `session` — active session name(s) and window position.
- `liquidity_events` — list of detected events (kind, direction, price
  level where applicable).
- `data_quality_flag` — boolean or enum (warm-up / stale / missing
  timeframe / nominal); see §10.
- No field in this model may represent a score, a decision, a size, or an
  approval, structurally — this is a type-level guarantee the acceptance
  criteria (§18) must be able to verify by inspection, not just by
  behavioral testing (see §3, Facts, Never Decisions).

**Amendment 1 (2026-07-04):** additional fields — `external_structure`,
`internal_structure`, `swing_hierarchy`, `equal_highs`/`equal_lows`,
`range_structure`, `phase` (accumulation/markup/distribution/markdown/
undefined), `trend_acceleration`/`trend_exhaustion`, and
`structure_confidence` (qualitative label, never numeric) — per §5. Same
type-level guarantee applies: none of these fields may represent a score,
decision, size, or approval. Future structural concepts (e.g. Volume
Profile, Market Profile, Order Flow, Footprint, Auction Theory,
Institutional Flow) are added the same way — as new, additive
`schema_version`-gated fields, never requiring architectural redesign,
consistent with the additive-field backward-compatibility rule `ADR-003`
§4 and `ADR-004` §4 already rely on when consuming `ScannerObservation`.

---

# 9. Failure modes

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
- **Amendment 1:** insufficient swing history to classify market phase or
  structure confidence — distinct from general warm-up, since a symbol
  can have enough bars for a trend reading but not enough distinct swing
  points for phase classification.

---

# 10. Fail-closed behavior

On any failure mode in §9, the Scanner emits a `ScannerObservation` with
`data_quality_flag` set to the specific condition, and every other field
either omitted or set to an explicit "unknown" state — **it never
fabricates a plausible-looking structure, trend, or volatility reading
from incomplete data.** This generalizes `titan_protocol/regime.py`'s
`INSUFFICIENT_DATA` handling (an idea worth keeping) to every field in
the observation, not just regime.

Downstream stages must treat any non-nominal `data_quality_flag` as an
automatic non-trade signal — that is a contract this ADR establishes for
the Strategy Engine (ADR-003) to honor, not something the Scanner
enforces itself (the Scanner has no authority to block anything; it can
only report honestly).

**Amendment 1:** `market_phase`, `structure_confidence`, and the other
composite fields introduced in Amendment 1 default to an explicit
UNKNOWN state under the same discipline — never fabricated, and never
carried forward from a stale prior scan (the Scanner Purity Principle,
§2, already forbids depending on "previous scans" for exactly this
reason).

---

# 11. Logging requirements

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

# 12. Metrics requirements

- Count of observations, labeled by `data_quality_flag` state (nominal
  vs. each failure mode in §9) — generalizes the reference material's
  `phantom_warmup_total` counter to every failure mode, not just warm-up.
- Per-symbol scan latency (for §13).
- Counts of structural signals detected, by kind and direction — useful
  denominator for later strategy-layer analytics, without the Scanner
  itself interpreting them.
- All metrics are export-only: incrementing them must have zero effect on
  the returned observation, mirroring the "additive, changes nothing"
  discipline already established for `titan_protocol/metrics.py`.

---

# 13. Performance targets

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
  idea in `titan_protocol/config.py`).
- **Amendment 1:** every composite field introduced in Amendment 1
  (external/internal structure, swing hierarchy, equal highs/lows, range
  structure, accumulation/distribution, trend acceleration/exhaustion,
  market phase, structure confidence) must be derived from the same
  single swing-pivot/structure computation already required above —
  never a second, independent computation pass. This is the same
  `swing_points()` lesson applied to prevent a new class of duplication
  this amendment could otherwise introduce.

---

# 14. Determinism Requirement

Historical replay using identical market data must generate identical
`ScannerObservation` objects, byte-for-byte. This is mandatory for:

- Regression testing
- Walk-forward validation
- Debugging
- Certification (forward-test / prop-firm audit trail)

This is **replay determinism** specifically — a stronger, time-independent
extension of the Scanner Purity Principle (§2): not only must a single
call be a pure function of its declared inputs, but re-running an entire
historical session's worth of calls must reproduce the exact same
sequence of observations, with no drift introduced by wall-clock time,
process restarts, execution order, or any other incidental factor outside
the declared inputs. §15's testing strategy is how this requirement is
verified, not where it is defined.

---

# 15. Testing strategy

Dedicated tests must prove, at minimum:

- ✓ Identical input → identical output
- ✓ No score fields exist
- ✓ No decision fields exist
- ✓ No mutable state affects output
- ✓ All computations occur once per scan
- ✓ Failures produce `data_quality_flag`s

Elaborated:

- **Fully isolated unit tests** — the Scanner must be testable with fixed
  OHLCV fixtures and no dependency on the Strategy Engine, Scoring
  Engine, or any stage downstream of it.
- **Deterministic regression tests** — identical input must produce
  byte-identical output; assert this directly, not just "similar
  decision" the way the reference material's scanner regression check
  did. This is the test-level verification of §14's Determinism
  Requirement.
- **One test per failure mode in §9**, asserting the correct
  `data_quality_flag` and that no fabricated structure/trend/volatility
  is present.
- **A structural/type-level test** that `ScannerObservation` has no field
  capable of representing a score, decision, size, or approval — enforces
  §3 and §6's boundary at the type level, not just behaviorally.
- **A duplicate-computation test** — assert that each structural
  computation (§13) executes exactly once per scan (e.g. via a call-count
  spy in tests), so the swing_points-style regression cannot silently
  reappear.
- **A purity test** — assert that mutating or removing any hidden/global
  state the implementation might be tempted to introduce has no effect on
  a call's output, directly enforcing §2's Scanner Purity Principle.
- **Amendment 1 — a structure-consistency test:** every composite field
  (market phase, structure confidence, accumulation/distribution, etc.)
  must be derivable from, and consistent with, the primitive facts (§5's
  original trend/structure/volatility fields) in the same observation —
  e.g. `market_phase = accumulation` while the swing hierarchy shows a
  clear downtrend of lower-highs/lower-lows would be a contradiction, not
  a valid output, and must fail the test.
- **Amendment 1 — UNKNOWN handling tests** for the new composite fields,
  per §10's amended fail-closed behavior.

---

# 16. Security assumptions

- The Scanner consumes only market-data inputs (§4) — no credentials, no
  account/equity data, no broker connection of any kind. Its blast radius
  if compromised or fed adversarial data is bounded to producing bad
  *observations*, never an unauthorized trade, because it has no
  execution capability and no path to one.
- Input validation must treat all supplied market data as untrusted
  (malformed candles, adversarial gaps, spoofed session/market-status
  flags) and fail closed per §10 rather than propagate garbage downstream.
- No network egress, consistent with `titan_protocol/`'s existing stdlib-only,
  no-third-party-dependency posture — worth preserving as a security
  property, not just a style preference.

---

# 17. Reference material — ideas only, not authority

The following inform this design and are explicitly **not** authoritative
over it, per ADR-001:

- `titan_protocol/regime.py` — EMA-based trend read, ATR-ratio volatility
  classification, `INSUFFICIENT_DATA` as its own state rather than a
  degraded `NEUTRAL`. Useful ideas; thresholds and exact formulas are not
  binding.
- `titan_protocol/structure.py` — swing-pivot-based BOS/CHOCH/liquidity-sweep/
  FVG/order-block detection shape (`StructureSignal(found, direction,
  detail)`). Useful shape; the repeated `swing_points()` computation
  pattern is explicitly rejected (§13).
- `titan_protocol/orb.py` — the idea that a session's opening range is a
  meaningful liquidity/structure fact is useful; its idempotency/
  session-confirmation state is explicitly rejected from the Scanner
  (§6) and belongs, if kept at all, in the Strategy Engine (ADR-003).
- `phantom_institutional.py`'s `LiquidityHeatmap` / `RegimeDetector` /
  `compute_regime_v2` — the idea of reporting nearest liquidity pools and
  a regime read with an "early warning" concept is a useful input to
  §5's liquidity-events and volatility-state design; none of its specific
  code, ML dependencies, or thresholds are authoritative, consistent with
  it being reference-only per ADR-001.
- `docs/research/VIBE-TRADING-EVALUATION.md` and
  `docs/research/ECC-EVALUATION.md` — no direct relevance to Scanner
  design; noted for completeness since both are standing reference
  documents.
- **Amendment 1:** Smart Money Concepts (SMC) / Wyckoff market-phase
  terminology — external/internal structure, equal highs/lows, and
  accumulation/distribution/markup/markdown phase labels are established
  technical-analysis concepts, not proprietary to Titan Protocol. The
  independent `smartmoneyconcepts` PyPI package (already noted in
  `docs/research/VIBE-TRADING-EVALUATION.md` §11 as a cross-check
  reference) is a useful idea-source for this expanded scope's
  terminology and detection shape — not an authority over it.

---

# 18. Acceptance criteria

ADR-002 is satisfied by an implementation that demonstrates all of:

- ✓ Referentially transparent per the Scanner Purity Principle (§2) —
  identical input produces byte-identical output.
- ✓ Testable in complete isolation from every other pipeline stage.
- ✓ Emits facts only, never a BUY/SELL/APPROVE/REJECT/score/size/
  execution-shaped field (§3), structurally guaranteed by the data model
  (§8) and verified by the type-level test (§15).
- ✓ Fails closed on every failure mode in §9 with the correct
  `data_quality_flag`, never fabricating a reading from incomplete data.
- ✓ No structural computation repeated more than once per scan (§13),
  verified by the duplicate-computation test.
- ✓ Passes replay-determinism testing (§14) — identical historical
  replay reproduces identical observations, byte-for-byte.
- ✓ Every logged record carries a `trace_id` (§11).
- ✓ Contains zero playbook-specific logic or state (§6).
- ✓ Metrics are export-only and additive (§12).
- ✓ No network egress, no credential or account-data access (§16).
- ✓ **Amendment 1:** exactly one authoritative source of market structure
  exists — no downstream stage independently recalculates BOS/CHOCH/swing
  structure/trend classification (§6, §13).
- ✓ **Amendment 1:** all composite structure fields (external/internal
  structure, swing hierarchy, equal highs/lows, range structure,
  accumulation/distribution, trend acceleration/exhaustion, market phase,
  structure confidence) are derived from a single computation pass, never
  duplicated (§13, §15).
- ✓ **Amendment 1:** structure confidence is a qualitative label, never a
  numeric score (§5).

Per `ADR-001` and `CLAUDE.md` §1.10, **no implementation begins until this
ADR's Status changes from Proposed to Accepted.** (This ADR is already
Accepted; Amendment 1 is a documentation-only expansion of an Accepted
ADR's scope, not a reopening of its acceptance status.)
