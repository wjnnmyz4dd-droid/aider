# ADR-035 — Opening Range Breakout (ORB) Strategy

Status: **Accepted** (2026-07-25 — architecture and phased roadmap,
§§0-16 and §17, only). This Acceptance is a new, explicit governance
decision made this session, not a reconstruction of history: no prior
commit ever changed this document's own Status line, and none is
retroactively claimed here. It rests on repository-verified maturity —
an independent Acceptance Review already found and required corrections
(F1-F5, all incorporated, commit `af5b9c0`), the companion Evidence
Engine amendment (§3) is implemented and independently validated (Phase
0, commit `ee976f4`, 22+5 tests green), and neither of §18.A's two
required-before-implementation items is an architectural objection:
item 1 (module location) is resolved by Phase 0's own implementation
choice; item 2 (lockout persistence) is resolved in direction this
session (§18.A item 2) with its remaining engineering work explicitly
gated to Phase 2, not blocking Phase 0 or Phase 1. **This Acceptance
does not authorize skipping any phase's own RPI Plan/review gate
(§17, `TEAM.md` §9), and it does not shorten ADR-036's own sequencing
requirement** — legacy-strategy retirement remains gated on ADR-035
Phases 1-6 being implemented, tested, and independently accepted, per
ADR-036 §13's governance gate, unchanged by this Acceptance.

Owner: Software Architect (per the ADR-024/025/026 precedent — a
cross-cutting evaluation design, not a playbook-orchestration one).

Reviewed by: Independent Acceptance Review (F1-F5, corrections
incorporated in `af5b9c0`); this document itself performs the §0 scope
audit ADR-026 established as precedent, checking the proposal against
Evidence Engine, Strategy Engine, Risk Engine, and Runtime's actual
current code before proposing anything.

Depends on: `ADR-024-evidence-engine.md` (Accepted, Amendment 1) —
this proposal requires a further amendment to that ADR (see §0).
`ADR-026-strategy-engine.md` (Accepted, Amendment 1) — the Strategy
interface and TradeIntent discipline ORB must conform to exactly.
`ADR-025-market-intelligence-engine.md` (Accepted) — session/news
facts ORB consumes, never recomputes.

**Amendment 1 (Proposed, 2026-07-26 — not yet Accepted): Phase 4
formation-time news-blackout staged limitation.** Triggered by an
independent implementation-readiness review of the Phase 4 Plan
(`docs/plans/adr-035-phase4-mi-eligibility-integration.md`), which found
that Phase 4's design checks `pair_safety.news.blackout_active` only at
breakout-evaluation time, on every cycle — never retroactively at the
opening range's own formation window — while §2's "News restrictions"
row requires NOT_QUALIFIED "both during range formation and at breakout
evaluation," and neither §17's Phase 4 entry nor §18 discloses or
authorizes this as a staged limitation. This amendment resolves that
gap explicitly rather than leaving it as an undisclosed deviation.

