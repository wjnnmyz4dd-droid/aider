# Plan: ADR-035 Phase 2 — ORB Breakout Qualification and Persistent Per-Range Lockout

Status: **FINALIZED — READY FOR INDEPENDENT IMPLEMENTATION-READINESS
REVIEW (§27).** Step 2A is implemented and independently accepted
(commit `dcf9b580ef6f46fd9bb8422cecb22ba794df892a`). Step 2B's own
write-failure defect (found in an earlier implementation-readiness
review of this Plan) was corrected, that correction was independently
re-reviewed (APPROVED WITH REQUIRED MINOR REVISIONS) and the three
required revisions applied, and the subsequent RPI Research phase
independently re-derived every repository fact this Plan depends on
(disposition: STEP 2B RESEARCH COMPLETE — READY FOR PLAN FINALIZATION).
This document is that finalization pass. This Plan originally specified
two separately gated RPI Implement increments (§4) rather than treating
Phase 2 as unblocked for a single combined implementation; that
structure is unchanged throughout.

Owner: Software Architect (RPI Plan phase, per ADR-035/ADR-024 owner
precedent).

**Correction — 2026-07-26 (Plan-level only, no code touched):** the
independent Step 2B implementation-readiness review of this Plan found
§10's original write-failure text self-contradictory — it required
`OrbBreakoutStrategy.qualify()` to "still return `QUALIFIED` even if the
persist call raises" while also requiring "the raised exception must
propagate to logging... not swallowed inside the store," which cannot
both hold given `StrategyEngine.evaluate()`'s `qualifications = tuple(strategy.qualify(...)
for strategy in self.registry.all())` has zero exception handling around
each `qualify()` call (independently confirmed by direct code read) — an
exception escaping `try_consume()` would abort that entire evaluation
cycle for all 5 legacy strategies too, not just ORB. §10 below is
corrected: the store now catches and logs the write failure **inside**
`try_consume()` and never raises past its own boundary, which this
correction shows still satisfies ADR-024/ADR-035 §18.A's actual
requirement ("must not be silently swallowed") through visible logging
rather than through letting an exception propagate — §18.A never
required the latter. This correction requires its own independent review
before Step 2B implementation may be authorized to begin (§27).

**Follow-up correction — 2026-07-26 (Plan-level only, no code touched):**
the independent re-review of the above correction found it structurally
sound but incomplete on three narrow points that would otherwise have
been left for an implementer to invent: (1) whether `try_consume()`'s
persist step writes the whole `entries` dict or a per-key delta —
resolved in §10 as whole-dict, with the resulting self-healing property
made explicit; (2) where the store's exception-safe logging call gets
its logger from — resolved in §10 as a plain module-level
`_LOGGER = logging.getLogger(__name__)` and `_safe_log_persist_failure()`
helper in `store.py`, not a constructor dependency; (3) the ADR-035
§18.A-accepted restart-duplication residual risk and the whole-dict
self-healing property were both real but untested requirements — two
tests are now added to §21. None of these three points changed the
underlying design decided by the first correction; they close gaps in
its specification.

**Plan finalization — 2026-07-26 (Plan-level only, no code touched):**
the independent Step 2B RPI Research phase (commit `085e7e5` as its
governance baseline) re-derived every repository fact this Plan depends
on directly from source and confirmed all three required corrections
present. It surfaced four items incorporated in this finalization pass:
(1) §18's structural-boundary scope was overstated — corrected below;
(2) §10 now explicitly documents *why* `OrbQualificationStore`
deliberately departs from `compliance_state_store`'s own write-failure
handling, rather than leaving that divergence unexplained; (3) §13 now
states explicitly that ADR-035 §13's cross-field validation clause does
not apply to any of Step 2B's 4 fields, so no implementer redundantly
re-implements it; (4) every stale HEAD/commit reference in this document
is updated to the actual state at finalization time. No breakout
algorithm, lockout semantic, concurrency guarantee, persistence design,
or registration prohibition changed — this pass closes documentation
gaps the Research phase found, it does not revise any decision already
reviewed and approved.

Touched components (this document only): none in production code.
`docs/plans/` only. No production code, test, ADR, or config file is
modified by this Plan revision. `titan_protocol/strategy_engine/*`
remains untouched by any commit to date; `titan_protocol/evidence_engine/*`
reflects Step 2A's own implementation (commit `dcf9b58`) — both are
exactly as they are at current HEAD `085e7e5608dd7509c6992ab56eef9c77cbdeb232`
(independently re-verified by the RPI Research phase; `dcf9b58` remains
the last commit to touch either package, `085e7e5` is simply HEAD's own
value at this finalization).

---

## 1. Research (carried forward, re-verified this revision)

### 1.1 Governance gate (re-verified against current HEAD)

- Branch: `claude/phantom-ea-visibility-cjjf3a`. HEAD at Plan finalization: `085e7e5608dd7509c6992ab56eef9c77cbdeb232`, matches `origin`, working tree clean (independently re-verified by the RPI Research phase preceding this finalization pass — not merely carried forward from the original Plan reconciliation's `d569de5` snapshot, which predates Step 2A's own implementation and both write-failure corrections).
- ADR-035: **Accepted** (2026-07-25, §§0-16/§17 only) — unaffected by this Plan.
- ADR-036: **Accepted** (product-direction only) — retirement still gated on all 6 ADR-035 phases being implemented, tested, and independently accepted, unaffected by this Plan.
- ADR-024 Amendment 4 (`OpeningRangeState.post_range_bars`): **Accepted** (2026-07-26, commit `d569de5`) — re-read in full this revision; the exact-equality first-candidate rule, exact subsequent-interval continuity, self-derived completion, bounded retention, sequence-relative index/`(symbol, timestamp)` identity, and multiple-range independence are all confirmed present and unambiguous in the Accepted text.
- ADR-035 Phase 0 (`OpeningRangeState`/`opening_ranges`): implemented, unchanged.
- ADR-035 Phase 1 (`OrbBreakoutStrategy` foundation): implemented (commit `27f231f`) and independently accepted. Re-verified this revision: `qualify()` still gates on eligibility → empty ranges → `len(opening_ranges) > 1` → `is_formed` → `is_valid`, then unconditionally `NOT_QUALIFIED`. Stateless (`vars(strategy) == {}`). Absent from `build_default_registry()` (still registers exactly the 5 legacy strategies, body unchanged — confirmed via `git log -1 -- titan_protocol/strategy_engine/` showing `27f231f` as the last touch). `git log d569de5..HEAD` is empty relative to this revision's own starting point — no Phase 2 code exists anywhere.
- **Distinction preserved throughout this Plan (per this task's own instruction): "Amendment 4 Accepted" is an architecture/design decision (A), not proof that Amendment 4's production code exists (B).** Both increments below (§4) required their own Implement-phase work; Step 2A's is now complete and independently accepted (commit `dcf9b58`), Step 2B's has not begun and remains gated on this finalized Plan's own independent implementation-readiness review.

### 1.2 ADR-035's exact Phase 2 contract (unchanged from prior revision, re-confirmed)

ADR-035 §17 assigns Phase 2 exactly: §4's objective breakout rules and
the §6 session-lockout with its Phase-2-gated persistence requirement
(§18.A item 2). FVG confirmation (§5) is Phase 3. MI/eligibility
integration is Phase 4. Config-loader wiring is Phase 5. Full-suite
validation is Phase 6. See §7 (Phase Boundary Matrix).

### 1.3-1.7 (carried forward unchanged from the prior revision of this
Plan — re-verified this revision, no drift found)

Current ORB foundation, opening-range field trace, precedent review for
lockout/persistence (`compliance_state_store`, `risk_engine/reservation.py`,
`runtime/in_flight_commands.py`), and the `StrategyEngineConfig`/approved-pairs
check are all unchanged from the version reviewed and accepted in the
prior Plan revision. Not re-stated verbatim here to avoid duplication;
every conclusion from that section remains valid and is relied on below.

### 1.8 Amendment 4's Accepted contract, re-read in full this revision

`docs/adr/ADR-024-evidence-engine.md`'s Amendment 4 (Accepted) adds:

```
OpeningRangeState.post_range_bars: Tuple[OpeningRangeBarObservation, ...] = ()

OpeningRangeBarObservation:
    index: int          # sequence-relative to the bars argument of one evaluate_snapshot() call
    timestamp: datetime  # bar-open time
    open: float
    high: float
    low: float
    close: float
```

Governing rules (verbatim from the Accepted text, relied on below
without restatement of their own proofs):

- First candidate: `bars[range_end_index].timestamp == range_end` exactly, or `post_range_bars == ()` for that range — no tolerance, no forward search.
- Subsequent candidates: `candidate.timestamp == previous.timestamp + expected_bar_interval_seconds` exactly.
- Completion: `candidate.timestamp + expected_bar_interval_seconds <= now`.
- Order per candidate: continuity check, then completion check; stop at the first failure of either; no skip-and-resume.
- Bounded by `EvidenceEngineConfig.opening_range_post_range_bar_window` (proposed default 5) — Evidence-Engine-owned, independent of any Strategy Engine confirmation-count field.
- `index` is sequence-relative per snapshot call; `timestamp` identity is scoped to `(symbol, timestamp)` within one evaluation call; neither is a durable/global identifier.
- Multiple configured anchors derive `post_range_bars` independently; a bar may be post-range evidence for one anchor and in-range formation evidence for another.
- Evidence Engine computes facts only — no breakout decision, direction, or threshold evaluation.

**Phase 2's qualify() logic below is designed entirely against this
contract.** No part of it requires anything from Phase 3 (FVG), Phase 4
(MI/eligibility gates), or Phase 5 (config-loader wiring).

---

## 2. Governance Preconditions

- ADR-035: Accepted.
- ADR-036: Accepted, retirement still gated on all 6 phases.
- ADR-024 Amendment 4: **Accepted** (this revision's own trigger).
- Phase 0/1: Implemented and independently accepted.
- CLAUDE.md §1.10: satisfied for Phase 2 code **once Amendment 4 is itself implemented** (§4 below, Step 2A) — Phase 2's own ORB breakout/lockout code (Step 2B) additionally requires Step 2A's implementation to be complete and independently accepted first, since it consumes `post_range_bars`, a field that does not exist in the running code until Step 2A ships.

---

## 3. Phase Objective

Give ORB its first real breakout-qualification behavior (ADR-035 §4) and
the persistent, restart-safe, concurrency-safe per-range qualification
lockout (§18.A item 2) — without pulling FVG confirmation (Phase 3),
MI/eligibility gating (Phase 4), or configuration wiring (Phase 5)
forward, and without ever allowing ORB to qualify on ambiguous, missing,
incomplete, or non-contiguous evidence.

**This objective is now fully specifiable** (§5-§18 below) because
Amendment 4's Accepted contract supplies every fact ADR-035 §4 needs.
It was **not implementable in one step**: Amendment 4's own code had to
land and be independently accepted first (§4, Step 2A) before Step 2B's
`qualify()` logic — which reads `post_range_bars`, a field that did not
exist until Step 2A shipped — could be written or tested against real
evidence. **That precondition is now satisfied** (Step 2A implemented
and independently accepted, commit `dcf9b58`); Step 2B's own
implementation may proceed once this finalized Plan itself passes its
independent implementation-readiness review.

---

## 4. Implementation Sequencing (resolves the evidence-blocker
reconciliation and the sequencing question together)

**Two separately gated RPI Implement increments, never one combined
commit:**

- **Step 2A — Implement ADR-024 Amendment 4.** Adds `OpeningRangeBarObservation`
  and `OpeningRangeState.post_range_bars` to Evidence Engine, exactly per
  the Accepted text (§1.8). Owned entirely by Evidence Engine; touches
  no Strategy Engine file. Its own RPI Implement phase, its own test
  suite (§17), its own independent implementation-conformance review
  before Step 2B may begin.
- **Step 2B — Implement ADR-035 Phase 2 (breakout qualification +
  lockout).** Consumes Step 2A's `post_range_bars` inside
  `OrbBreakoutStrategy.qualify()`, adds the new
  `titan_protocol/strategy_state_store/` package, and the 4 new
  `StrategyEngineConfig` fields (§11). Owned entirely by Strategy Engine
  (plus its own new persistence sibling); does not modify Evidence
  Engine. Its own RPI Implement phase, its own test suite (§18), its own
  independent implementation-conformance review before Phase 3 may
  begin.

**Why two increments, not one:** the two changes have different
architectural owners (Evidence Engine vs. Strategy Engine), different
risk profiles (Amendment 4 is a pure-fact addition with zero behavioral
risk to any existing consumer; Step 2B introduces Strategy Engine's
first stateful, side-effecting strategy and its first cross-package
persistence dependency), and different review scopes (Step 2A's review
need only re-verify the already-exhaustively-reviewed Amendment 4 text
matches its implementation; Step 2B's review must additionally verify
the breakout algorithm, concurrency atomicity, and persistence failure
semantics — a materially larger surface). Combining them into one commit
would force one review to carry both burdens at once, exactly the
"partial, unreviewable implementation" risk the original Plan's own
governing principle warned against. **Explicit gate:** Step 2B's own
RPI Research/Plan/Implement cycle does not begin until Step 2A's
implementation has been committed and has passed its own independent
conformance review with an ACCEPTED disposition.

---

## 5. Breakout Qualification Algorithm (ADR-035 §4, fully specified
against the Accepted Amendment 4 contract)

`OrbBreakoutStrategy.qualify()`'s new control flow (Step 2B), replacing
Phase 1's unconditional final `NOT_QUALIFIED`:

1. `check_eligibility()` — unchanged generic gate.
2. `opening_ranges` empty → `NOT_QUALIFIED`, unchanged Phase 1 reason.
3. `len(opening_ranges) > 1` → `NOT_QUALIFIED`, unchanged Phase 1 reason (§12 below re-confirms this stays correct, not a regression).
4. `opening_range = opening_ranges[0]`.
5. `not opening_range.is_formed` → `NOT_QUALIFIED`, unchanged Phase 1 reason.
6. `not opening_range.is_valid` → `NOT_QUALIFIED`, unchanged Phase 1 reason.
7. **New:** `post_range_bars = opening_range.post_range_bars`. Empty → `NOT_QUALIFIED`, `"No post-range evidence available yet"`.
8. **New:** `candidate = post_range_bars[-1]` (the most recent bar in Amendment 4's guaranteed-contiguous, guaranteed-complete sequence — this *is* "the most recent closed bar" ADR-035 §4 refers to, by construction of the Accepted contract, requiring no further "is this really the latest bar" proof).
9. **New — degenerate-geometry fail-closed check (Plan decision, flagged explicitly — see §5.1):** `candidate.high <= candidate.low` → `NOT_QUALIFIED`, `"Degenerate candle geometry"`.
10. **New — direction/breakout determination:** `candidate.close > opening_range.range_high` → bullish candidate, `range_boundary = range_high`; `candidate.close < opening_range.range_low` → bearish candidate, `range_boundary = range_low`; otherwise → `NOT_QUALIFIED`, `"No breakout: close within range"` (§4's own "never a wick-only touch" — only `close` decides direction, never `high`/`low`).
11. **New — momentum:** `not evidence.volatility.is_expansion` → `NOT_QUALIFIED`, `"No volatility expansion"` (reused field, unchanged from `SessionBreakoutStrategy`'s own precedent).
12. **New — ATR-distance:** `evidence.volatility.atr <= 0` → `NOT_QUALIFIED`, `"Insufficient volatility evidence (non-positive ATR)"` (fail-closed on degenerate ATR — §5.1). Else `abs(candidate.close - range_boundary) < config.orb_min_breakout_distance_atr_multiple * evidence.volatility.atr` → `NOT_QUALIFIED`, `"Breakout distance below ATR-relative threshold"`.
13. **New — body/wick ratio:** `abs(candidate.close - candidate.open) < config.orb_min_body_to_range_ratio * (candidate.high - candidate.low)` → `NOT_QUALIFIED`, `"Body/wick ratio below threshold"` (`>=` passes, matching ADR-035 §4's own "must be at least" wording literally — no invented operator).
14. **New — confirmation count:** `len(post_range_bars) < config.orb_min_confirmation_candles` → `NOT_QUALIFIED`, `"Insufficient confirmation candles"`.
15. **New — confirmation direction-consistency (§5.1):** the trailing `config.orb_min_confirmation_candles` entries of `post_range_bars` must *all* satisfy the same directional close-beyond-boundary test as step 10 (bullish: `close > range_high`; bearish: `close < range_low`) → else `NOT_QUALIFIED`, `"Confirmation candles inconsistent with breakout direction"`.
16. All of steps 1-15 passed → build the candidate `QUALIFIED` result (direction → `TradeIntent`, score/confidence per §6) but **do not return it yet** — proceed to lockout consumption (§9/§10) as one atomic, terminal step. If consumption succeeds, return the built `QUALIFIED` result; if capacity is already exhausted, return `NOT_QUALIFIED`, `"Already qualified for this opening range"` instead.

### 5.1 Explicitly flagged Plan-level decisions (not silently invented,
not left ambiguous — each is a minimal, evidence-grounded resolution
of a point ADR-035 does not spell out to the operator level)

- **Degenerate geometry (step 9):** ADR-035 §4 assumes well-formed OHLC; it does not say what happens if `high <= low` (a data-quality artifact, not a real market condition). Resolved fail-closed, consistent with this project's own capital-preservation-over-permissiveness doctrine — a bar that cannot geometrically have a body or a wick cannot honestly support either the body/wick check or a real breakout-distance measurement.
- **Boundary operator direction (step 10):** ADR-035 §4 says "close beyond" without stating whether an exact touch (`close == range_high`) counts. Resolved as strict `>`/`<` (an exact touch is not "beyond"), matching the half-open-interval convention Evidence Engine already uses for `[range_start, range_end)` and for ordinary-language "beyond."
- **ATR degeneracy (step 12):** ADR-035 §4 does not address `atr <= 0`. Resolved fail-closed: with `atr<=0` the ATR-distance filter would otherwise trivially pass any nonzero distance, silently defeating its own purpose; treating this as insufficient volatility evidence is the conservative reading.
- **Confirmation-window scope (steps 14-15):** ADR-035 §4 requires "that many consecutive closed bars beyond the range boundary" but does not state whether the *body/wick*/*ATR-distance* quality checks (steps 12-13) must also hold for every bar in the confirmation window, or only for the most recent one. Resolved minimally: quality checks (12-13) apply once, to the current/most-recent bar only; the confirmation-count requirement (14-15) only requires the trailing window's *closes* to stay beyond the boundary in the same direction. This is the smaller, more conservative-to-implement reading consistent with §4's own separation of "momentum/body/wick/ATR" (single-bar quality gates) from "confirmation candle count" (a separate, additional persistence-of-direction requirement). **Flagged for the Step 2B implementation-conformance review to re-confirm or correct** — this is an interpretation, not settled ADR-035 text.
- **Score/confidence formula (§6):** ADR-035 §5's own weighted-sum formula (`w1*range_quality + w2*mi_session_score + w3*volatility_score + w4*fvg_bonus`) requires `fvg_bonus` (Phase 3) and is presented alongside FVG confirmation, not defined standalone for Phase 2. §6 below resolves this by reusing `SessionBreakoutStrategy`'s own already-Accepted, already-shipped formula shape verbatim (same class of BREAKOUT-regime strategy, zero new computation, zero invented weights) rather than inventing new Phase-2-only config fields ADR-035 §13 never named. **Flagged explicitly as an interim formula**, to be extended (not replaced) by Phase 3's FVG bonus term and revisited if Phase 4 changes what MI facts ORB may use.

