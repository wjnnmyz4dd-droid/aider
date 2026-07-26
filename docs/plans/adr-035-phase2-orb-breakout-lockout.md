# Plan: ADR-035 Phase 2 — ORB Breakout Qualification and Persistent Per-Range Lockout

Status: **Blocked — Evidence Contract Insufficient** (Research complete;
Phase 2 cannot be planned to an implementation-ready state until a
companion Evidence Engine amendment is proposed and Accepted — see §5,
§8, §25, §31). **Update (2026-07-26):** the required amendment has now
been specified and proposed — `docs/adr/ADR-024-evidence-engine.md`
Amendment 4 (Proposed, not yet Accepted) and a corresponding note in
`docs/adr/ADR-035-orb-strategy.md` §17 Phase 2. This Plan remains
**Blocked** until Amendment 4 is independently reviewed and Accepted
(CLAUDE.md §1.10) — proposing an amendment is not the same as accepting
one, and no Phase 2 implementation is authorized by this update.

Owner: Software Architect (RPI Research/Plan phases, per ADR-035 owner
precedent).

Touched components (this document only): none in production code.
`docs/plans/` only. No production code, test, ADR, or config file is
modified by this Plan. `titan_protocol/strategy_engine/*` remains exactly
as accepted in Phase 1 (commit `27f231f`).

---

## 1. Research

### 1.1 Governance gate (verified directly, this session)