*Why the gap cannot be closed within Phase 4 without violating this
project's own architecture boundaries or inventing unavailable state:*
`OrbBreakoutStrategy.qualify()` is stateless by design (ADR-026) and
observes only the current cycle's `MarketIntelligenceSnapshot` —
`OpeningRangeState` (Evidence Engine, ADR-024) carries no news-related
field, so there is no repository mechanism recording "was a blackout
active while this specific range was forming." Two paths to close this
without inventing state were independently checked and both rejected:
(a) reconstructing formation-time blackout status inside Strategy
Engine from the current snapshot's `pair_safety.news.{active_events,
recent_events,upcoming_events}` — rejected, because doing so requires
duplicating Market Intelligence's own blackout-window arithmetic
(`pre_news_blackout_minutes`/`post_news_blackout_minutes`/per-pair
overrides/central-bank-category rules, `titan_protocol/market_intelligence/news.py`)
inside Strategy Engine, violating the "Market Intelligence owns event
interpretation" ownership split this codebase already enforces
elsewhere (`tests/titan_protocol/news_ingestion/test_structural_boundary.py`'s
prohibition on reimplementing MI's blackout logic outside MI) — and is
unreliable regardless, since `active_events`/`recent_events`'s own
bucket windows are sized independently of, and are frequently narrower
than, the actual blackout pre/post windows, so a formation-time-relevant
event can silently age out of every bucket before breakout evaluation,
producing exactly the false confidence a fail-closed design must avoid;
(b) amending Evidence Engine to persist a formation-time blackout flag
on `OpeningRangeState` — rejected for this amendment's scope because it
requires Evidence Engine to newly depend on Market Intelligence's output
(a dependency that does not exist anywhere in the current architecture,
both engines today independently consume only external inputs), which
is new cross-engine coupling requiring its own dedicated architectural
review, not something to fold into Phase 4's existing scope.

**Authorization:** for Phase 4 only, evaluation-time-only news-blackout
enforcement (checking `pair_safety.news.blackout_active` once, on every
cycle, immediately after the market-closed/holiday gates and before
opening-range selection logic) is explicitly authorized as a staged
limitation. This narrows §2/§14's news-blackout requirement for Phase 4
specifically; it does not alter §2/§14 for any other gate, and it does
not authorize omitting the evaluation-time check itself.

**Safety consequence, stated plainly:** if a blackout was active at any
point during an opening range's formation window but has cleared by the
time a breakout candidate is evaluated, ORB can still produce a
`QUALIFIED` result for that range on that basis alone — the range's
underlying price action may have been shaped by the news event even
though the check performed at evaluation time reports no active
blackout. This residual exposure is partially bounded by ORB's existing,
unrelated gates (ATR-relative breakout distance, body/wick ratio,
confirmation-candle count, volatility expansion) which independently
filter low-quality moves regardless of their cause, and by whatever
downstream Risk/Compliance-layer news-sensitivity exists — but those are
incidental mitigations, not a substitute for the ADR's own stated
requirement.

**Closing the gap (deferred, not designed here, not yet scheduled):** a
future, dedicated RPI Research pass must scope one of — (i) a new,
small, per-`(pair, range_start)` persisted history mechanism, in
convention analogous to `OrbQualificationStore`, that accumulates
"was `blackout_active` ever `True`" across the cycles spanning a range's
own formation window, queried by `OrbBreakoutStrategy` at evaluation
time; or (ii) a reviewed, explicit Evidence-Engine dependency on Market
Intelligence's news output. Neither design is chosen here. This work is
recorded as **Phase 7 — Formation-Time News-Blackout Closure (not yet
scheduled; no RPI Research performed)**, appended to, not folded into,
the phased roadmap in §17 — following this project's own "never
silently move an item between phases" discipline (§17's own precedent
for the Amendment 4/lockout-persistence gaps).

**Status of this amendment: Proposed.** It requires its own independent
review and formal Acceptance before the Phase 4 Plan that depends on it
may proceed to implementation. It does not itself authorize any code
change.

---

## 0. Scope discipline and verified current state (read first)

Every claim below was checked directly against the current repository,
not assumed:

- **Strategy Engine has five registered strategies today**
  (`titan_protocol/strategy_engine/strategies/`):
  `bos_fvg.py`, `liquidity_sweep_mss.py`, `range_reversal.py`,
  `session_breakout.py`, `trend_continuation.py`. `SessionBreakoutStrategy`
  is the closest existing analog to ORB (BREAKOUT regime, session-gated,
  requires volatility expansion) but is not an opening-range strategy —
  it has no concept of a fixed-width range measured from a session's
  open. ORB is additive, not a replacement or duplicate of it.
- **Registration is explicit, not auto-discovery**
  (`titan_protocol/strategy_engine/strategies/registry.py`:
  `StrategyRegistry.register()`, one call per strategy, duplicate
  `StrategyId` rejected). ORB registers exactly the same way.
- **Selection is already a deterministic, evidence-driven cascade**
  (`titan_protocol/strategy_engine/selection.py`: 6 steps — qualification
  score, evidence-alignment confidence, historical ranking (placeholder),
  portfolio concentration (placeholder), liquidity quality, news risk;
  ties beyond all six are rejected, never randomized). **This already is
  Titan's "Strategy Router."** No separate router component exists in
  the repository today, and none needs to be built for ORB — ORB
  competes in the existing cascade exactly like the other five
  strategies. §12 below designs ORB's compatibility with this real
  mechanism, not a hypothetical future one.
- **Fair Value Gaps are already computed by Evidence Engine**, not by
  any strategy: `EvidenceSnapshot.fair_value_gaps: Tuple[FairValueGap, ...]`
  (`titan_protocol/evidence_engine/models.py`), produced by
  `structure.py::detect_fair_value_gaps()`. `BosFvgStrategy` already
  consumes this field directly (`evidence.fair_value_gaps`) rather than
  recomputing gaps itself. ORB must do the same — never a second,
  divergent FVG detector (CLAUDE.md §1.4).
- **`SessionName` (Evidence Engine) is broad, hour-boundary windows**
  (`LONDON`, `LONDON_NEW_YORK_OVERLAP`, `EARLY_NEW_YORK`, `LATE_NEW_YORK`,
  `ASIAN` — `titan_protocol/evidence_engine/session.py`), not a literal
  "opening range" in the ORB sense (typically the first 15-60 minutes
  after a specific session's open). **No existing Evidence Engine field
  computes a fixed-width opening range today.** `SupportResistanceContext.
  session_high`/`session_low` (`support_resistance.py::session_high_low()`)
  is the nearest existing analog — a running high/low since a session
  boundary — but is not width-bounded and not exposed per-(range-window).
- **ATR already exists**: `EvidenceSnapshot.volatility.atr`
  (`VolatilityState.atr`, `titan_protocol/evidence_engine/models.py`) —
  reusable directly for a breakout-distance filter, never a second ATR
  computation.
- **Stop-loss/take-profit price levels are a pre-existing, disclosed
  scope boundary, not something ORB can or should close.**
  `titan_protocol/runtime/bridge_handoff.py::build_trade_command()`
  sets `stop_loss=None, take_profit=None` unconditionally today, with
  its own docstring stating: *"no engine in this pipeline currently
  computes an absolute price level"* (ADR-031 §3, Accepted). This is
  true for every one of the five existing strategies — none of them,
  nor Risk Engine's `position_sizing.py` (R-multiple/confidence/
  volatility/Kelly sizing only, never a price distance), computes a
  stop-loss or take-profit *price*. ORB does not change this. §8/§9
  below design what ORB *can* contribute (structural reference levels,
  as evidence) without inventing a price-level mechanism that would
  either duplicate a decision Risk Engine doesn't yet make, or silently
  expand this ADR's scope into closing ADR-031 §3 — out of scope here.

**Consequence for this design:** ORB requires exactly one companion
change outside Strategy Engine — a proposed **Amendment to ADR-024**
adding opening-range computation to Evidence Engine (§3), mirroring
Amendment 1's own precedent (adding `support_resistance.py` and
expanding `EvidenceSnapshot` for a then-new consumer). Everything else
is additive within Strategy Engine, using only what Evidence Engine and
Market Intelligence already expose.

---

## 1. Strategy purpose

**Objective:** identify and trade the initial directional breakout of a
narrow, fixed-width price range established during the first portion of
a designated trading session — capturing the volatility expansion that
follows a session's opening consolidation, while systematically
rejecting breakouts that reverse immediately (false breaks).

**Performs well when:** genuine volatility expansion follows session
open (session-open liquidity injection, e.g., London or New York open),
the opening range is well-defined (no gaps, no missing candles), and no
high-impact news sits inside or immediately after the range window.

**Should not trade when:** the opening range itself formed during a
news blackout or illiquid/holiday session; the range is abnormally wide
or narrow relative to recent ATR (a symptom of a data or session-timing
problem, not a tradeable range); spread is elevated beyond the
configured maximum at the moment of breakout; or no directional fact
(a confirmed break or an already-directional trend) exists to derive
`TradeIntent` from — ORB never guesses direction (mirrors
`SessionBreakoutStrategy`'s existing `_breakout_trade_intent()` pattern
of returning `None`, never a fallback guess).

**Assumptions:** broker bar timestamps are reliable and in UTC (or a
declared, fixed UTC offset — see §3 DST handling); `MarketDataIngestionEngine`
has already validated/ordered/deduplicated bars before Evidence Engine
ever sees them (ADR-033, unchanged, unrelated to this ADR).

**Limitations:** ORB cannot detect a range contaminated by a data gap
that occurred *inside* the range window itself beyond what `market_data_ingestion`'s
existing gap-detection already flags (ADR-033 §3.3) — a gap inside the
range is treated as an invalid range (fail closed, §14), not silently
tolerated. ORB, like every Strategy Engine strategy, never sizes a
position or sets a price-level stop/target (§0's disclosed boundary).

---

## 2. Market eligibility

| Facet | Rule |
|---|---|
| Supported instruments | Configurable pair whitelist, `orb_approved_pairs` (mirrors every existing strategy's `config.approved_pairs_for(StrategyId.OPENING_RANGE_BREAKOUT)` pattern via `eligibility.check_eligibility()` — no new eligibility mechanism) |
| Supported sessions | Configurable named session-opens only (e.g. London open, New York open) — never "any hour," always an explicit, named range-anchor per §3 |
| Supported days | Monday–Friday only by construction (no session-open concept applies to a closed weekend market); a range anchor falling on an operator-flagged holiday (via the same `MarketSafetyInputs.holidays` Market Intelligence already consumes, ADR-025, unchanged) is NOT_QUALIFIED |
| Minimum volatility | Configurable `orb_min_range_atr_ratio` — the formed range's width relative to `evidence.volatility.atr` must clear this floor, or the range is judged too narrow to be a real opening range |
| Maximum spread | Configurable `orb_max_spread_pips`, checked against the same live-cycle `current_spread` value already threaded into every strategy's cycle (`RuntimeOrchestrator.run_cycle_for_pair()`'s existing parameter — no new spread source) |
| News restrictions | Reuses Market Intelligence's existing `pair_safety.news.blackout_active` exactly as `SessionBreakoutStrategy` does today — NOT_QUALIFIED if active, both during range formation and at breakout evaluation |
| Holiday handling | `MarketSafetyInputs.holidays`/`market_closed` (existing, ADR-025) — NOT_QUALIFIED, never inferred locally |
| Weekend handling | No explicit check needed — no bars exist to form a range, so `is_ready`-style upstream gating (ADR-033, unchanged) already prevents a cycle from reaching ORB with weekend data |
| Low-liquidity handling | Reuses `pair_safety.liquidity.liquidity_score` (Market Intelligence, existing) as an additional qualification floor, `orb_min_liquidity_score` |

---

## 3. Opening range (requires an Evidence Engine amendment)

**`OpeningRangeState` is generic market evidence, not ORB-specific
logic.** It belongs in Evidence Engine for exactly the same reason
`FairValueGap` and `SupportResistanceContext.session_high`/`session_low`
already do: it is a fact about price action within a configured time
window, independent of any one strategy's qualification rules. ORB is
its first consumer, not its only intended one. Once this amendment
exists, any future strategy can read `EvidenceSnapshot.opening_ranges`
the same way `BosFvgStrategy` already reads `fair_value_gaps` — without
a further Evidence Engine change. Plausible future consumers (not
proposed or designed here, named only to justify why this belongs in
Evidence Engine rather than inside ORB's own strategy file): an Initial
Balance strategy, a London Breakout variant with different session
anchors than ORB's own configuration, a Session Reversal strategy that
qualifies on a *failure* to break the range, a VWAP Opening Drive
strategy, or a Mean Reversion strategy trading *back toward*
`range_midpoint` instead of away from it.

**Proposed new Evidence Engine model** (ADR-024 Amendment 3 — corrected
numbering, this session: ADR-024's own Amendment 2 slot is already used
by Fair Value Gap detection, dated 2026-07-10, unrelated to this
proposal; this document's prior references to "Amendment 2" for the
opening-range addition were a clerical numbering error, fixed here. The
addition was implemented as ADR-035 Phase 0, but `ADR-024-evidence-engine.md`
itself has never been updated with a corresponding Amendment 3 entry
recording it — a bookkeeping gap in that document, not this one, that
does not block this ADR's own Acceptance and is flagged here as a
recommended follow-up correction to ADR-024's own text):

```
OpeningRangeState:
    session: SessionName          # descriptive only -- which broad session-open window this anchor falls within. NOT the identifying key (see "Identification" below).
    range_start: datetime          # first bar's open time in the window
    range_end: datetime            # window close time (range_start + duration)
    range_start_index: int         # first included bar's position in Evidence Engine's own bar sequence for this evaluation
    range_end_index: int           # exclusive upper bound of included bars, directly comparable to FairValueGap.start_index/end_index (see §5/§9)
    range_high: float
    range_low: float
    range_midpoint: float
    is_formed: bool                # True only once range_end has fully elapsed
    is_valid: bool                 # False if a temporal gap or an insufficient bar count was detected inside the window