None of the above five items is a capital-preservation risk on the
"false `QUALIFIED`" axis: every one of them, read either way, only ever
narrows (never widens) which candidates can qualify, or affects the
*quality/ranking* of an already-genuine qualification (score/confidence),
never whether qualification itself is fabricated.

---

## 6. Qualification Result Semantics

`QualificationResult` (existing type, no new fields needed):

- `status`: `QUALIFIED` only after all of §5's steps 1-15 pass *and* lockout consumption (§9) succeeds; `NOT_QUALIFIED` at every earlier exit; `NOT_ELIGIBLE` from `check_eligibility()` (step 1) — unchanged shape from Phase 1.
- `score` (0-100): **interim Phase 2 formula**, `clamp(0.4*session_value + 0.3*mi_session_score + 0.3*evidence.volatility.volatility_score)`, reusing `component(evidence.report, "session")` and `market_intelligence.pair_safety.session.session_score` exactly as `SessionBreakoutStrategy` already does — zero new computation, explicitly flagged in §5.1 as interim, extended by Phase 3.
- `confidence` (0-1): `session_component.confidence if session_component else 0.5` — same reuse.
- `reason`: one of the deterministic strings named in §5's steps.
- `strengths`/`weaknesses`: mirror the existing 5-strategy convention (e.g. `strengths=("breakout beyond range_high", "volatility expanding", f"{n} confirmation candles")`, `weaknesses=()` on `QUALIFIED`; single-item `weaknesses` naming the failed check on `NOT_QUALIFIED`).
- `trade_intent`: `TradeIntent.BUY` for a bullish candidate, `TradeIntent.SELL` for bearish, `TradeIntent.NONE` on every non-`QUALIFIED` path — never guessed, deterministic from step 10's already-decided direction (ADR-035 §1: "ORB never guesses direction").