- Branch: `claude/phantom-ea-visibility-cjjf3a`. HEAD: `27f231f7aa485ff7809d73f233743d673e0e2351`. Working tree: clean (before this Plan file was added).
- `docs/adr/ADR-035-orb-strategy.md`: **Accepted** (2026-07-25, §§0-16/§17 only).
- `docs/adr/ADR-036-orb-strategy-consolidation.md`: **Accepted** (product-direction only; retirement still gated on all 6 ADR-035 phases being implemented, tested, and independently accepted — unchanged by this Plan).
- ADR-035 Phase 0 (Evidence Engine amendment, `OpeningRangeState`/`opening_ranges`): implemented, `titan_protocol/evidence_engine/opening_range.py` exists and is wired into `EvidenceSnapshot`.
- ADR-035 Phase 1 (`OrbBreakoutStrategy` foundation): implemented (commit `27f231f`) and independently accepted (prior conversation turn's 26-section conformance review, disposition **PHASE 1 ACCEPTED**). `git log 27f231f..HEAD` is empty — no Phase 2 code exists yet anywhere in the repository. `StrategyId.OPENING_RANGE_BREAKOUT` exists; `OrbBreakoutStrategy` is stateless and cannot return `QUALIFIED`; it is absent from `build_default_registry()`; all 5 legacy strategies are unchanged.
- **No part of Phase 2 is already implemented.** No STOP required on this ground.

### 1.2 ADR-035's exact Phase 2 contract (read in full, §§0-19)

ADR-035 §17 assigns Phase 2 exactly: "§4's objective rules (close beyond
range, ATR-relative distance, corrected body/wick ratio, momentum,
confirmation-candle count) — the first phase at which `qualify()` can
produce `QUALIFIED`" **and** the §6 session-lockout with its Phase-2-gated
persistence requirement (§18.A item 2). FVG confirmation (§5) is
explicitly Phase 3. Market Intelligence/eligibility integration
(session-anchor matching, news/liquidity/holiday gates, the
`orb_approved_pairs` hard gate) is explicitly Phase 4. Full config wiring
(§13's fields through `StrategyEngineConfig`/`config_loader.py`) is
explicitly Phase 5. Cross-phase integration/regression validation is
Phase 6. See §7 (Phase Boundary Matrix) below for the complete mapping.

### 1.3 Current ORB foundation, re-verified directly against the working tree

`titan_protocol/strategy_engine/strategies/orb_breakout.py`: `qualify()`
gates on generic eligibility (`check_eligibility()`), then
`evidence.opening_ranges` (empty → `NOT_QUALIFIED`; >1 entries →
`NOT_QUALIFIED`, "cannot disambiguate before Phase 4"; not
formed/not valid → `NOT_QUALIFIED`), then unconditionally returns
`NOT_QUALIFIED` ("No breakout qualification logic exists yet -- Phase
2"). No helper functions beyond a local `_not_qualified()`. No instance
state (`vars(strategy) == {}`). `StrategyEngineConfig` has no
`__post_init__` anywhere in the file (confirmed by reading
`titan_protocol/strategy_engine/config.py` in full) — no config
validation mechanism exists in this package today. `StrategyEngine`
(`engine.py`) holds one shared `StrategyRegistry` per instance and
iterates `self.registry.all()` generically; its own docstring states
`evaluate()` "may be called concurrently from many threads against one
shared instance" — an architectural contract, not merely today's
sequential Runtime caller behavior (`deployment_windows/start.py`'s plain
`for pair in profile.allowed_pairs:` loop).

### 1.4 Opening-range evidence, traced field-by-field

`OpeningRangeState` (`titan_protocol/evidence_engine/models.py:337-354`):
`session` (descriptive only), `range_start`/`range_end` (datetimes,
identity key per ADR-035 §3), `range_start_index`/`range_end_index`
(bar-sequence positions, same index space as `FairValueGap.start_index`/
`end_index`), `range_high`/`range_low`/`range_midpoint` (floats),
`is_formed`/`is_valid` (bools). All confirmed present and matching
ADR-035 §3 exactly.

### 1.5 Evidence sufficiency assessment — **the blocking finding**

**Critical question (per this task's own §4): does Strategy Engine
currently receive enough post-range price information through
`EvidenceSnapshot` to determine that price actually broke above
`range_high` or below `range_low`? No.**

Traced every field on `EvidenceSnapshot`
(`titan_protocol/evidence_engine/models.py:357-374`) and its nested
types:

- `report` (`EvidenceReport`): `symbol`, `generated_at`, `score`,
  `strengths`/`weaknesses`, `confidence_explanation` — no price.
- `structure` (`MarketStructureResult`): `swings`, `events`, `trend`,
  `support_levels`/`resistance_levels`. `StructureEvent.confirmed_price`
  *is* a real bar close — but only at the bar that confirmed a break of
  a **swing** level, an unrelated reference level to the opening range's
  `range_high`/`range_low`, and only exists when a structural break
  happened to occur; it cannot substitute for "the most recent closed
  bar's close vs. the range boundary."
- `liquidity` (`LiquidityResult`): pools/sweeps carry a `sweep_price`
  (a wick extreme) tied to a specific liquidity-pool event, not a
  general "most recent bar close."
- `candlesticks` (`Tuple[CandlestickMatch, ...]`): `pattern`, `index`,
  `quality`, `context`, `confidence` — **no OHLC values stored on the
  match itself.** Even if a match's `index` is the most recent bar, no
  price can be recovered from it.
- `volatility` (`VolatilityState`): `atr`, `is_expansion`,
  `is_compression`, `volatility_score` — no price.
- `session` (`SessionState`): `session`, `quality_score` — no price.
- `support_resistance` (`SupportResistanceContext`): previous
  day/week/month high/low, `session_high`/`session_low`, psychological
  levels, confluence zones, `break_quality_score`,
  `false_break_probability` — **no `current_price` field.** Read
  `titan_protocol/evidence_engine/support_resistance.py` in full:
  `build_support_resistance_context()` computes
  `current_price = bars[-1].close` at line 196 — proving the last
  closed bar's close is available *inside* Evidence Engine's own
  computation — but this is a local variable used only to sort
  confluence zones and center psychological levels; it is **never
  attached to any field Evidence Engine actually returns.**
- `fair_value_gaps` (`Tuple[FairValueGap, ...]`): `gap_high`/`gap_low`,
  `start_index`/`end_index` — a gap's bounds, not a bar's close, and
  Phase 3 scope regardless.
- `opening_ranges` (`Tuple[OpeningRangeState, ...]`): §1.4 above — the
  range's own bounds, never the bars that came after it.

Also read `titan_protocol/evidence_engine/engine.py` in full:
`EvidenceEngine._analyze(bars, now)` computes every one of the above from
`bars`, then both `evaluate()` and `evaluate_snapshot()` **discard `bars`
after the analysis pass** — the returned `EvidenceSnapshot` retains no
`Sequence[Bar]`, no single `Bar`, and no accessor from a bar-sequence
index (e.g. `range_end_index`, or a would-be "breakout bar index") back
to that bar's OHLC.

**Consequence:** ADR-035 §4's first and most fundamental breakout
condition — "the most recent **closed** bar's close must be beyond
`range_high` (bullish candidate) or below `range_low` (bearish
candidate)" — together with the body/wick-ratio check ("the breakout
bar's body ... must be at least `orb_min_body_to_range_ratio *
(bar.high - bar.low)`") and the confirmation-candle-count check
(`orb_min_confirmation_candles`, which needs the closes of several
trailing bars when configured above the default of 1) **cannot be
computed by `OrbBreakoutStrategy.qualify()` from `EvidenceSnapshot` as
currently defined.** No existing field, alone or in combination,
substitutes for a bar's own OHLC.

This is not an assumption error correctable inside Strategy Engine: per
this task's own instruction and ADR-024's Hard Rule (Evidence Engine is
the sole interpreter of market data), Strategy Engine must not read raw
bars or import `market_data_ingestion` to work around this — doing so
would violate `test_architecture.py`'s `ALLOWED_UPSTREAM_PREFIXES`
boundary (currently `titan_protocol.evidence_engine`,
`titan_protocol.market_intelligence` only) and ADR-026's dependency
inversion principle (§16 of ADR-035 itself: "ORB depends on
`EvidenceSnapshot`/`MarketIntelligenceSnapshot` abstractions ... no
direct dependency on `market_data_ingestion`"). **This is a genuine
architectural prerequisite, not an implementation detail Phase 2 can
resolve on its own.**

### 1.6 Precedent review for the remaining (non-blocked) design questions

Lockout/persistence is **not** blocked by §1.5 — it is a separable
concern (ADR-035 §18.A item 2 already resolves ownership, semantics, and
storage convention; only the concrete file/schema needs specifying, and
none of it depends on the breakout rule's evidence gap). Traced
precedent:

- `titan_protocol/compliance_state_store/store.py` (read in full): JSON
  file, `schema_version` field checked on load (`CorruptStateError` on
  mismatch, no migration attempted), atomic write via
  `tempfile.mkstemp()` → `fsync` → `os.replace()`, `.bak` rotation
  before every overwrite, fail-closed (`CorruptStateError`) if both
  primary and backup are unreadable — never a silent reset. A **sibling
  top-level package**, not nested inside `compliance_engine/`.
- `titan_protocol/risk_engine/reservation.py` and
  `titan_protocol/runtime/in_flight_commands.py`: both use a
  process-local `threading.Lock()` (`import threading`, `self._lock =
  threading.Lock()`) guarding their in-memory read-modify-write —
  confirming this codebase's one precedented concurrency-safety
  mechanism is a thread lock, never a cross-process mechanism. No
  evidence anywhere in the repository of more than one OS process ever
  touching the same persisted state file concurrently (single Bridge +
  single Runtime process model, ADR-031/034, unchanged) — cross-process
  concurrency is out of scope for Phase 2's design, consistent with
  actual deployment topology, not merely assumed.

### 1.7 Repository-wide `StrategyId`/config check

`StrategyEngineConfig` (`config.py`, read in full): no `__post_init__`
exists in the file today — adding one for Phase 2's
`orb_max_qualifications_per_range` (and future §13 fields) would be this
package's first config-validation code, a legitimate but real precedent
question (§19 below), not silently assumed away.
`DEFAULT_APPROVED_PAIRS_BY_STRATEGY` has no `OPENING_RANGE_BREAKOUT`
entry — `approved_pairs_for()` falls back to `()`, so ORB remains
`NOT_ELIGIBLE` for every pair under the shipped default config,
regardless of anything Phase 2 adds (consistent with ADR-035 §18.B item
4: approved pairs are explicitly Phase 5 scope, empty-by-default is
correct through Phase 2-4).

---

## 2. Governance Preconditions

- ADR-035: Accepted — verified (§1.1).
- ADR-036: Accepted, retirement still gated on all 6 phases — verified, unaffected by this Plan.
- Phase 0: Implemented — verified.
- Phase 1: Implemented and independently accepted — verified.
- CLAUDE.md §1.10: satisfied for Phase 2 *research/planning* (this document). Phase 2 *implementation* additionally requires the evidence-contract gap in §1.5 to be closed by its own Accepted amendment before it may begin (this is what "Blocked" means here — see §25).

---

## 3. Phase Objective

Give ORB its first real breakout-qualification behavior (§4's objective
rules) and the persistent, restart-safe, concurrency-safe per-range
qualification lockout ADR-035 §18.A item 2 requires — without pulling
FVG confirmation (Phase 3), Market Intelligence/eligibility gating
(Phase 4), or configuration wiring (Phase 5) forward, and without
weakening capital preservation by ever allowing ORB to qualify on
ambiguous, missing, or unreadable evidence.

**This objective cannot currently be met**, per §1.5: the breakout rule
itself has no evidence contract to implement against. This Plan
therefore specifies what *can* be designed now (lockout/persistence, §9-
§18 below) and what must be resolved first (§25) before the remainder can
be planned to implementation-ready detail.

---

## 4. Repository Evidence Summary

See §1 in full. Every claim above was checked directly against the
working tree this session (`models.py`, `engine.py`,
`support_resistance.py`, `config.py`, `selection.py`, `eligibility.py`,
`orb_breakout.py`, `test_orb_breakout_foundation.py`,
`compliance_state_store/store.py`, `risk_engine/reservation.py`,
`runtime/in_flight_commands.py`, `market_intelligence/models.py`), not
assumed from ADR-035's own prose or prior conversation summaries.

---

## 5. Current Architecture Assessment

Strategy Engine's existing architecture (registry, eligibility,
selection cascade, `Strategy` interface) requires no change to
accommodate a real ORB qualification rule *once the breakout rule has
evidence to evaluate* — §0 and §12 of ADR-035 are corroborated by direct
code reading, not merely trusted. The one real gap is entirely on the
Evidence Engine side (§1.5) — Strategy Engine's own architecture is
sound and ready for Phase 2 the moment that gap is closed.

---

## 6. (merged into §1.2)

## 7. Phase Boundary Matrix

| Concern | Owning phase | Status |
|---|---|---|
| `OpeningRangeState` / `opening_ranges` (Evidence Engine) | Phase 0 | Implemented |
| Range-formed/valid gating only, stateless, never `QUALIFIED` | Phase 1 | Implemented, accepted |
| Close-beyond-range, ATR-distance, body/wick ratio, momentum, confirmation-candle count | **Phase 2** | **Blocked — evidence contract insufficient (§1.5)** |
| Session lockout (`orb_max_qualifications_per_range`), persisted, restart-safe | **Phase 2** | Designable now (§9-§18); implementation still gated by the same STOP since it lives in the same `qualify()` call as the breakout rule |
| FVG confirmation (§5), index-based temporal comparison | Phase 3 | Out of scope — not designed here |
| Session-anchor matching, news/liquidity/holiday gates, `orb_approved_pairs` hard gate | Phase 4 | Out of scope — not designed here |
| Full `StrategyEngineConfig`/`config_loader.py` wiring, cross-field validation | Phase 5 | Out of scope — not designed here |
| Full-suite integration/regression validation | Phase 6 | Out of scope — not designed here |

Direction (upside → `BUY`, downside → `SELL`) and `QualificationResult`
scoring shape are Phase 2 concerns per ADR-035 §17, but their concrete
design is likewise blocked: a truthful `TradeIntent`/score cannot be
produced without a resolved breakout rule to derive them from (§10-§11
below record what *would* apply once §1.5 is resolved, not a working
design).

---

## 8. Breakout Rule — Decision

**Not resolved. Blocked.** ADR-035 §4's rules are extracted faithfully in
§1.2/§1.5 above; every threshold it names (`orb_min_breakout_distance_atr_multiple`,
`orb_min_body_to_range_ratio`, `orb_min_confirmation_candles`, etc.) is
category C in this task's own taxonomy (a new Phase 2 config field
explicitly required by ADR-035) — never invented here — but **no
threshold can be wired to real evidence** until `EvidenceSnapshot`
exposes the missing bar-level facts (§1.5). No breakout rule is
specified as code or pseudocode in this Plan; doing so would be
speculative design against a contract that does not exist.

## 9. Evidence Mapping

| ADR-035 §4 condition | Required evidence | Currently on `EvidenceSnapshot`? |
|---|---|---|
| Range formed and valid | `opening_ranges[i].is_formed`/`is_valid` | Yes (Phase 0) |
| Close beyond range | Most recent closed bar's `close` | **No** |
| Minimum breakout distance (ATR-relative) | Same bar's `close`, plus `volatility.atr` | Bar close missing; ATR present |
| Body size / wick tolerance | Breakout bar's `open`, `close`, `high`, `low` | **No** |
| Momentum | `volatility.is_expansion` | Yes |
| Minimum confirmation candles | N trailing closed bars' `close` values | **No** |
| False-break filter | Same as "close beyond range" (by construction, §4) | **No** (depends on the same missing fact) |

## 10. Qualification Result Semantics

Not resolved — depends on §8. Once evidence exists, the shape is already
knowable from `QualificationResult` (`strategy_engine/models.py`):
`score` (0-100), `confidence` (0-1), `reason`/`strengths`/`weaknesses`
(str/tuple), `trade_intent` (defaults `NONE`, set only on `QUALIFIED`).
`SessionBreakoutStrategy`'s weighted-sum pattern (`clamp(0.4*a + 0.3*b +
0.3*c)`) is the established precedent ADR-035 §5 itself cites for the
eventual scoring formula. Not designed further here since it cannot be
truthfully populated without §8.

## 11. Direction / TradeIntent Semantics

Not resolved — depends on §8. ADR-035's own intended mapping (upside
breakout → `BUY`, downside → `SELL`) is unambiguous in principle and
matches `TradeIntent`'s existing two directional members exactly, but
"upside breakout" itself is the undefined quantity per §8. No sizing,
stop-loss, take-profit, order type, or execution artifact is introduced
by this mapping when it is eventually implemented (ADR-026 Hard Rule 1,
unchanged) — confirmed as a design constraint, not implemented.

## 12. Opening-Range Selection Behavior

This question **is** resolvable independently of §8, and independently
verified against ADR-035 §3/§13/§15: multiple ranges remain matched by
window (`range_start`/`range_end`), never by `session`, with startup
validation (Phase 5 scope) rejecting overlapping anchors so at most one
match is ever possible. Phase 1's blanket "`len(opening_ranges) > 1` →
`NOT_QUALIFIED`" behavior should **not** be retained as Phase 2's final
behavior once Phase 5's anchor-overlap validation exists, but **is**
still correct for Phase 2 itself: Phase 2 does not implement §13's
config or its cross-field overlap check (that is Phase 5), so Phase 2
has no way to *guarantee* two configured anchors don't collide, and must
therefore continue to fail closed on plural ranges — carrying Phase 1's
existing behavior forward unchanged is correct, not a regression to fix.
Zero ranges / one range / mixed valid-invalid / mixed formed-unformed:
all already correctly handled by Phase 1's existing gates, unchanged.

## 13. Lockout Semantics

Resolved by ADR-035 §18.A item 2, re-verified this session, carried
forward unchanged:

- **Identity:** `(pair, range_start)` — `range_start` is
  `OpeningRangeState.range_start`, already unique per configured anchor.
- **Consumption event:** `qualify()` returning `QUALIFIED`, and only
  that — never selection, reservation, command submission, or execution.
  This is the strictest available trigger (§18.A: "it can only cause ORB
  to under-trade... never to over-trade").
- **Non-consuming paths:** every `NOT_QUALIFIED`/`NOT_ELIGIBLE` result
  leaves the counter untouched.
- **A `QUALIFIED` result that later loses the selection cascade still
  consumes the allowance** — the counter is written the moment
  `qualify()` itself decides `QUALIFIED`, before `select_winning_strategy()`
  ever runs; this is a direct consequence of the trigger being
  `qualify()`'s own return, not a separate design choice.
- **Trade close, Risk rejection, Compliance rejection, and execution
  failure do not reset or decrement the counter** — none of those
  events happen inside `qualify()`, and the lockout is defined purely in
  terms of `qualify()`'s own output (§18.A: "at most N qualifications
  per opening range, full stop").
- **Reset/rollover:** a new `range_start` (the next trading day's opening
  range) is a new identity key — implicitly "fresh" with no explicit
  reset step needed, since the persisted store simply never has an entry
  for a `range_start` it hasn't seen before.

## 14. State Ownership

Strategy Engine, exclusively — re-verified this session:
zero references to `range_start` or any opening-range concept exist
anywhere under `risk_engine/`, `compliance_engine/`, or `runtime/`
(repository-wide grep, this session, confirms the same finding ADR-035
§18.A already recorded). No other engine has the vocabulary to host this
fact, and none should acquire it merely to do so (ADR-026 Hard Rule 5).

## 15. Persistence Architecture

Resolved in convention by ADR-035 §18.A item 2, confirmed against
`compliance_state_store`'s actual implementation (§1.6): a **new sibling
top-level package**, `titan_protocol/strategy_state_store/` — not nested
inside `titan_protocol/strategy_engine/`, and never a reuse of
`compliance_state_store` or `runtime/in_flight_store.py` (ADR-026 Hard
Rule 5 — no engine borrows another engine's persistence). This mirrors
`compliance_state_store`'s own precedent exactly: file-backed JSON,
`schema_version` field, atomic write (`tempfile.mkstemp()` → write →
`fsync` → `os.replace()`), `.bak` rotation before every overwrite,
fail-closed `CorruptStateError`-equivalent on an unreadable or
schema-mismatched file — never a silent reset. This part of the design
is genuinely ready; it is not blocked by §1.5, since the counter it
persists is independent of how the breakout rule itself is computed.

## 16. Persisted Data Model

Minimal model, derived from §13's identity and consumption semantics —
not `compliance_state_store`'s shape copied wholesale:

```
PersistedOrbQualificationState:
    schema_version: int
    entries: Dict[key, count]   # key = "pair|range_start_iso" (a single string, since JSON object keys must be strings; range_start serialized via datetime.isoformat(), matching this codebase's existing ISO-8601 convention in compliance_state_store)
```

- `strategy_id` does **not** belong in the key: this store is already
  scoped to `OpeningRangeState`'s own Strategy Engine package convention
  (§15 — a store per strategy that needs one), so a second strategy
  needing similar state would get its own store, not a shared one keyed
  by `strategy_id` (consistent with ADR-026 Hard Rule 5's per-engine, not
  per-strategy, ownership boundary already established at the *engine*
  level — extending it to a per-strategy boundary is the more
  conservative, more isolated choice and avoids one strategy's schema
  evolution affecting another's).
- `session` does **not** belong in the key (§3's own "Identification"
  correction: `session` is descriptive only).
- `range_end` does **not** need persisting: it is not part of the
  identity and is not needed to answer "has this range already
  qualified" — only `range_start` (the key) and the count (the value)
  answer that question.
- Pruning stale entries (ranges that will never recur, e.g. more than a
  few trading days old): not required for Phase 2 to be correct —
  `orb_max_qualifications_per_range` defaults to 1 and unbounded growth
  of a small per-(pair, range_start) counter file is a Phase 5-or-later
  operational concern (config-loader/operational-hygiene scope), not a
  correctness requirement Phase 2 must solve. Documented as an explicit
  Phase 2 non-requirement, not silently forgotten.

## 17. Concurrency Model

`StrategyEngine.evaluate()`'s own docstring is treated as architectural
fact (§1.3), not today's single-threaded Runtime loop. The race named in
this task's own prompt (`check allowance` + `consume allowance` as two
non-atomic steps under two concurrent callers) is real given that
contract. Resolution, consistent with this repository's one precedented
concurrency mechanism (§1.6): a **process-local `threading.Lock()`**
owned by the new store, wrapping "read count, compare to max, write
incremented count" as one critical section — never split across two
public methods a caller could interleave between. This provides thread
safety (the only kind this repository's own architecture requires or has
ever needed, per `ReservationLedger`/`InFlightCommandRegistry`
precedent) and crash safety (via §15's atomic file replace, independent
of the lock). Cross-process concurrency is explicitly out of scope,
consistent with the single-Bridge/single-Runtime-process deployment
topology this codebase has everywhere else (§1.6) — not claimed to be
solved, simply not a real scenario given actual deployment architecture.

## 18. qualify() Side-Effect / Ownership Decision

Every existing `Strategy.qualify()` implementation is pure (reads
`evidence`/`market_intelligence`/`config`, returns a `QualificationResult`,
touches nothing else). §13's "consume on `QUALIFIED`" rule necessarily
makes `OrbBreakoutStrategy.qualify()` the first strategy with an
observable side effect. Of this task's three options: **Option A**
(the strategy receives a lockout dependency and atomically
reserves/consumes inside `qualify()`) is the only one that can guarantee
"consume iff `QUALIFIED`" as a single atomic fact, without introducing
strategy-specific branching into `StrategyEngine.evaluate()` (which
today calls every registered strategy's `qualify()` identically, with no
per-strategy special-casing anywhere in `engine.py` — confirmed by
reading it in full, §1.3). Requires `OrbBreakoutStrategy.__init__()` to
accept the new store as a constructor dependency — its first,
narrowly-scoped instance state (ADR-035 §6 already anticipated and
named this: "an explicit, narrow, documented exception" to Strategy
Engine's otherwise-stateless convention, analogous to
`market_data_ingestion`'s own one documented stateful exception). This
does not require changing the `Strategy` ABC's `qualify()` signature —
the dependency lives on the instance, not the call. **This is the
recommended option**, but its concrete implementation still cannot begin
until §1.5's evidence gap is resolved, since the store's one write
happens exactly where the (currently undesignable) breakout rule would
decide `QUALIFIED`.

## 19. Failure-Semantics Matrix

| Condition | Behavior |
|---|---|
| State file absent (first-ever run for any `(pair, range_start)`) | Genuinely new/empty store — bootstrap an empty `entries: {}`, never an error (mirrors `compliance_state_store`'s own "missing file on first-ever run bootstraps fresh state" — there is nothing to lose) |
| State file corrupt (unparseable JSON) | Fail closed: raise (do not qualify), attempt `.bak` recovery first, exactly as `compliance_state_store._load_existing()` does |
| Unsupported schema version | Fail closed, same as `compliance_state_store` (`CorruptStateError`-equivalent, no migration attempted) |
| State read failure (I/O error) | Fail closed — never treated as "not yet consumed" (ADR-035 §18.A: "if persisted state cannot be read, is corrupt, or is an unsupported schema version, ORB must not qualify the affected `(pair, range_start)`") |
| State write failure after a qualification is produced | The qualification that already occurred stands (it already happened); the write failure itself must be raised/logged, never silently swallowed (§18.A, verbatim) |
| Lock acquisition failure | Not applicable to a process-local `threading.Lock()` (cannot fail to acquire, only block) — no separate failure path needed |
| Count already at maximum | `NOT_QUALIFIED`, `"already qualified for this opening range"` (§14 of ADR-035, verbatim) |
| Invalid negative count | Cannot occur by construction (the store only ever increments from a validated non-negative starting point) — not a runtime check, a structural guarantee of the store's own write path |
| Malformed key | Fail closed at deserialization (same path as "corrupt") — a key that doesn't parse as `pair|iso-datetime` is corruption, not a distinct case |
| `range_start` serialization failure | Cannot occur: `range_start` is always a real `datetime` from `OpeningRangeState`, and `datetime.isoformat()` cannot fail on a valid `datetime` — not a real failure mode, not designed further |

## 20. Configuration Plan

`orb_max_qualifications_per_range` (`int`, default 1, safe range ≥ 1,
per ADR-035 §13) is the only Phase 2 config field with resolvable
semantics — but wiring it into `StrategyEngineConfig` in a way that's
actually exercised requires the surrounding `qualify()` logic (§8) to
exist first, since the field has no effect without a `QUALIFIED` path to
gate. Whether adding `StrategyEngineConfig.__post_init__` validation now
is itself a new precedent for this package (§1.7) is flagged as an open
question for whichever Plan revision follows §1.5's resolution — not
decided here, since it's entangled with how many of §13's other fields
Phase 2 vs. Phase 5 actually owns. `config_loader.py`/example-config
wiring remains Phase 5, unchanged from ADR-035 §17.

## 21. Approved-Pair Behavior

Unchanged from Phase 1: `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` gets no
`OPENING_RANGE_BREAKOUT` entry in Phase 2 (ADR-035 §18.B item 4 — Phase 5
scope). Phase 2's own tests must construct an explicit
`StrategyEngineConfig` override to exercise the eligible path, exactly as
`test_orb_breakout_foundation.py`'s `_ORB_APPROVED_CONFIG` already does
for Phase 1 — the same pattern carries forward.

## 22. Registration Plan

Unchanged: `OrbBreakoutStrategy` remains outside
`build_default_registry()` through Phase 2 (ADR-035 §17 assigns
production registration to no phase before Phase 6's full-suite
validation at the earliest, and even that is integration testing, not
necessarily production wiring). No registry-count test is weakened by
this Plan.

## 23. Architecture-Test Impact

`test_architecture.py`'s `ALLOWED_UPSTREAM_PREFIXES` (currently
`titan_protocol.evidence_engine`, `titan_protocol.market_intelligence`)
will need a third entry once the new `titan_protocol.strategy_state_store`
sibling package exists (§15), since `orb_breakout.py` would then import
from it. This is a narrow, correctly-scoped addition reflecting a real,
intended dependency direction (Strategy Engine depending on its own
persistence sibling, same pattern Evidence Engine already uses for
`market_intelligence`) — not a loosening of the boundary. Not implemented
in this Plan; recorded for whichever Plan revision follows §1.5's
resolution.

## 24. Structural-Boundary Impact

Both `test_structural_boundary.py` files (`compliance_state_store`,
`news_ingestion`) list `"titan_protocol/strategy_engine/"` in their
`_FROZEN_PREFIXES`. A future Phase 2 implementation touching
`orb_breakout.py`/`strategies/__init__.py` again, plus creating the new
`titan_protocol/strategy_state_store/` package (not itself a frozen
prefix in either file today), would need the same
`_LATER_AUTHORIZED_EXCEPTIONS` entries these files already carry for
Phase 0/Phase 1 — narrowly scoped to the exact files touched, following
the established, precedented pattern (independently verified as
legitimate in the prior Phase 1 conformance review). Not implemented
here.

## 25. Fail-Closed Analysis

Every fail-closed path specified in §19 traces directly to ADR-035
§18.A's own governing principle, verbatim. No path in this Plan weakens
capital preservation to make ORB trade more often — consistent with this
task's own governing principle. **The most important fail-closed
decision this Plan makes is procedural, not code-level: refusing to
invent a breakout rule against a contract `EvidenceSnapshot` does not
support (§1.5) is itself the correct fail-closed behavior for the
*planning* phase** — a Plan that fabricated thresholds against
non-existent evidence fields would be exactly the kind of "best-effort
guess" ADR-026 Hard Rules 3-4 forbid at the code level, extended here to
forbid it at the design level too.

## 26. Risk Assessment

| Risk | Class | Mitigation / verification gate |
|---|---|---|
| False breakout (breakout rule too permissive) | HIGH | Cannot be assessed until §8 is resolved — deferred |
| Duplicate same-range qualification (no lockout) | CRITICAL | §13-§18 design (ready); blocked on §8 for actual implementation |
| Restart duplication | CRITICAL | §15/§19 persistence design (ready) |
| Concurrent lost update | HIGH | §17 process-local lock design (ready) |
| Corrupt state treated as empty | CRITICAL | §19 fail-closed matrix (ready) |
| Write succeeds but qualification "fails" / qualification returned before state persisted | MEDIUM | §19: qualification stands, write failure surfaced, never swallowed (ready) |
| Stale state blocks a legitimate future range | LOW | §16: keyed by `range_start`, a new range is a new, unblocked key (ready) |
| Timezone/datetime identity mismatch | LOW | `range_start` is already a UTC-only `datetime` per ADR-035 §3 (ready) |
| Multiple-range ambiguity | LOW | §12: Phase 1's existing fail-closed behavior carries forward correctly (ready) |
| Accidental ORB registration | LOW | §22: unchanged, no registry-count test weakened (ready) |
| Legacy-strategy regression | LOW | No legacy file touched by this Plan (nothing implemented yet) |
| Architecture dependency inversion | MEDIUM | §23: one narrowly-scoped, correctly-directed `ALLOWED_UPSTREAM_PREFIXES` addition anticipated, not yet made |
| **Evidence-contract insufficiency (breakout rule has no data to evaluate)** | **CRITICAL — the actual blocker** | §1.5/§8: requires a new Evidence Engine amendment before Phase 2 implementation can begin |

## 27. Out-of-Scope Confirmation

FVG confirmation (Phase 3), Market Intelligence/eligibility gating
(Phase 4), config-loader wiring (Phase 5), and full-suite validation
(Phase 6) are not designed, referenced as implementable, or pulled
forward anywhere in this Plan (§7). ADR-036 strategy consolidation is
untouched. No legacy strategy is modified, retired, disabled, or
renamed. No production code is modified by this Plan (docs-only diff).

## 28. Acceptance Criteria

This Plan cannot yet be marked implementation-ready. When it can be (see
§31), the following must all hold:

1. A companion Evidence Engine amendment closing §1.5's gap is itself Accepted (CLAUDE.md §1.10).
2. The breakout rule (§8) is specified against that amendment's real fields, with every threshold traceable to ADR-035 §13's config table (never invented).
3. Lockout identity/consumption/persistence/concurrency (§13-§18, already resolved here) are re-confirmed unchanged by whatever the evidence amendment adds.
4. `OrbBreakoutStrategy` remains unregistered in `build_default_registry()`.
5. No legacy strategy is modified.
6. A full test matrix (breakout rule × lockout × persistence × concurrency × regression × architecture) is specified before implementation begins.

## 29. Rollback Strategy

Not applicable — no implementation exists yet to roll back. This Plan
document itself can be reverted (`git revert`) with zero production
impact, since it modifies no code.

## 30. Engineering Checklist

- [x] Repository evidence gathered directly (not assumed from ADR-035's prose or prior summaries).
- [x] Phase 1 baseline re-verified as implemented and accepted.
- [x] Evidence sufficiency independently checked field-by-field.
- [x] Lockout/persistence precedent traced to real, existing code.
- [x] Concurrency precedent traced to real, existing code.
- [ ] Breakout rule specified against real evidence — **blocked**.
- [ ] Test matrix written — blocked (depends on breakout rule).
- [ ] Plan marked implementation-ready — blocked.

## 31. Open Questions / Blockers

**The blocker:** `EvidenceSnapshot` does not expose the most recent
closed bar's OHLC (or any addressable bar-level price data) needed to
evaluate ADR-035 §4's breakout rule. **Smallest next action:** propose a
new, narrowly-scoped Evidence Engine amendment (next available slot —
confirm against `ADR-024-evidence-engine.md`'s actual current amendment
count, since ADR-035 §3 already found and flagged one clerical numbering
error in this exact area) exposing the minimum fact Strategy Engine
needs — for example, a small, purpose-built type (not a raw
`Sequence[Bar]` handed to Strategy Engine, which would violate ADR-024's
"sole interpreter" authority) such as a bounded tuple of the last *K*
closed bars' `(index, open, high, low, close)`, where *K* is driven by
the largest configured `orb_min_confirmation_candles` this or any future
strategy needs — attached to `EvidenceSnapshot` the same additive way
`fair_value_gaps` and `opening_ranges` were. That amendment needs its own
Research → Plan → Implement cycle and its own Accepted status
(CLAUDE.md §1.10) before this Phase 2 Plan can be completed. This Plan
does not propose that amendment's design in detail — doing so is a
distinct RPI cycle's Research phase, not this one's.

Secondary, non-blocking open question (§20): whether
`StrategyEngineConfig` should gain its first `__post_init__` validation
method now or as part of whichever later phase the resolved Phase 2 ends
up needing it — left open pending §8's resolution, since it changes
which fields Phase 2 vs. Phase 5 actually validates.

## 32. Final Readiness Assessment

**Not ready.** Roughly half of Phase 2 (the persistent lockout: identity,
consumption semantics, ownership, storage architecture, persisted model,
concurrency model, failure semantics — §13-§19) is fully researched and
would need only the connective breakout-rule STOP resolved to become
implementable. The other half (the breakout rule itself, and everything
that depends on it — qualification result semantics, direction, exact
`QualificationResult` shape) cannot be planned further without new
Evidence Engine evidence. Presenting either half as "ready to implement"
while the other is blocked would risk a partial, unreviewable
implementation — not permitted under this task's own instructions.

## 33. Validation Checklist for Future Implementation

To be completed once §31's blocker is resolved and this Plan (or its
successor revision) reaches Final Readiness:

- [ ] `py_compile` on all new/modified files.
- [ ] New Phase 2 test suite (breakout rule × lockout × persistence × concurrency, per this task's own Test Plan section) green.
- [ ] Full `tests/titan_protocol` suite green (regression: 5 legacy strategies + Phase 0/1 unchanged).
- [ ] `test_architecture.py` green, including any narrowly-scoped `ALLOWED_UPSTREAM_PREFIXES` addition for the new store package.
- [ ] Both `test_structural_boundary.py` files' exception lists extended narrowly, if needed, following the established precedent.
- [ ] `git status --porcelain` clean; single, reviewable commit.
- [ ] `OrbBreakoutStrategy` still absent from `build_default_registry()`.
- [ ] Independent implementation-conformance review completed before any further phase begins.

---

## Research/Plan disposition

**PHASE 2 PLAN BLOCKED — EVIDENCE CONTRACT INSUFFICIENT.**

Smallest next governance/research action: initiate a new RPI Research
cycle for a targeted Evidence Engine amendment exposing the minimal
bar-level breakout evidence identified in §1.5/§31, get it Accepted, then
resume this Phase 2 Plan (or a revision of it) to complete §8-§11, §20,
and the test matrix against real evidence.