```

- **Identification (corrects a finding from independent Acceptance
  Review):** `session: SessionName` is descriptive metadata only, never
  the field used to pick one `OpeningRangeState` out of the plural
  `opening_ranges` tuple. §13's `orb_session_anchors` config is a list —
  nothing about `SessionName` (5 coarse values) guarantees two
  configured anchors are distinguishable by session alone (e.g., two
  different anchors could both fall within `LONDON`). The identifying
  key is instead the anchor's own `range_start`/`range_end` window,
  which is unique per anchor **once startup validation rejects any two
  configured anchors whose windows would coincide or overlap** (§13, new
  cross-field check) — the same class of fail-closed startup
  `ConfigError` this codebase already uses for other threshold
  violations, not a new validation mechanism. With that guarantee in
  place, selecting "whichever configured range is currently relevant"
  (§12, §15) means comparing the evaluation cycle's `now` against each
  `OpeningRangeState.range_start`/`range_end` directly — never matching
  by `session`, which remains purely descriptive.
- **Opening range start:** a configured hour+minute in UTC per named
  session-open (e.g., London open, New York open) — not derived from
  `SessionName`'s existing broad hour-boundary logic, which is too
  coarse for a 15-60 minute range window. New, explicit config, never
  inferred.
- **Opening range end:** `range_start + orb_range_duration_minutes`
  (configurable, e.g. 30). A single, simple duration — no
  session-dependent variable width, which would be a hidden magic
  number per pair/session (CLAUDE.md §3).
- **Timezone handling:** all range-anchor configuration is UTC-only,
  matching every other time-boundary config in this codebase
  (`compliance.daily_reset_hour_utc`, Evidence Engine's own session
  hours) — no local-time input anywhere, avoiding an entire class of
  ambiguity.
- **DST handling:** explicitly NOT DST-aware, by the same convention
  `compliance_state_store`'s `daily_reset_hour_utc` already documents
  ("not DST-aware — update this value if your broker's own UTC offset
  changes with DST"). An operator updates `orb_range_start_hour_utc`
  twice a year if their broker's session times shift with DST. This is
  a known, accepted, already-precedented limitation — not a new one.
- **Range calculation:** `range_high`/`range_low` are the max high / min
  low of every **closed** bar (never a forming bar — mirrors
  `market_data_ingestion`'s own closed-bar-only retention rule) whose
  `bar_open_time` falls within `[range_start, range_end)`.
  `range_midpoint = (range_high + range_low) / 2`. `range_start_index`/
  `range_end_index` are the positions of that same bar subset within the
  bar sequence Evidence Engine already holds internally while computing
  the rest of an `EvidenceSnapshot` (structure, FVGs, candlesticks) —
  no second bar source, just two additional integer offsets recorded
  alongside the datetime bounds already described above.
- **Multiple session support:** the proposed model is computed
  independently per configured session-open (e.g., both a London-open
  range and a New York-open range could be configured simultaneously) —
  `EvidenceSnapshot.opening_ranges: Tuple[OpeningRangeState, ...]`
  (plural), not a single value, so ORB can qualify against whichever
  configured range's window (per "Identification" above) is currently
  relevant to the evaluation cycle.
- **Fail-closed (corrects a finding from independent Acceptance
  Review):** `is_valid=False` (and therefore `NOT_QUALIFIED` for ORB,
  never a best-effort range) if fewer than a configured minimum bar
  count formed the range, **or if Evidence Engine's own check of
  `bar_open_time` spacing across the closed bars in `[range_start,
  range_end)` finds a gap against a newly-introduced "expected bar
  interval" value** (a config concept Evidence Engine does not have
  today and this amendment must introduce — see §17 Phase 0). This is
  an independent computation inside Evidence Engine, not a reuse of
  `market_data_ingestion`'s own gap flag: that flag is surfaced only
  through `market_data_ingestion`'s own `IngestionResult`/health
  snapshot and is never attached to the `Bar` objects Evidence Engine
  actually receives, so it cannot be "reused" at this layer. Evidence
  Engine already receives every closed bar's `timestamp`
  (`Bar.timestamp`), which is sufficient to detect a temporal gap on
  its own once it knows the expected interval — the same kind of
  self-contained fact-derivation Evidence Engine already performs for
  structure, FVGs, and support/resistance from bars alone.

---

## 4. Breakout qualification

Objective, deterministic rules — every threshold named in config
(§13), none hardcoded. Throughout §§4-9, **`range_boundary`** means
`range_high` when evaluating a bullish (BUY) breakout candidate and
`range_low` when evaluating a bearish (SELL) one — defined once here,
not restated at each use below.

- **Range must be formed and valid** (`is_formed and is_valid`) before
  any breakout logic runs — otherwise NOT_QUALIFIED (`"range not yet
  formed"` / `"range invalidated by a data gap"`).
- **Close beyond range:** the most recent **closed** bar's close must
  be beyond `range_high` (bullish candidate) or below `range_low`
  (bearish candidate) — never a wick-only touch, never a forming bar.
- **Minimum breakout distance:** `abs(close - range_boundary) >=
  orb_min_breakout_distance_atr_multiple * evidence.volatility.atr` —
  an ATR-relative filter (never a fixed-pip magic number, since ATR
  already varies appropriately per pair/volatility regime), consistent
  with how `SessionBreakoutStrategy` already gates on
  `volatility.volatility_score`/`is_expansion` rather than a fixed
  distance.