No sizing, stop-loss, take-profit, order type, or execution artifact is
introduced (ADR-026 Hard Rule 1, unchanged).

---

## 7. Phase Boundary Matrix (updated)

| Concern | Owning phase | Status |
|---|---|---|
| `OpeningRangeState`/`opening_ranges` | Phase 0 | Implemented |
| Range-formed/valid gating, stateless, never `QUALIFIED` | Phase 1 | Implemented, accepted |
| `post_range_bars`/`OpeningRangeBarObservation` evidence contract | **Step 2A** | **Implemented and independently accepted** (commit `dcf9b58`) |
| Close-beyond-range, ATR-distance, body/wick, momentum, confirmation count, lockout | **Step 2B** | **Fully specified (§5-§10), Plan finalized; not yet implemented — gated on this finalized Plan's own independent implementation-readiness review** |
| FVG confirmation (§5 of ADR-035) | Phase 3 | Out of scope — not designed here |
| Session-anchor matching, news/liquidity/holiday gates, `orb_approved_pairs` hard gate | Phase 4 | Out of scope — not designed here |
| Full `StrategyEngineConfig`/`config_loader.py` wiring, cross-field validation | Phase 5 | Out of scope — not designed here |
| Full-suite integration/regression validation | Phase 6 | Out of scope — not designed here |

---

## 8. Worked Examples (A-P)

All examples assume `config.orb_min_breakout_distance_atr_multiple=0.15`,
`orb_min_body_to_range_ratio=0.5`, `orb_min_confirmation_candles=1`
unless stated otherwise; `range_high=1.1050`, `range_low=1.0950`.

| # | Scenario | Result |
|---|---|---|
| A | `opening_ranges == ()` | `NOT_QUALIFIED`, "No opening range configured for this evaluation cycle" |
| B | `is_formed=False` | `NOT_QUALIFIED`, "Opening range not yet formed" |
| C | `is_valid=False` | `NOT_QUALIFIED`, "Opening range invalidated by a data gap or insufficient bar count" |
| D | Formed+valid, `post_range_bars == ()` | `NOT_QUALIFIED`, "No post-range evidence available yet" |
| E | `candidate.close = 1.1000` (inside range) | `NOT_QUALIFIED`, "No breakout: close within range" |
| F | `candidate.close = 1.1080` (> range_high) | Bullish candidate; proceeds to momentum/ATR/body/confirmation checks |
| G | `candidate.close = 1.0920` (< range_low) | Bearish candidate; proceeds similarly |
| H | `candidate.high = 1.1090` but `candidate.close = 1.1040` (wick crosses, close does not) | `NOT_QUALIFIED`, "No breakout: close within range" (step 10 only ever inspects `close`) |
| I | `len(post_range_bars) = 0` after direction determined impossible (range formed but zero post-range bars) | Already covered by D — cannot reach step 14 without passing step 7 |
| I′ | `len(post_range_bars) = 1`, `orb_min_confirmation_candles = 2` | `NOT_QUALIFIED`, "Insufficient confirmation candles" |
| J | `len(post_range_bars) = 3`, `orb_min_confirmation_candles = 2`, trailing 2 closes both beyond `range_high` | Confirmation passes; proceeds to `QUALIFIED` if all other checks hold |
| K | `abs(close-open) = 0.0003`, `(high-low) = 0.0010`, ratio 0.5 → threshold `0.0005`; `0.0003 < 0.0005` | `NOT_QUALIFIED`, "Body/wick ratio below threshold" |
| L | `abs(close-open) = 0.0005` exactly equals threshold `0.0005` | Passes (`>=`); proceeds |
| M | `abs(close-open) = 0.0008 > 0.0005` | Passes; proceeds |
| N | `candidate.high = candidate.low = 1.1080` | `NOT_QUALIFIED`, "Degenerate candle geometry" (step 9) |
| O | `len(opening_ranges) = 2` | `NOT_QUALIFIED`, "Multiple opening ranges configured, cannot disambiguate before Phase 4" (step 3, unchanged from Phase 1) |
| P | `post_range_bars` truncated to 1 entry because Amendment 4's own contiguity rule stopped extraction at an internal gap, while `orb_min_confirmation_candles = 2` | `NOT_QUALIFIED`, "Insufficient confirmation candles" — identical outcome and reason to I′; the *cause* of the short tuple (gap vs. simply not enough time elapsed vs. bound reached) is irrelevant to Strategy Engine, exactly as Amendment 4's own review already established |

For every example that reaches `QUALIFIED`, the outcome is additionally
gated on lockout consumption succeeding (§9) — a scenario reaching every
breakout check successfully still returns `NOT_QUALIFIED`,
`"Already qualified for this opening range"` if the `(pair, range_start)`
allowance is already exhausted.

---

## 9. Lockout Semantics (unchanged from the prior Plan revision,
re-confirmed against Amendment 4's Accepted text — no contradiction found)

- **Identity:** `(pair, range_start)`.
- **Consumption event:** `qualify()` deciding `QUALIFIED` (i.e., after §5's step 15 passes), and only that.
- **Non-consuming paths:** every `NOT_QUALIFIED`/`NOT_ELIGIBLE` leaves the counter untouched.
- **A would-be-`QUALIFIED` result that later loses the selection cascade still consumes the allowance** — consumption happens inside `qualify()`, before `select_winning_strategy()` ever runs.
- **Trade close, Risk rejection, Compliance rejection, execution failure** do not reset or decrement the counter.
- **Reset/rollover:** a new `range_start` is a new, unblocked key.

---

## 10. Persistence Design (Step 2B) — `titan_protocol/strategy_state_store/`

New sibling top-level package (not nested in `strategy_engine/`, never a
reuse of `compliance_state_store`/`runtime/in_flight_store.py`):

```
titan_protocol/strategy_state_store/
    __init__.py
    models.py    PersistedOrbQualificationState(schema_version, entries: Dict[str, int])
                 CorruptStateError
    config.py    StrategyStateStoreConfig(state_file: Path)
    store.py     OrbQualificationStore
                 module-level `_LOGGER = logging.getLogger(__name__)`
                 and `_safe_log_persist_failure(exc: Exception) -> None`
                 (see the write-failure contract below)
```

`store.py`'s logger is a plain module-level `logging.getLogger(__name__)`
— not a constructor/callback dependency on `OrbQualificationStore`. No
`logging_sink.py` is added for this package: unlike the engine packages
that have one, this store has exactly one thing to log (a persist
failure), which does not warrant the structured-snapshot-logging
abstraction those packages exist for (CLAUDE.md §6 — smallest change that
solves the problem).

**`entries` key encoding:** `f"{pair}|{range_start.isoformat()}"` (a
single string, since JSON object keys must be strings) — no
`strategy_id`, `session`, or `range_end` in the key (§16 of the prior
Plan revision's own reasoning, unchanged: this store is already scoped
to one strategy's own needs by virtue of living in its own package; a
second strategy needing similar state gets its own store).

**`OrbQualificationStore` public surface — exactly one atomic method,
never split across two public calls:**

```python
class OrbQualificationStore:
    def __init__(self, config: StrategyStateStoreConfig) -> None:
        self._config = config
        self._lock = threading.Lock()

    def try_consume(self, pair: str, range_start: datetime, max_allowed: int) -> bool:
        """Atomically: load current state, check entries.get(key, 0) < max_allowed,
        increment and persist if so, return whether consumption succeeded.
        The entire check-then-increment-then-persist sequence executes while
        holding self._lock -- no caller can observe an intermediate state."""
```

There is deliberately **no separate `get_count()`/`increment()` pair** —
splitting the operation into two public calls is exactly the race this
design must prevent (§12 below).

**In-memory authority model (corrected — resolves the write-failure
contradiction identified in the Step 2B implementation-readiness
review):** `OrbQualificationStore` loads `entries` from disk exactly
once, at first access (construction or lazy first call, guarded by the
same `self._lock`), and thereafter treats its own in-memory `entries`
dict as the sole authority `try_consume()` reads and increments for the
rest of the process's lifetime. Disk state is written *from* that
authoritative in-memory dict after every successful increment — never
read back mid-process to "refresh" it. This is what makes "the decision
stands" true for every subsequent call in the same process, not merely
the one call that experienced a write failure: a lost write cannot cause
a later call to under-count and silently re-allow a `(pair, range_start)`
that was already consumed, since a later call never re-reads the disk to
find out.

**Persistence writes the full dictionary, never a per-key delta
(clarified — resolves the disk/memory-invariant gap identified in the
Step 2B implementation-readiness re-review):** each successful
`try_consume()` call serializes the *entire* in-memory `entries` dict to
disk — the same whole-JSON-object model `PersistedOrbQualificationState.entries:
Dict[str, int]` already implies, and the same whole-file-replace
convention `compliance_state_store` already uses; there is no per-key
delta or append format anywhere in this design. **Consequence (the
self-healing property):** if a persist attempt fails for one key's
increment, that increment remains in the authoritative in-memory dict
(above) and is not lost — it is simply not yet durable. The *next*
successful `try_consume()` call for *any* `(pair, range_start)` key,
including an unrelated one, serializes the whole current `entries` dict
to disk, which durably writes the previously-failed key's increment too,
as a side effect. No explicit retry logic is introduced or needed:
ordinary subsequent operation (new opening ranges qualifying for other
pairs over the trading day) is what eventually flushes a stalled write to
disk. The narrow exposure window this leaves — a crash after a failed
persist and before any later successful persist anywhere in the store —
is the same ADR-035 §18.A-accepted residual risk discussed below, not a
new one.

**Read/write semantics**, mirroring `compliance_state_store`'s own
established convention exactly (file-backed JSON, `schema_version`
checked on that one initial load, atomic write via `tempfile.mkstemp()` →
`fsync` → `os.replace()`, `.bak` rotation before every overwrite):

- Missing state file (first-ever run) → bootstrap `entries: {}`, never an error.
- Corrupt/unparseable file on the one initial load → attempt `.bak` recovery; if that also fails, raise `CorruptStateError` (fail closed — construction itself fails; `try_consume()` is never reached with an unreadable store silently treated as "nothing consumed yet").
- Unsupported `schema_version` on the one initial load → same fail-closed path, no migration attempted.
- **Write failure after the in-memory increment (corrected contract):** the in-memory increment inside `try_consume()`'s critical section happens first and is never rolled back — that increment *is* the atomic decision (§11), and is what "the decision stands" means. The subsequent disk-persist call is then attempted; if it raises, `try_consume()` catches that specific exception **inside the store** — never letting it cross the method's own boundary — and calls the module-level `_safe_log_persist_failure(exc)` helper (defined alongside `OrbQualificationStore` in `store.py`, using the module-level `_LOGGER = logging.getLogger(__name__)`, no constructor/callback dependency), which itself wraps its own `_LOGGER.exception(...)` call in a bare `except Exception: pass` so a *logging* failure can never compound the original persist failure — mirroring this codebase's own established fault-containment pattern (the positions-staleness diagnostic's `_safe_log_exception()` precedent in `deployment_windows/start.py`). `try_consume()` then returns `True` exactly as it would on a successful persist. **No exception ever crosses `try_consume()`'s boundary for a write failure.** This satisfies ADR-035/ADR-024 §18.A's actual requirement — persisted state must not be "silently swallowed" — through visible, unmissable logging, not through letting an exception propagate; §18.A's text never required the latter, and reading it that way was this Plan's own prior error, since `StrategyEngine.evaluate()`'s `qualifications = tuple(strategy.qualify(...) for strategy in self.registry.all())` has zero exception handling around each `qualify()` call (independently confirmed by direct code read during the Step 2B readiness review) — an exception escaping `try_consume()` would abort that entire evaluation cycle for all 5 legacy strategies too, a materially worse outcome than a durability gap that is loudly logged. `OrbBreakoutStrategy.qualify()` therefore needs no exception handling of its own around `try_consume()`, since the store's public contract now guarantees it never raises for this reason.