- **Body size / wick tolerance (formula corrected per independent
  Acceptance Review — prose and formula previously referenced two
  different quantities):** the breakout bar's body (`abs(close - open)`)
  must be at least `orb_min_body_to_range_ratio * (bar.high - bar.low)`
  — the ratio applies to **the breakout bar's own high-low span**, never
  the opening range's width (`range_high`/`range_low` elsewhere in this
  document always mean the opening range's boundaries, not any single
  bar's). Rejects a breakout bar that is mostly wick (indecision), a
  standard candlestick quality check already precedented by Evidence
  Engine's own `candlesticks.py` pattern matching (reused as a *concept*,
  not a second implementation — see §6, ORB reuses `evidence.candlesticks`
  directly rather than reimplementing wick-ratio logic).
- **Momentum:** `evidence.volatility.is_expansion` must be `True` —
  identical field `SessionBreakoutStrategy` already requires; a
  breakout with no volatility expansion is definitionally suspect.
- **False-break filter:** the breakout bar must not have already
  reversed back inside the range by the time of evaluation (checked via
  the same closed-bar close condition above — a bar whose low taps
  beyond `range_low` but closes back inside the range never satisfies
  "close beyond range" in the first place, so false intrabar breaks are
  excluded by construction, not by a separate reversal check).
- **Minimum confirmation candles:** configurable
  `orb_min_confirmation_candles` (default 1) — requires that many
  consecutive closed bars beyond the range boundary before qualifying,
  trading immediacy against false-break resistance; default of 1
  preserves "first-close-beyond-range" as the base case, consistent
  with `SessionBreakoutStrategy`'s own single-bar evaluation.

---

## 5. FVG confirmation

**Optional, weighted — never mandatory, never ignored.** Mandatory would
reject genuine ORB setups that break out cleanly with no imbalance left
behind (common on strong, gap-free trends); ignored would waste a
signal Evidence Engine already computes for free. Weighted matches
`BosFvgStrategy`'s own precedent of using FVGs as a scoring input, not a
hard gate.

- **Reuses `evidence.fair_value_gaps` directly** — no second FVG
  detector (§0).
- **Temporal comparison (corrects a finding from independent Acceptance
  Review):** `FairValueGap.start_index`/`end_index` are bar-sequence
  indices, not timestamps, and `EvidenceSnapshot` does not expose the
  raw bar sequence a strategy could use to convert an index to a time.
  "Formed at or after `range_start`" is therefore evaluated as **`gap.
  start_index >= opening_range.range_start_index`** — comparing two
  integers Evidence Engine already computes from the same internal bar
  sequence (§3), never a datetime-to-index conversion inside the
  strategy. This is the one, decided mechanism; no alternative is left
  open.
- **Bullish FVG:** required to be same-direction as a bullish breakout
  candidate (`FairValueGap.direction` matching `StructureDirection` up),
  unfilled (`not gap.filled`), and formed at or after `range_start` per
  the index comparison above (an FVG from before the range formed is
  unrelated context, not confirmation of *this* breakout).
- **Bearish FVG:** the mirror.
- **Maximum age:** configurable `orb_fvg_max_age_bars` — an FVG many
  bars stale is weak confirmation of a fresh breakout.
- **Minimum size:** configurable `orb_fvg_min_size_atr_multiple`
  (`gap_high - gap_low` relative to ATR) — a trivially small gap
  contributes negligible confirmation.
- **Overlap requirement:** the FVG's `[gap_low, gap_high]` must overlap
  the breakout price zone (between `range_boundary` and the breakout
  bar's close) — an FVG far from the actual breakout price is unrelated.
- **Expiration:** an FVG already `filled=True` never contributes (same
  field Evidence Engine already maintains — no new fill-tracking).
- **Weighting:** presence of a qualifying FVG adds a bounded scoring
  bonus (§4's score calc, mirrors `SessionBreakoutStrategy`'s weighted-sum
  pattern: `score = clamp(w1*range_quality + w2*mi_session_score +
  w3*volatility_score + w4*fvg_bonus)`, weights configurable, sum-bounded
  so FVG absence never disqualifies, only fails to add the bonus).

---

## 6. Entry logic

- **Entry type:** breakout entry only (qualification itself *is* the
  breakout event — ORB does not qualify in anticipation of a future
  break). No stop-entry, no limit-entry, no retest-entry variant in
  this proposal — Strategy Engine produces a qualification + directional
  `TradeIntent`, never an order type; order mechanics belong to
  Execution/Bridge, unchanged, out of this ADR's scope (mirrors every
  existing strategy — none specifies an order type either).
- **Multiple entries:** not applicable at the Strategy Engine layer —
  `RuntimeOrchestrator`'s existing in-flight-command/reservation
  machinery (ADR-034) already prevents duplicate submissions for the
  same pair/cycle; ORB introduces no new duplicate-prevention logic,
  reusing what exists.
- **Maximum entries / session lockout:** proposed new config
  `orb_max_qualifications_per_range` (default 1) — once ORB has
  produced one `QUALIFIED` result for a given `(pair, range_start)`,
  subsequent cycles against the *same* range return NOT_QUALIFIED
  (`"already qualified for this opening range"`), preventing the same
  breakout from re-qualifying every cycle until the range rolls over.
  This state is the *strategy's own*, session-scoped, in-memory record
  (a `Dict[(pair, range_start), bool]`-shaped concept) — never persisted
  cross-restart, mirroring that Strategy Engine strategies are otherwise
  stateless per ADR-026 (an explicit, narrow, documented exception,
  analogous to how `market_data_ingestion`'s `WarmupTracker` is the one
  documented stateful exception in its own package).
- **Duplicate prevention:** the above, plus Runtime's existing
  reservation/in-flight guarantees — no new mechanism invented.

---

## 7. Position management

Entirely out of Strategy Engine's authority (ADR-026 Hard Rule 1,
unchanged) and therefore out of this ADR's scope: one-trade-per-session
enforcement is the §6 lockout above (a qualification-time concern);
same-direction stacking, opposite-direction handling, partial exits,
scaling, and re-entry are Position Manager/Risk Engine/Compliance
Engine concerns, all pre-existing and unmodified. ORB supplies exactly
one `QualificationResult` with a `TradeIntent`, same as every other
strategy — nothing downstream needs to change to accommodate it.

---

## 8. Stop loss

**Per §0's verified boundary: Titan does not compute stop-loss price
levels anywhere today (ADR-031 §3, disclosed).** This ADR does not
close that gap — doing so is explicitly out of scope (Minimal Change
Engineer: a new strategy's ADR is not the place to retroactively design
system-wide price-level stop computation).

**What ORB does contribute, within its own qualification output:** the
opening range's `range_low` (for a bullish breakout) or `range_high`
(for a bearish breakout) is the structurally obvious invalidation level
— already available as plain data on `OpeningRangeState`, requiring no
new computation. This is recorded only as part of `QualificationResult.reason`/
`strengths` (human/audit-readable text, exactly how every existing
strategy already reports its reasoning) — never as a numeric field that
would imply Strategy Engine sets stops (Hard Rule 1). If/when a future
ADR closes ADR-031 §3 system-wide, that mechanism would naturally
consume `OpeningRangeState.range_low`/`range_high` the same way it would
consume any other strategy's structural levels — a forward-compatible
hook, not a dependency this ADR requires.