**Deliberate deviation from the `compliance_state_store` precedent
(confirmed by the RPI Research phase's direct read of
`compliance_state_store/store.py`):** `ComplianceStateStore._save()`
does **not** catch its own write failures — an exception during its
`tempfile.mkstemp()`/`os.replace()` sequence propagates uncaught to its
caller (`deployment_windows/start.py`'s `reconcile()` call site, which
has no local try/except either). `OrbQualificationStore.try_consume()`
deliberately does not follow that shape. The reason is call-site risk,
not inconsistency: `ComplianceStateStore`'s callers are the Runtime
live-cycle loop, a different architectural context from
`StrategyEngine.evaluate()`/`evaluate_batch()`, whose own
`qualifications = tuple(strategy.qualify(...) for strategy in
self.registry.all())` and `results = tuple(self.evaluate(...) for pair,
... in sorted(pairs.items()))` comprehensions have **zero** exception
handling (confirmed by direct code read) — an exception escaping one
strategy's `qualify()` call would abort not merely that pair's other 4
qualifications, but the entire multi-pair `evaluate_batch()` cycle then
in progress. Containing the write failure *inside* `try_consume()` is
therefore this design's own correctly-justified choice for its own
call site, not a deviation to be reconciled away — `compliance_state_store`
is not wrong for its own call site either; the two stores simply serve
callers with different failure tolerances. ADR-035 §18.A's own semantics
are fully preserved either way: the in-memory qualification stands after
a failed persist (§this section, above), and the narrow
crash-before-the-next-successful-whole-state-write duplication risk is
an ADR-accepted residual, not something this deviation introduces or
must resolve.

**Dependency injection:** `OrbBreakoutStrategy.__init__(self, store: OrbQualificationStore)` — the strategy's first, narrowly-scoped instance state (ADR-035 §6's own anticipated "explicit, narrow, documented exception" to Strategy Engine's stateless convention). `build_default_registry()` is unaffected since `OrbBreakoutStrategy` is not registered there (§13).

**Test isolation:** tests construct `OrbQualificationStore` against a
`tempfile.TemporaryDirectory()`-backed `StrategyStateStoreConfig`, the
same pattern this codebase already uses for `compliance_state_store`
tests — no new test infrastructure invented.

**Rollback:** reverting the implementing commit leaves any on-disk
persisted state file inert (Phase 1/pre-Phase-2 code never reads it),
identical reasoning to the original Plan's own rollback analysis.

---

## 11. Concurrency Contract (load-bearing — resolves §9/§10 of the task)

`StrategyEngine.evaluate()`'s own docstring ("may be called concurrently
from many threads against one shared instance") is treated as
architectural fact, not today's sequential Runtime loop. Two concurrent
`qualify()` calls for the identical `(pair, range_start)` **cannot** both
observe remaining capacity and both return `QUALIFIED` when the
configured limit permits only one, because:

1. Both calls, having independently passed §5's steps 1-15 (pure,
   side-effect-free reads of `evidence`/`market_intelligence`/`config`),
   each call `store.try_consume(pair, range_start, max_allowed)`.
2. `try_consume()` acquires `self._lock` (a single `threading.Lock()`
   per `OrbQualificationStore` instance, and `OrbBreakoutStrategy`
   holds exactly one `OrbQualificationStore` instance for the process
   lifetime, injected once at construction — never one instance per
   call).
3. The **entire** "read current in-memory count → compare to
   `max_allowed` → increment the in-memory dict → best-effort persist"
   sequence executes while holding that lock (§10's in-memory authority
   model — the in-memory dict, never the disk, is what this step reads
   and compares). The second caller to acquire the lock necessarily
   observes the already-incremented in-memory count from the first
   caller's completed critical section, and correctly receives `False`
   (capacity exhausted) if `max_allowed=1` — regardless of whether the
   first caller's disk persist succeeded or failed (§10).
4. `qualify()` returns `QUALIFIED` if and only if `try_consume()`
   returned `True`; otherwise it returns `NOT_QUALIFIED`,
   `"Already qualified for this opening range"`.

This provides thread safety — the only concurrency guarantee this
codebase's own architecture requires or has ever needed anywhere
(`ReservationLedger`/`InFlightCommandRegistry` precedent, both
single-process, thread-lock-guarded). Crash safety is separately
provided by §10's atomic file replace. Cross-process concurrency remains
explicitly out of scope, consistent with the single-Bridge/single-Runtime
deployment topology this codebase has everywhere else — not claimed
solved, simply not a real scenario given actual deployment architecture.

**If a future implementation proposed splitting `try_consume()` into
separate `peek()`/`commit()` calls for any reason, that proposal would
not be implementation-ready** — this Plan explicitly rejects that shape.

---

## 12. Lockout Ordering (resolves the atomicity-boundary requirement)

Exact sequence, restated from §5/§9 for clarity as its own explicit
contract:

```
1. check_eligibility()                              [existing generic gate]
2-6. opening-range presence/count/formed/valid gates  [unchanged Phase 1]
7-9. post_range_bars presence + degenerate-geometry   [new, §5]
10.  direction/breakout determination                 [new, §5]
11-15. momentum, ATR-distance, body/wick, confirmation [new, §5]
16.  build candidate QUALIFIED result (not returned yet)
17.  store.try_consume(pair, range_start, max_allowed) [atomic, §11]
18a. True  -> return the QUALIFIED result built in 16
18b. False -> return NOT_QUALIFIED, "Already qualified for this opening range"
```

This ordering guarantees both required properties: **no capacity is ever
consumed for a non-qualified candidate** (steps 1-15 must all pass
before `try_consume()` is ever called), and **`QUALIFIED` is never
returned without successfully consuming capacity** (step 18a only
executes when `try_consume()` itself returned `True`). The atomicity
boundary is exactly `try_consume()`'s own critical section (§11) — no
check or decision made in steps 1-16 needs to be atomic with anything
else, since none of them have side effects; only step 17 does, and it is
self-contained.

---

## 13. Configuration Impact

**New `StrategyEngineConfig` fields (Step 2B only — the 4 ADR-035 §13
fields Phase 2 actually needs, no others pulled forward):**

| Field | Type | Default | Safe range | Source |
|---|---|---|---|---|
| `orb_min_breakout_distance_atr_multiple` | `float` | 0.15 | `> 0` | ADR-035 §13 |
| `orb_min_body_to_range_ratio` | `float` | 0.5 | `0 <= x <= 1` | ADR-035 §13 |
| `orb_min_confirmation_candles` | `int` | 1 | `>= 1` | ADR-035 §13 |
| `orb_max_qualifications_per_range` | `int` | 1 | `>= 1` | ADR-035 §13 |