---

## 9. Take profit

Same boundary as §8 applies identically — no price-level target is
computed by Strategy Engine today, and ORB does not change that.
`range_midpoint`-to-`range_high`/`range_low` distance (i.e., the range's
own width) is available as a natural R-multiple reference *if* a future
system-wide mechanism needs one, recorded the same way (descriptive
text only, never a numeric field on `QualificationResult`).

---

## 10. Risk management

- **Risk per trade / per session:** Risk Engine's existing
  confidence-tier + volatility + Kelly sizing (`position_sizing.py`,
  unchanged) already governs this for every strategy uniformly; ORB
  supplies `confidence` (0-1, from range-quality/FVG-confirmation
  strength, same scale every strategy already uses) into that existing
  pipeline — no ORB-specific sizing path.
- **Daily loss interaction:** Compliance Engine's existing daily-loss
  gate (unchanged, and now correctly bootstrapped per KNOWN_GAPS #9)
  applies uniformly to any ORB-originated trade exactly like any other.
- **Maximum losses / consecutive losses:** Compliance Engine's existing
  `consecutive_loss.py`, unchanged, pair- and account-level, not
  strategy-specific — no new logic.
- **Maximum open positions / exposure interaction:** Risk Engine's
  existing `exposure.py`/`safety_limits.py`/`correlation.py`, unchanged
  — ORB participates in the same portfolio-level checks as every other
  strategy's qualified trade.

**No new risk mechanism is proposed.** ORB is a new *signal source*,
not a new risk authority — consistent with "Strategies may confirm each
other; they may never create duplicate signals or bypass guards"
(CLAUDE.md §2).

---

## 11. Evidence Engine integration

ORB does **not** generate a raw signal independently of Evidence
Engine, and does not compute its own score outside the qualification
scoring already described in §4/§5. Its role, precisely:

- **Consumes** `EvidenceSnapshot` (structure, volatility, fair value
  gaps, candlesticks, support/resistance, and the proposed new
  `opening_ranges`) and `MarketIntelligenceSnapshot` (session, news,
  liquidity) — exactly the same two inputs every existing strategy
  receives via `Strategy.qualify()`. No new input type, no bypass of
  Evidence Engine's "sole interpreter of market data" authority
  (ADR-024 Hard Rule, unchanged).
- **Produces** one `QualificationResult` (score 0-100, confidence 0-1,
  `TradeIntent`) — a confirmation-weighted output, not a primary
  trigger independent of Evidence Engine's own facts. "Primary trigger"
  vs. "confirmation" is not a meaningful distinction at this layer:
  every strategy, ORB included, is itself one candidate among several
  competing in the existing selection cascade (§0) — none of the five
  existing strategies is privileged as more "primary" than another, and
  ORB does not seek that status either.
- **Scoring interaction:** identical shape to `SessionBreakoutStrategy`'s
  weighted-sum pattern (§4/§5) — no new scoring engine, no
  ScoringEngine reference-only package (`phantom_pipeline/scoring_engine/`)
  involvement, since that package is reference-only per ADR-001 and was
  never re-authorized as a running authority.

---

## 12. Strategy Router compatibility

As established in §0, **the "Strategy Router" Titan needs today already
exists** as `selection.py`'s 6-step cascade. No new component is
proposed. ORB's compatibility with it:

- **Required metadata:** the same 13-field `StrategyDefinition` every
  strategy must declare (ADR-026 §1) — `strategy_id=StrategyId.
  OPENING_RANGE_BREAKOUT`, `market_regime=MarketRegime.BREAKOUT`,
  `preferred_sessions` set to whichever named session-opens are
  configured, and the remaining ten fields filled the same way
  `SessionBreakoutStrategy`'s are.
- **Confidence outputs:** `QualificationResult.confidence` (0-1),
  identical scale/semantics to every other strategy — the cascade's
  step 2 (evidence-alignment) consumes this uniformly; ORB requires no
  special-casing there.
- **Market regime suitability:** `MarketRegime.BREAKOUT` (existing enum
  value, shared with `SessionBreakoutStrategy` — both target the same
  regime via different, non-duplicate mechanisms: session-wide
  volatility expansion vs. a fixed opening range).
- **Priority:** none proposed — the existing cascade has no notion of a
  strategy-level priority weight beyond the six deterministic steps;
  introducing one for ORB alone would be inconsistent special
  treatment, not architecture ORB should invent unilaterally.
- **Selection criteria:** unchanged — ORB simply becomes one more
  candidate in `qualifications: Sequence[QualificationResult]` passed
  into `select_winning_strategy()`. If ORB and, say,
  `SessionBreakoutStrategy` both qualify the same pair/cycle with tied
  scores, the existing cascade's steps 2/5/6 resolve it exactly as
  designed today — no ORB-specific tiebreak.

If a genuinely separate, more sophisticated Strategy Router is ever
designed (e.g., one consuming Research & Learning Engine's historical
per-strategy performance — steps 3/4 of the current cascade are already
reserved placeholders for exactly this), ORB requires no changes to
participate: it already exposes everything the placeholder steps
would need (a `StrategyId` to key historical performance by, a
`QualificationResult` to rank).

---

## 13. Configuration

All new fields, `StrategyEngineConfig`-scoped (mirrors
`session_breakout_min_session_score` / `bos_fvg_min_structure_score`
naming convention — no magic numbers, every threshold named):

| Parameter | Type | Default | Safe range | Recommended range |
|---|---|---|---|---|
| `orb_approved_pairs` | `Tuple[str, ...]` | `()` (none — fail closed until configured) | any valid symbol set | major pairs with reliable session-open liquidity |
| `orb_session_anchors` | config list of `(SessionName, start_hour_utc, start_minute_utc)` | `()` | valid UTC hour/minute | London open, New York open |
| `orb_range_duration_minutes` | `int` | 30 | 5-120 | 15-60 |
| `orb_min_range_bars` | `int` | 3 | ≥ 2 | 3-6 (depends on chosen bar timeframe) |
| `orb_min_range_atr_ratio` | `float` | 0.5 | > 0 | 0.4-0.8 |
| `orb_max_spread_pips` | `float` | 3.0 | > 0 | broker/pair-dependent |
| `orb_min_breakout_distance_atr_multiple` | `float` | 0.15 | > 0 | 0.1-0.3 |
| `orb_min_body_to_range_ratio` | `float` | 0.5 | 0-1 | 0.4-0.7 |
| `orb_min_confirmation_candles` | `int` | 1 | ≥ 1 | 1-2 |
| `orb_fvg_max_age_bars` | `int` | 10 | ≥ 1 | 5-20 |
| `orb_fvg_min_size_atr_multiple` | `float` | 0.1 | > 0 | 0.05-0.2 |
| `orb_fvg_score_weight` | `float` | 0.15 | 0-1 (bounded, sums with other weights ≤ 1) | 0.1-0.2 |
| `orb_min_liquidity_score` | `float` | 60.0 | 0-100 | 55-75 |
| `orb_max_qualifications_per_range` | `int` | 1 | ≥ 1 | 1 |

Every field fails closed at config-load time for an out-of-safe-range
value (mirrors `config_loader.py`'s existing `ConfigError` pattern for
every other threshold) — not implemented here, specified for the
implementation phase.

**Cross-field validation (required, per independent Acceptance
Review):** in addition to each field's own range check, config loading
must fail closed if:

- Any two entries in `orb_session_anchors` would produce coincident or
  overlapping `[range_start, range_end)` windows on the same trading day
  — this is what makes §3's identification rule (matching by window,
  not by `SessionName`) unambiguous; without this check, two anchors
  could collide.
- `orb_min_range_bars` is infeasible for the configured
  `orb_range_duration_minutes` given the bar timeframe Evidence Engine
  is actually configured for (e.g., a 3-bar minimum cannot be satisfied
  by a 30-minute window if the configured timeframe means only one bar
  forms in that time).
- The weighted-scoring components in §5 (`orb_fvg_score_weight` and any
  sibling weights in the same weighted sum) do not sum to ≤ 1.

---

## 14. Fail-closed behavior

ORB returns `NOT_QUALIFIED` (never `QUALIFIED` with a partial/guessed
value — ADR-026 Hard Rules 3-4, unchanged) whenever any of:

- Pair outside `orb_approved_pairs` → `NOT_ELIGIBLE` (hard gate, before
  any other check, identical to every existing strategy).
- No configured session anchor matches the current evaluation session.
- Opening range not yet formed (`is_formed=False`).
- Opening range invalidated by a data gap or insufficient bar count
  (`is_valid=False`).
- Spread exceeds `orb_max_spread_pips` at evaluation time.
- News blackout active (`pair_safety.news.blackout_active`).
- Liquidity below `orb_min_liquidity_score`.
- Market closed / holiday (`MarketSafetyInputs`).
- No breakout condition met (§4).
- No directional fact available to derive `TradeIntent` — same
  fail-closed pattern as `SessionBreakoutStrategy._breakout_trade_intent()`
  returning `None`: ORB never guesses a direction.
- Already qualified for this `(pair, range_start)` (§6 lockout).
- A configuration value is out of its declared safe range at startup
  (fails closed at process start, never at evaluation time — consistent
  with every other `ConfigError`-raising field in this codebase).