**Resolves the prior Plan's open question:** `StrategyEngineConfig`
gains its **first** `__post_init__`, validating exactly these 4 new
fields (never retroactively validating pre-existing thresholds — that
is out of scope, a separate concern). ADR-035 §13 itself states "every
field fails closed at config-load time... not implemented here,
specified for the implementation phase" — Phase 2 (Step 2B) *is* that
implementation phase for these 4 fields, so adding validation here is
ADR-mandated, not scope creep.

**ADR-035 §13 requires no cross-field validation among Step 2B's 4
fields (confirmed by the RPI Research phase's direct read of ADR-035
§13's own "Cross-field validation (required)" clause):** that clause
names exactly three checks — anchor-window-overlap, min-range-bars
feasibility against the configured bar timeframe, and the FVG
scoring-weight sum. All three reference fields that are either **already
validated elsewhere** (the anchor-overlap check is
`EvidenceEngineConfig._validate_no_overlapping_anchors()`, Phase 0,
confirmed present and unrelated to `StrategyEngineConfig`) or
**out of Step 2B's scope** (`orb_fvg_score_weight`, Phase 3). None of
the three apply to `orb_min_breakout_distance_atr_multiple`,
`orb_min_body_to_range_ratio`, `orb_min_confirmation_candles`, or
`orb_max_qualifications_per_range`. `StrategyEngineConfig.__post_init__`
therefore validates only each of these 4 fields' own individual range
(the table above) — no cross-field check between them, and critically,
**no Phase 3+ validation (the FVG weight-sum check) is pulled forward**
merely because it lives in the same ADR §13 clause. An implementer must
not invent a cross-field check here; none is required or authorized.

**`EvidenceEngineConfig.opening_range_post_range_bar_window` (Step 2A,
Amendment 4's own field) remains entirely independent** — no
cross-reference to `orb_min_confirmation_candles` or any Strategy Engine
field, confirmed by direct inspection of both current config files (no
such reference exists today, and none is proposed).

**Deferred, not Step 2B's scope:** `orb_approved_pairs`,
`orb_session_anchors`* , `orb_range_duration_minutes`* ,
`orb_min_range_bars`* , `orb_min_range_atr_ratio`, `orb_max_spread_pips`,
`orb_fvg_max_age_bars`, `orb_fvg_min_size_atr_multiple`,
`orb_fvg_score_weight`, `orb_min_liquidity_score` — Phase 3/4/5 per §7.
(*`orb_session_anchors`/`orb_range_duration_minutes`/`orb_min_range_bars`
are, on inspection, actually `EvidenceEngineConfig.opening_range_*`
fields already implemented in Phase 0 — ADR-035 §13's own table mixes
Evidence-Engine-owned and Strategy-Engine-owned fields without labeling
ownership, an ADVISORY documentation note for ADR-035, not a Step 2B
blocker.)

`config_loader.py`/example-config wiring remains Phase 5, unchanged.

---

## 14. Approved-Pair Behavior

Unchanged: `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` gets no
`OPENING_RANGE_BREAKOUT` entry in Step 2B (ADR-035 §18.B item 4, Phase 5
scope). Tests construct an explicit `StrategyEngineConfig` override,
exactly as Phase 1's `_ORB_APPROVED_CONFIG` already does. No production
approved pairs added merely to make tests easier.

---

## 15. Registration

`OrbBreakoutStrategy` remains **absent** from `build_default_registry()`
through Step 2B (ADR-035 §17 assigns production registration no earlier
than Phase 6, and even that is integration testing, not necessarily
production wiring). Tests construct `OrbBreakoutStrategy` directly or via
a test-only registry, never the production factory. No registry-count
test is weakened.

---

## 16. Multiple-Range Behavior

Amendment 4's per-anchor factual independence (each `OpeningRangeState`
derives `post_range_bars` independently, confirmed by its own Accepted
test commitment) does **not** license Strategy Engine to choose among
multiple ranges. §5's step 3 (`len(opening_ranges) > 1` → `NOT_QUALIFIED`)
is preserved unchanged from Phase 1 — no Phase 4/5 range-selection or
disambiguation policy is introduced here.

---

## 17. Architecture-Boundary Impact

**Step 2A (Amendment 4 implementation):** touches only
`titan_protocol/evidence_engine/{models.py,opening_range.py,config.py}`.
No new import boundary needed — Evidence Engine already owns its own
`Bar` model and `expected_bar_interval_seconds`; nothing new is imported
from anywhere.

**Step 2B (Phase 2 Strategy Engine implementation):** touches
`titan_protocol/strategy_engine/{config.py, strategies/orb_breakout.py,
strategies/__init__.py}` plus the new sibling package
`titan_protocol/strategy_state_store/`. `test_architecture.py`'s
`ALLOWED_UPSTREAM_PREFIXES` (currently `titan_protocol.evidence_engine`,
`titan_protocol.market_intelligence`) needs exactly one new entry,
`titan_protocol.strategy_state_store`, since `orb_breakout.py` will
import `OrbQualificationStore` from it — narrow, correctly-scoped,
mirroring the existing pattern. No Risk/Compliance/Runtime/Bridge
authority expansion in either increment.

---

## 18. Structural-Boundary Impact

**Corrected by the RPI Research phase's direct read of both
`test_structural_boundary.py` files' actual `_LATER_AUTHORIZED_EXCEPTIONS`
lists** (the prior Plan text overstated this section's scope):
`titan_protocol/strategy_engine/models.py`,
`strategy_engine/strategies/__init__.py`, and
`strategy_engine/strategies/orb_breakout.py` are **already present** in
both files' exception lists, added at Phase 1 (confirmed by direct
inspection, not re-derived from this Plan's own prior claim). Step 2B
touches exactly one `strategy_engine` file **not** already exempted:
`titan_protocol/strategy_engine/config.py` (the 4 new fields + first
`__post_init__`). **Exactly one new exception-list entry, in each of the
two files, is required — not three, and not a blanket
`strategy_engine/` re-authorization.**

The new `titan_protocol/strategy_state_store/` package requires **no
exception entry in either file**: `_FROZEN_PREFIXES` in both files
covers only pre-existing, already-frozen pipeline-stage packages
(`evidence_engine`, `market_intelligence`, `strategy_engine`,
`risk_engine`, `compliance_engine`, `runtime`, `reliability`,
`market_data_ingestion`, `news_ingestion` — confirmed by direct read);
`strategy_state_store` is not among them and does not yet exist, so no
file under it can trip the frozen-prefix check regardless of exception
entries. This is a mechanism fact, not a gap — the structural-boundary
guard exists to catch *undocumented changes to already-frozen packages*,
and a brand-new, not-yet-frozen package is categorically outside what it
polices. (Whether to add `titan_protocol/strategy_state_store/` to
`_FROZEN_PREFIXES` going forward, for its own future protection once it
exists, is a policy choice for whoever owns these test files — not a
Step 2B implementation requirement, and not decided here.)

---

## 19. File Impact Matrix

**Step 2A (Amendment 4 implementation):**

| File | Classification | Reason |
|---|---|---|
| `titan_protocol/evidence_engine/models.py` | REQUIRED | Add `OpeningRangeBarObservation`, `post_range_bars` field |
| `titan_protocol/evidence_engine/opening_range.py` | REQUIRED | Compute `post_range_bars` inside `_compute_single_range()` |
| `titan_protocol/evidence_engine/config.py` | REQUIRED | Add `opening_range_post_range_bar_window`, validate `>= 1` |
| `tests/titan_protocol/evidence_engine/test_opening_range.py` | REQUIRED | Extend with Amendment 4's own test list |
| `tests/titan_protocol/evidence_engine/test_structural_boundary.py` (if one exists) or the compliance/news files' exception lists | POSSIBLY REQUIRED | Narrow exception entries for the 3 touched files |
| `titan_protocol/evidence_engine/engine.py` | READ ONLY | `_analyze()`'s call site is unchanged; no edit needed |
| `titan_protocol/strategy_engine/*` | OUT OF SCOPE | Not touched by Step 2A |
| `CHANGELOG.md` | REQUIRED | Dated entry per TEAM.md §9 convention (Implement phase) |

**Step 2B (Phase 2 ORB implementation — Step 2A itself is already implemented and independently accepted; Step 2B remains gated on this finalized Plan's own independent implementation-readiness review):**

| File | Classification | Reason |
|---|---|---|
| `titan_protocol/strategy_engine/config.py` | REQUIRED | 4 new fields + first `__post_init__` |
| `titan_protocol/strategy_engine/strategies/orb_breakout.py` | REQUIRED | Breakout algorithm (§5), lockout consumption (§9-§12) |
| `titan_protocol/strategy_engine/strategies/__init__.py` | POSSIBLY REQUIRED | Only if `OrbBreakoutStrategy`'s constructor signature change needs re-export adjustment (unlikely) |
| `titan_protocol/strategy_state_store/{__init__.py,models.py,config.py,store.py}` | REQUIRED (new package) | Persistence design (§10) |
| `tests/titan_protocol/strategy_engine/test_orb_breakout_foundation.py` | REQUIRED | Extend with Step 2B's own test matrix (§20 below), renamed or extended |
| `tests/titan_protocol/strategy_state_store/*` | REQUIRED (new) | Store unit tests |
| `tests/titan_protocol/strategy_engine/test_architecture.py` | REQUIRED | One new `ALLOWED_UPSTREAM_PREFIXES` entry |
| `tests/titan_protocol/compliance_state_store/test_structural_boundary.py` | REQUIRED | One new `_LATER_AUTHORIZED_EXCEPTIONS` entry: `titan_protocol/strategy_engine/config.py` (§18 — the other 3 `strategy_engine` files are already exempted from Phase 1; `strategy_state_store/*` needs no entry) |
| `tests/titan_protocol/news_ingestion/test_structural_boundary.py` | REQUIRED | Same one new entry, mirrored (§18) |
| `titan_protocol/strategy_engine/strategies/{bos_fvg,liquidity_sweep_mss,range_reversal,session_breakout,trend_continuation}.py` | UNNECESSARY | No legacy strategy touched |
| `titan_protocol/strategy_engine/strategies/registry.py`, `engine.py`, `selection.py`, `eligibility.py` | READ ONLY | No change needed; generic mechanisms already support this |
| `titan_protocol/evidence_engine/*` | OUT OF SCOPE | Not touched by Step 2B |
| `docs/adr/ADR-035-orb-strategy.md`, `ADR-036*` | OUT OF SCOPE | No amendment needed for either increment |
| `CHANGELOG.md` | REQUIRED | Dated entry per TEAM.md §9 convention |

---

## 20. Test Plan — Step 2A (Amendment 4 implementation)

Carries forward Amendment 4's own Accepted test list verbatim: model
shape/immutability of `OpeningRangeBarObservation`; `post_range_bars`
defaults to `()`; first candidate exactly at `range_end` (eligible);
first candidate later than `range_end` (`()`); first candidate earlier
than `range_end` (`()`); the concrete missing-boundary-bar scenario;
exact OHLC/timestamp/index preservation; chronological ordering;
window-bound enforcement; a genuinely completed candidate included; a
candidate failing the completion inequality excluded; a candidate
exactly at the completion boundary included; an internal
subsequent-candidate gap stops extraction; an incomplete candidate stops
extraction; no skip-and-resume; the multiple-opening-range independence
test (Amendment 4's own Testing item G); `evaluate()` behavioral
regression; `evaluate_snapshot()` integration; architecture-boundary
tests; full existing Evidence Engine regression suite green.

---

## 21. Test Plan — Step 2B (Phase 2 ORB)

- **Eligibility:** generic `check_eligibility()` gate unchanged from Phase 1.
- **Range gates:** no range, unformed, invalid, multiple ranges — unchanged Phase 1 behavior, re-tested for regression.
- **Post-range evidence:** empty `post_range_bars` → `NOT_QUALIFIED`.
- **Direction/breakout:** no breakout (close inside range); upside breakout; downside breakout; wick-only crossing (close does not confirm) → `NOT_QUALIFIED`.
- **Momentum:** `is_expansion=False` → `NOT_QUALIFIED`.
- **ATR-distance:** below threshold; at threshold (passes, `>=`); above threshold; degenerate `atr<=0` → `NOT_QUALIFIED`.
- **Body/wick:** below threshold; exactly at threshold (passes); above threshold; degenerate `high<=low` → `NOT_QUALIFIED`.
- **Confirmation count:** insufficient history; exactly sufficient; direction-inconsistent trailing bar → `NOT_QUALIFIED`.
- **QualificationResult correctness:** exact `status`/`score`/`confidence`/`reason`/`trade_intent` fields for a genuine `QUALIFIED` case; `trade_intent=NONE` on every non-`QUALIFIED` path.
- **Lockout:** first qualification for a `(pair, range_start)` succeeds; a second attempt at the same key with `max_allowed=1` is denied (`"Already qualified for this opening range"`); a `NOT_QUALIFIED` result never consumes; a different pair is independent; a different `range_start` is independent.
- **Concurrency:** two simulated concurrent `qualify()` calls (e.g. via threads calling into one shared `OrbQualificationStore`) for the identical `(pair, range_start)` with `max_allowed=1` produce exactly one `QUALIFIED` and one `NOT_QUALIFIED` — never two `QUALIFIED`.
- **Persistence:** state survives store-recreation (simulated restart); missing file bootstraps safely; corrupt file fails closed at construction (with `.bak` recovery attempted first); unsupported schema version fails closed at construction; a disk-persist failure inside `try_consume()` is caught internally, logged via `_safe_log_persist_failure()`, and `try_consume()` still returns `True` — the call must not raise; a second `try_consume()` call in the same process for the same `(pair, range_start)` after a first call's persist failure still correctly observes the incremented in-memory count and returns `False` if `max_allowed` is now exhausted (proving the in-memory authority model, not just the disk, is what prevents duplicate consumption); a failure inside `_safe_log_persist_failure()` itself must also not raise past `try_consume()` (mirrors the `_safe_log_exception()` test-coverage precedent).
- **Restart duplication after a failed persist (required — documents the ADR-035 §18.A-accepted residual risk as a tested fact, not a silent assumption):** force a persist failure on one `try_consume()` call for `(pair, range_start)` with `max_allowed=1` (it still returns `True`, per the corrected contract above); without any further successful persist, construct a **new** `OrbQualificationStore` instance against the same on-disk state file (simulating a process restart); assert the new instance's first `try_consume()` call for the identical `(pair, range_start)` also returns `True` — i.e., the reload observes the stale, un-incremented disk count and a second qualification for that exact range becomes possible. This test exists to keep the known, ADR-accepted limitation visible and regression-tested, not to assert it is safe.
- **Later whole-state self-healing (required — proves the full-dictionary persistence property above):** force a persist failure on one `try_consume()` call for key A, then perform a *successful* `try_consume()` call for a different key B on the *same, still-live* store instance; assert that reading the on-disk file afterward shows key A's incremented count durably present alongside key B's — proving a later successful write for an unrelated key opportunistically flushes an earlier key's failed increment, bounding the residual-risk window described above to "until the next successful write anywhere in the store."
- **Regression:** five legacy strategies unchanged; `OrbBreakoutStrategy` still absent from `build_default_registry()`; full `tests/titan_protocol` suite green.
- **Architecture:** `test_architecture.py` green including the new `strategy_state_store` upstream-prefix entry; both `test_structural_boundary.py` files' narrowly-scoped exceptions in place.

---

## 22. Risk Register (updated)

| Risk | Class | Status |
|---|---|---|
| False breakout (rule too permissive) | HIGH | Mitigated by §5's fully-specified, conservative checks (steps 9-15) |
| Duplicate same-range qualification | CRITICAL | Mitigated by §11/§12's atomic `try_consume()` |
| Restart duplication | CRITICAL | Mitigated by §10's persistence design **in the normal (successful-write) case**; a narrow, ADR-035 §18.A-accepted residual window remains for a crash between a failed persist and the next successful whole-state write (§10, §21) — not fully eliminated, and not claimed to be |
| Concurrent lost update | HIGH | Mitigated by §11's single-lock atomic critical section |
| Corrupt state treated as empty | CRITICAL | Mitigated by §10's fail-closed load path |
| Score/confidence formula is an interim approximation | LOW | Flagged explicitly (§5.1/§6); never affects whether a trade occurs, only ranking/sizing quality |
| Confirmation-window quality-check scope is an interpretation | LOW | Flagged explicitly (§5.1) for the Step 2B conformance review to confirm or correct |
| Two implementation increments landing out of the specified order | MEDIUM | Mitigated by §4's explicit gate — Step 2B's own RPI cycle must not begin before Step 2A's is independently accepted |
| Write-failure exception escaping `try_consume()` and aborting `evaluate()`/`evaluate_batch()` for all strategies/pairs | CRITICAL | **Resolved** — `try_consume()` catches and logs the write failure internally via an exception-safe logging call and never raises past its own boundary (§10); confirmed by the RPI Research phase's direct read that `evaluate_batch()`'s own blast radius is the entire multi-pair cycle, not just one pair, making this containment more load-bearing than originally stated, not less |
| Multiple-range disambiguation prematurely invented | LOW | Explicitly preserved as `NOT_QUALIFIED` (§16), not touched |
| Accidental ORB registration | LOW | Unchanged, explicitly preserved (§15) |
| Legacy-strategy regression | LOW | No legacy file touched by either increment |
| §18's structural-boundary scope overstated (3 exception entries claimed, only 1 per file actually needed) | LOW | **Resolved by the RPI Research phase** — corrected in §18/§19 of this finalization |
| `OrbQualificationStore`'s internal write-failure containment left unexplained as a departure from `compliance_state_store` precedent | LOW | **Resolved** — §10 now states explicitly why the two stores differ (§10, this finalization) |
| ADR-035 §13 cross-field validation clause misapplied to Step 2B's 4 fields | LOW | **Resolved** — §13 now states explicitly that none of ADR §13's three named cross-field checks apply to Step 2B's fields (§13, this finalization) |
| Stale HEAD/commit references in this document | LOW (governance hygiene) | **Resolved** — updated to `085e7e5` throughout (this finalization) |

---

## 23. Out-of-Scope Confirmation

FVG confirmation (Phase 3), MI/eligibility gating (Phase 4),
config-loader wiring (Phase 5), and full-suite validation (Phase 6) are
not designed, referenced as implementable, or pulled forward anywhere in
this Plan. ADR-036 strategy consolidation is untouched. No legacy
strategy is modified, retired, disabled, or renamed.

---

## 24. Acceptance Criteria (for this Plan to be called
implementation-ready)

1. ADR-024 Amendment 4 is Accepted — **satisfied**.
2. Step 2A and Step 2B are specified as separate, explicitly gated increments — **satisfied** (§4).
3. The breakout algorithm is fully specified against Amendment 4's real, Accepted fields, with every ambiguous point explicitly flagged rather than silently invented — **satisfied** (§5, §5.1).
4. Lockout identity/consumption/persistence/concurrency are fully specified, including the atomicity boundary — **satisfied** (§9-§12).
5. `OrbBreakoutStrategy` remains unregistered through both increments — **satisfied** (§15).
6. No legacy strategy is modified — **satisfied** (§23).
7. A full test matrix exists for both increments — **satisfied** (§20-§21).
8. **Updated to reflect actual state (the original criterion, "neither increment has begun implementation," is now false and would misstate Step 2A's own progress if left unchanged):** Step 2A has been implemented and independently accepted (commit `dcf9b58`); Step 2B has not begun implementation and remains correctly gated on this finalized Plan's own independent implementation-readiness review — **satisfied** for Step 2B, the only increment this finalization authorizes proceeding toward.

---

## 25. Rollback Strategy

Step 2A and Step 2B are independently revertible (`git revert` on
whichever commit implements each), since neither is consumed by the
other until Step 2B's own implementation explicitly reads
`post_range_bars`. Reverting Step 2B alone leaves Step 2A's evidence
contract in place, unused, harmless. Reverting Step 2A would break Step
2B if Step 2B has already landed — this Plan's own gate (§4) exists
precisely to prevent that ordering from ever occurring in practice.

---

## 26. Engineering Checklist

- [x] Repository evidence re-verified directly against current HEAD (`085e7e5`, at Plan finalization).
- [x] Amendment 4's Accepted text re-read in full and relied on without restating its own proofs.
- [x] Breakout algorithm fully specified, every threshold traced to ADR-035 §13, every ambiguity explicitly flagged.
- [x] Worked examples (A-P) covering every load-bearing branch.
- [x] Lockout/persistence/concurrency fully specified, including the atomicity boundary.
- [x] Configuration ownership kept one-directional (Evidence Engine retention bound vs. Strategy Engine confirmation policy).
- [x] Registration/approved-pairs/multiple-range behavior preserved unchanged.
- [x] File impact matrices and test plans produced for both increments separately.
- [x] Step 2A implementation — complete (commit `dcf9b58`).
- [x] Step 2A independent conformance review — complete, **ACCEPTED**.
- [x] §10's write-failure self-contradiction — identified by the Step 2B implementation-readiness review, corrected in a prior revision (Plan-level only, no code touched).
- [x] That correction's own independent re-review — complete: **STEP 2B PLAN APPROVED WITH REQUIRED MINOR REVISIONS** (full-dictionary persistence, the store's module-level exception-safe logger, and two durability tests covering restart duplication after a failed persist and later whole-state self-healing).
- [x] The three required minor revisions — applied (§10, §21).
- [x] Step 2B's own RPI Research phase — complete: every repository fact this Plan depends on independently re-derived directly from source (ORB foundation, Step 2A evidence contract, breakout-predicate ADR-vs-Plan attribution, config contract, score/confidence precedent, persistence precedent, concurrency proof, architecture/structural-boundary scope). Disposition: **STEP 2B RESEARCH COMPLETE — READY FOR PLAN FINALIZATION**.
- [x] Plan finalization — this revision incorporates all four Research findings (§18 structural-boundary scope corrected; §10 documents the deliberate `compliance_state_store` deviation; §13 states no ADR-035 §13 cross-field validation applies; all stale HEAD references updated to `085e7e5`).
- [ ] Step 2B implementation — not started, gated on the below.
- [ ] Step 2B's own independent implementation-readiness review of this finalized Plan — not started; required before Step 2B's RPI Implement phase may begin.
- [ ] Step 2B independent conformance review (post-implementation) — not started.

---

## 27. Final Readiness Assessment

**Step 2A is done and accepted.** Its implementation (commit `dcf9b58`)
independently passed its own conformance review with an **ACCEPTED**
disposition. **§10's write-failure correction independently passed its
own re-review with an APPROVED WITH REQUIRED MINOR REVISIONS
disposition; those three revisions were applied, then the RPI Research
phase independently re-derived every repository fact this Plan depends
on and returned STEP 2B RESEARCH COMPLETE — READY FOR PLAN
FINALIZATION, with four documentation-level findings.** This revision
incorporates all four: §18's structural-boundary scope is corrected to
exactly one new exception entry per file (not three, and no entry at
all for the new `strategy_state_store` package); §10 now explicitly
documents why `OrbQualificationStore` deliberately departs from
`compliance_state_store`'s own non-containing write-failure handling;
§13 now states explicitly that none of ADR-035 §13's three named
cross-field checks apply to Step 2B's 4 fields; every stale HEAD
reference is updated to `085e7e5`. No breakout algorithm, lockout
semantic, concurrency guarantee, persistence design, or registration
prohibition was altered by this finalization pass — every one of those
was independently re-derived and confirmed unchanged during Research
(§5-§12, §14-§16 above). §21's full test suite still cannot be
*written* against real `post_range_bars` values until Step 2B's own RPI
Implement phase starts, which remains gated on an independent
implementation-readiness review of this finalized Plan.

---

## Plan disposition

**STEP 2B PLAN FINALIZED — READY FOR INDEPENDENT
IMPLEMENTATION-READINESS REVIEW.**

Next authorized action: submit this finalized Plan for its own
independent implementation-readiness review. Only after that review
authorizes it may Step 2B's own RPI Implement phase begin — its own
code, its own test suite (§21), and its own independent conformance
review, before Phase 3 may begin in turn. Implementation is not
authorized by this finalization pass.