- Time ambiguity: a `now` timestamp that cannot be unambiguously placed
  relative to `range_start`/`range_end` (e.g., naive datetime with no
  UTC assumption) — Evidence Engine's own existing convention already
  treats naive datetimes as UTC (`trading_day_id_for()`'s precedent);
  ORB's proposed Evidence Engine amendment follows the same rule, so
  "ambiguous" in practice reduces to "malformed input," which upstream
  validation (`market_data_ingestion`, unchanged) already rejects before
  Evidence Engine ever sees it.

---

## 15. Edge cases

| Case | Handling |
|---|---|
| Gap open (price opens far from prior close) | If the gap occurs *before* `range_start`, irrelevant to range formation. If a bar is missing *inside* the range window, `is_valid=False` (§3) — never bridged/interpolated. |
| Missing candles | Same `is_valid=False` path — detected by Evidence Engine's own `bar_open_time`-spacing check against the expected bar interval (§3), independent of `market_data_ingestion`'s own gap flag, which does not propagate to this layer (§3). |
| Session reconnect (Bridge/EA restart mid-range) | If bars were missed during the outage, `is_valid=False`. If no bars were missed (a fast reconnect), the range forms normally — no ORB-specific reconnect logic needed since it operates on already-validated bars, not on the connection's own state. |
| DST transitions | Explicitly not handled automatically (§3) — operator updates the UTC anchor hour twice yearly, an already-precedented limitation, not a new one. |
| Holiday sessions | `MarketSafetyInputs.holidays`/`market_closed` — NOT_QUALIFIED, never locally inferred (§2). |
| Multiple ranges (e.g. London open + New York open configured together) | `EvidenceSnapshot.opening_ranges` is plural (§3) — ORB's `qualify()` selects whichever configured range's `range_start`/`range_end` window is currently relevant, per §3's "Identification" rule (never by `session` alone, which cannot disambiguate two anchors sharing a `SessionName`); if none matches, NOT_QUALIFIED (no ambiguity, no "closest" guess). Startup validation (§13) rejects any two configured anchors whose windows would coincide or overlap, so at most one match is ever possible. |
| Broker time differences | All range anchors are UTC-only (§3) — a broker whose own server time differs from UTC is already normalized upstream by however bar timestamps are supplied (`market_data_ingestion`'s existing `broker_timestamp`/`source_timestamp` clock-skew validation, ADR-033, unchanged); ORB does not add a second time-normalization layer. |
| Partial trading days (early close, e.g. holiday-adjacent half day) | Covered by `MarketSafetyInputs.early_closes` (existing, ADR-025) — if the configured range window falls after an early close, no further bars exist to complete `is_formed`, so the range simply never forms (fails closed by absence of data, not a special case to code for). |

---

## 16. Architecture review

| Principle | Verified |
|---|---|
| Single responsibility | ORB (Strategy Engine) qualifies; the proposed opening-range computation (Evidence Engine) interprets market data; neither computes the other's concern. |
| Minimal change | Reuses `fair_value_gaps`, `volatility.atr`, `pair_safety.*`, the existing selection cascade, existing eligibility gate, and existing config-loading conventions verbatim; the only new engine-level code is one Evidence Engine amendment (opening-range computation) plus one Strategy Engine strategy — no new package, no new pipeline stage. |
| Dependency inversion | ORB depends on `EvidenceSnapshot`/`MarketIntelligenceSnapshot` abstractions exactly as the `Strategy` interface already requires — no direct dependency on `market_data_ingestion`, `news_ingestion`, or the Bridge. |
| Modular architecture | New code lives entirely within `titan_protocol/strategy_engine/strategies/` (ORB) and `titan_protocol/evidence_engine/` (opening-range amendment) — no cross-cutting reach into Risk/Compliance/Runtime. |
| Fail-closed behavior | §14 — every ambiguous or incomplete condition returns `NOT_QUALIFIED`/`is_valid=False`, never a best-effort guess. |
| Capital preservation | ORB adds a signal source; it does not weaken any existing gate. Risk/Compliance/Runtime remain the only authorities over sizing, daily loss, and execution — unchanged. |
| Strategy separation | ORB confirms itself independently (§11) — it does not read another strategy's qualification, and no existing strategy is modified to accommodate it. |
| Runtime ownership | `RuntimeOrchestrator` is unmodified by this proposal — ORB is just one more registered `Strategy`, discovered the same explicit way as the other five. |

No violation identified.

---

## 17. Implementation roadmap (proposed — not started)

**Each phase below includes its own implementation, unit tests, and
validation as part of that phase — none defers testing to a later phase
(corrects a wording issue from independent Acceptance Review: this
project's own established practice, visible throughout its history,
always pairs an "Implement X" step with a "Write X test suite" step
immediately after, never batched at the end; the phase ordering itself
is unchanged, only this clarification is added).**

- **Phase 0 — ADR-024 Amendment 3 (Evidence Engine, implemented):** add
  `OpeningRangeState` model (including `range_start_index`/
  `range_end_index`, §3) + `opening_range.py` computation (including the
  independent temporal-gap check against a newly-introduced expected-bar-
  interval concept, §3) + `EvidenceSnapshot.opening_ranges` field, with
  its own unit tests (range calculation, `is_formed`/`is_valid`
  transitions, the gap check, index/datetime consistency). Requires its
  own Accepted status before Phase 1 begins (CLAUDE.md §1.10).
- **Phase 1 — Core ORB detection:** consume `opening_ranges` inside a
  new `OrbBreakoutStrategy` (naming to match `StrategyId.
  OPENING_RANGE_BREAKOUT`); range-formed/valid checks only, no
  qualification scoring yet — with its own unit tests for exactly that
  scope. **The §6 session-lockout moves to Phase 2 (revised this
  session, §18.A item 2):** Phase 1's `qualify()` cannot produce a
  `QUALIFIED` result under any input (no breakout-qualification rule
  exists until Phase 2), so the lockout's own consumption event (§6:
  "once ORB has produced one `QUALIFIED` result") can never fire within
  Phase 1's scope — building lockout state (in-memory or persisted) that
  can never be written is speculative scaffolding for a condition that
  cannot occur, not a genuine Phase 1 requirement (CLAUDE.md §7). Moving
  it to Phase 2 also means Phase 1's `OrbBreakoutStrategy` needs no
  constructor/instance state at all, matching every existing strategy's
  stateless convention (ADR-026) rather than introducing this package's
  first stateful strategy a phase before that statefulness has any
  observable effect.
- **Phase 2 — Breakout qualification and session lockout:** §4's
  objective rules (close beyond range, ATR-relative distance, corrected
  body/wick ratio, momentum, confirmation-candle count) — the first
  phase at which `qualify()` can produce `QUALIFIED`, and therefore the
  first phase at which the §6 session-lockout has anything to protect.
  **Newly-discovered precondition (RPI Research, 2026-07-26, see
  `docs/plans/adr-035-phase2-orb-breakout-lockout.md`): §4's rules
  require bar-level OHLC evidence (the most recent closed bar's close,
  the breakout bar's own body/high/low) that no field on
  `EvidenceSnapshot` exposes today — `evaluate_snapshot()` discards
  `bars` after its analysis pass, and no existing field substitutes.
  This gates Phase 2 implementation the same way item 2 below gates it
  on persistence design: a proposed `ADR-024-evidence-engine.md`
  Amendment 4 (Proposed, not yet Accepted — see that document) must be
  independently reviewed and Accepted before Phase 2 implementation may
  begin. This ADR's own Acceptance (2026-07-25) did not anticipate this
  gap; it is recorded here, not silently absorbed into Phase 2's
  existing text, per this project's "never silently move an item
  between phases" discipline.**
  **§18.A item 2's persistence requirement gates this phase, not Phase
  1:** the lockout state must survive a process restart (resolved this
  session — see §18.A item 2), owned by Strategy Engine, requiring its
  own small, Strategy-Engine-owned persistence mechanism (analogous in
  convention to `titan_protocol/compliance_state_store/` — file-backed,
  atomic write, schema-versioned, fail-closed on corruption/unavailable
  state — but a separate package, never a reuse of another engine's
  store, per ADR-026 Hard Rule 5). That mechanism's own concrete design
  is new architecture and requires its own focused review (a Phase 2 RPI
  Plan addendum or a further ADR-035 amendment) before Phase 2
  implementation begins — this ADR authorizes the requirement, not the
  implementation. With unit tests for each breakout rule individually,
  each fail-closed path, and the full lockout/persistence behavior
  (first consumption, duplicate attempt, restart-survival, corrupt/
  unavailable state, different pair/range unaffected).
- **Phase 3 — FVG confirmation:** §5's weighted scoring addition,
  including the corrected index-based temporal comparison, with unit
  tests covering direction matching, age, size, overlap, and expiration.
- **Phase 4 — Market Intelligence/eligibility integration:** session
  anchor matching (using §3's corrected identification rule), news/
  liquidity/holiday gates, eligibility hard gate, with unit tests for
  each gate. **News-blackout enforcement is evaluation-time-only for
  this phase, a staged limitation requiring Amendment 1's independent
  review and Acceptance before Phase 4 implementation may proceed — see
  Amendment 1, above, and Phase 7, below.**
- **Phase 5 — Configuration:** §13's fields wired through
  `StrategyEngineConfig`, `config_loader.py`, and the example config,
  each with startup fail-closed validation and the cross-field checks
  named in §13 (duplicate/overlapping anchors, bar-count feasibility,
  weight-sum bound), with unit tests for every validation path.
- **Phase 6 — Full-suite validation:** integration (real
  five-plus-ORB `StrategyEngine` competing in the real selection
  cascade), regression (existing five strategies' behavior unchanged —
  `git diff --stat` showing zero change to any of them), exception
  safety, and every edge case in §15 — the cross-phase pass that only
  full end-to-end wiring makes possible, not the first point at which
  any test exists.
- **Phase 7 — Formation-time news-blackout closure (not yet scheduled,
  proposed by Amendment 1, above; no RPI Research performed):** design
  and implement whichever mechanism closes the gap Amendment 1
  authorizes Phase 4 to leave open — a persisted per-`(pair,
  range_start)` formation-window blackout history, or a reviewed
  Evidence-Engine dependency on Market Intelligence's news output.
  Requires its own Research → Plan → Implement pass and its own Accepted
  ADR-035 amendment (or further amendment) before any code changes.

Each phase requires its own review before the next begins, per this
project's established RPI (Research → Plan → Implement) workflow
(`.claude/agents/TEAM.md` §9) — this document is the Research artifact
for Phase 0 only; Phases 1-6 each need their own Plan artifact once
Phase 0 is Accepted.

---

## 18. Open design decisions

None of the items below block **Acceptance** of this ADR — they are
implementation-detail decisions the phased roadmap (§17) resolves at
the appropriate gate, not architectural objections. They are split
accordingly.

### 18.A Required before implementation

These must be resolved before the phase that depends on them starts —
Phase 0 and Phase 1 specifically (§17) — but do not block this
document's own architectural approval:

1. **~~Should `OpeningRangeState` live in `support_resistance.py` (the
   nearest existing analog) or as a new sibling module
   `opening_range.py`?~~ RESOLVED — Phase 0 implemented it as the
   sibling module `titan_protocol/evidence_engine/opening_range.py`**
   (commit `ee976f4`), matching this document's original assumption.
   No longer open.
2. **Should `orb_max_qualifications_per_range`'s lockout state survive a
   process restart? RESOLVED THIS SESSION — persistence is required in
   principle; the concrete storage mechanism is new architecture,
   deliberately deferred to Phase 2 (§17), which is also the first phase
   at which the answer has any observable effect.** Full resolution:
   - **Semantic requirement:** YES, persistence is required. ORB's own
     purpose for this field (§6: "preventing the same breakout from
     re-qualifying... until the range rolls over") is "at most N
     qualifications per opening range," full stop — not "at most N per
     opening range unless the process happens to restart first." A
     restart mid-range is an ordinary, anticipated operational event
     (§15 already documents "Bridge/EA restart mid-range" as a normal
     case, not an exotic failure), and CLAUDE.md §1's Priority-1 rule
     ("No duplicate trades... Capital preservation overrides profit")
     outranks this document's own original assumption that in-memory,
     session-scoped state was sufficient — that assumption is
     superseded here, not merely revisited.
   - **Restart/re-entry evidence (re-verified this session, unchanged
     from the prior investigation):** a direct trace of every existing
     duplicate-control mechanism
     (`titan_protocol.risk_engine.reservation.ReservationLedger`,
     `titan_protocol.runtime.in_flight_commands.InFlightCommandRegistry`,
     `titan_protocol.compliance_engine`'s `max_positions_per_pair`)
     confirms **none of them retains any memory of "this pair already
     had an ORB trade for this specific opening range" once that trade
     has closed** — `ReservationLedger` releases its reservation and
     `InFlightCommandRegistry` releases its entry at the trade's own
     terminal/confirmed state; `max_positions_per_pair` is fed by live,
     current `/bridge/positions` reports, so it only blocks a *second
     simultaneously open* position, never a *new* one after the first
     has already closed; and a repository-wide search confirms zero
     file under `risk_engine/`, `compliance_engine/`, or `runtime/`
     references `range_start` or any opening-range concept at all —
     none of these engines has the vocabulary to know what "this
     opening range" even means. **Concrete consequence:** without
     persisted lockout state, a restart while the same `(pair,
     range_start)` window is still current, after an earlier trade for
     it has already closed, could allow a second `QUALIFIED` result (and
     therefore a second trade) for the same opening range once Phase 2
     exists — classified **POSSIBLE**, not already-prevented.
   - **Ownership:** Strategy Engine. The fact "this opening range has
     already produced N qualifications" is a strategy-qualification
     concern (ADR-026 Hard Rule 5) — no other engine has opening-range
     vocabulary (above), and none should acquire it merely to host this
     one fact.
   - **Storage architecture:** no existing persistence mechanism may be
     reused. Strategy Engine owns no persistence mechanism of its own
     today (confirmed: no state-store module exists anywhere under
     `titan_protocol/strategy_engine/`), and reusing
     `compliance_state_store` or `runtime/in_flight_store.py` to hold a
     *different* engine's qualification state would blur exactly the
     engine-ownership boundary ADR-026 Hard Rule 5 exists to keep clean.
     A new, small, Strategy-Engine-owned store is required — in
     *convention* analogous to `titan_protocol/compliance_state_store/`
     (its own sibling top-level package, not nested inside the engine it
     serves; file-backed JSON; atomic write via a temp file + `os.replace`;
     schema-versioned; a `.bak` rotation; fail-closed on a corrupt or
     unreadable file, never a silent reset) — but its own package, never
     a reuse of `compliance_state_store` itself. This is new
     architecture and requires its own focused review (a Phase 2 RPI
     Plan addendum, or a further ADR-035 amendment) before Phase 2
     implementation begins; this ADR authorizes the requirement and its
     governing conventions, not a specific implementation.
   - **Counter consumption semantics:** the lockout counts `qualify()`
     returning `QUALIFIED` (§6's own words: "once ORB has produced one
     `QUALIFIED` result"), never a later event (selection, reservation,
     command submission, or execution). This is deliberately the
     strictest, most conservative trigger available — it can only cause
     ORB to under-trade (skip a would-be-selected opportunity because an
     earlier cycle qualified but lost the selection cascade), never to
     over-trade, consistent with "capital preservation overrides profit."
   - **State identity:** `(pair, range_start)`, unchanged — `range_start`
     is already the unique, collision-checked per-anchor identity §3's
     "Identification" correction establishes (startup validation rejects
     overlapping anchors), and is directly available on
     `OpeningRangeState` without inventing a new field.
   - **Fail-closed persistence principle (governs whatever Phase 2's own
     store design produces):** if persisted state cannot be read, is
     corrupt, or is an unsupported schema version, ORB must not qualify
     the affected `(pair, range_start)` until the state is resolved —
     mirroring `compliance_state_store`'s own `CorruptStateError`
     precedent (fail closed, never silently treat unreadable state as
     "not yet consumed"). A write failure after a qualification is
     produced must not be silently swallowed; the qualification that
     already occurred stands (it already happened), but the mechanism
     must not paper over its own inability to record it.
   - **Why this does not block Phase 1:** Phase 1's `OrbBreakoutStrategy.
     qualify()` cannot produce `QUALIFIED` under any input (§9 of the
     Phase 1 Plan — every path returns `NOT_QUALIFIED`, since no
     breakout-qualification rule exists until Phase 2). The lockout's own
     consumption event, above, therefore cannot fire within Phase 1's
     scope regardless of whether the state is in-memory or persisted —
     building storage for a write that cannot occur yet would be
     speculative code for a scenario that cannot occur (CLAUDE.md §7).
     The lockout mechanism itself (design, storage, and its own tests)
     accordingly moves to Phase 2 (§17), the first phase at which it has
     any observable effect. Phase 1 needs no persistence decision and
     introduces no stateful strategy instance.

### 18.B Future design considerations

These do not block any implementation phase and may be revisited at or
after the phase noted, without requiring a return to this ADR:

3. **Exact default values in §13** are proposed, reasonable starting
   points, not empirically validated — real backtesting/forward-testing
   (Validation Engine, ADR-030, existing) should inform final defaults
   before Phase 5, not before.
4. **Should ORB be limited to major pairs only at first
   (`orb_approved_pairs` empty by default, fail-closed until an operator
   configures it), or ship with a starter default list?** A Phase 5
   configuration question, not a Phase 0-4 blocker. This document
   proposes empty-by-default (safest, forces deliberate operator choice).
5. **Whether a genuinely separate Strategy Router (beyond the existing
   `selection.py` cascade) is still on the roadmap at all**, given §12's
   finding that the cascade already fulfills that role today. This is
   independent of ORB entirely — if a more sophisticated router is still
   desired, that is its own ADR, not a prerequisite or blocker for ORB
   at any phase.

---

## 19. Acceptance criteria

This ADR was marked **Accepted** (2026-07-25) once, and only once, all
of the following held — recorded below as satisfied, not as a
still-pending gate:

- The architecture described in §§0-16 is approved as sound by
  independent review (this document's own §0 self-audit is not a
  substitute for that review). **Satisfied** — Independent Acceptance
  Review (F1-F5, `af5b9c0`).
- The companion Evidence Engine amendment (§3, proposed as ADR-024
  Amendment 3) is itself approved — this ADR's Phase 1 cannot begin
  without it, so its approval is a precondition of this ADR's
  Acceptance, not a separate, independently-timed decision.
  **Satisfied** — implemented as Phase 0 (`ee976f4`), independently
  reviewed (F1-F4) and validated (22+5 tests green). Note:
  `ADR-024-evidence-engine.md` itself has not yet been updated with a
  corresponding Amendment 3 entry recording this — a documentation gap
  in that ADR, not this one (§3).
- No conflict is found with ADR-024 (Evidence Engine), ADR-025 (Market
  Intelligence), or ADR-026 (Strategy Engine) — verified, not assumed
  (§0 performed this check against current code; independent review
  should re-verify against whatever code state exists at review time).
  **Satisfied** — re-verified this session.
- No violation of the Engineering Charter (CLAUDE.md) is found,
  including but not limited to: no duplicate logic (§0's FVG/ATR/session
  reuse), no position sizing or price-level stop/target introduced into
  Strategy Engine (§7-9), and fail-closed behavior on every ambiguous or
  incomplete condition (§14). **Satisfied.**
- §18.A's two required-before-implementation decisions are explicitly
  resolved (not silently defaulted): item 1 before Phase 0 began
  (satisfied — Phase 0 implemented and resolved it); item 2 before
  Phase 2 begins (resolved in direction this session — persistence
  required, ownership and semantics settled; the concrete storage
  design remains a Phase 2 precondition, not an ADR-035-Acceptance
  precondition, per §18.A item 2's own text).

**Acceptance of this ADR authorizes design approval only.**
Implementation may begin solely through the phased roadmap (§17), one
phase at a time, each phase gated by its own RPI Plan artifact and
review — Acceptance of this document is not itself authorization to
implement every phase at once. Every phase remains subject to this
project's normal RPI governance (`.claude/agents/TEAM.md` §9)
regardless of this ADR's own status.
