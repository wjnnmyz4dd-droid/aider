# Plan: ADR-036 — Legacy Strategy Retirement / ORB Consolidation

Status: Research, Plan (architecture/sequence finalized; deployment-profile
values conditional — see Plan §16)
Owner (Research phase): Software Architect
Owner (Plan phase): Software Architect
Touched components (Research phase): `titan_protocol/strategy_engine/`,
`titan_protocol/runtime/` (read-only — no file under either package, or
anywhere else, was modified by the Research phase)
Touched components (Plan phase, future Implement phase only — nothing
touched by this Plan document itself): `titan_protocol/strategy_engine/`,
`titan_protocol/runtime/validation.py`, `titan_protocol/runtime/models.py`
(if a signature changes), `deployment_windows/start.py`,
`deployment_windows/config_loader.py`,
`deployment_windows/config/titan_protocol_config.example.json`,
`tests/titan_protocol/strategy_engine/`,
`tests/titan_protocol/runtime/` — full matrix in Plan §13

---

## 0. Scope of this document

This document is the Research-phase RPI artifact for ADR-036 consolidation
and legacy-strategy retirement (`TEAM.md` §9). Per the governing task
instructions, **only Research work was performed**: no implementation, no
production/test behavior change, no strategy retirement, no registration
change, and no Plan/Implement work. Every finding below is derived from a
fresh, direct read of governing ADR text, current source, current tests,
and fresh command/script/test execution performed during this Research
pass — never from a prior report's claims taken on faith.

---

## 1. Governance basis for ADR-036

**Finding: ADR-036 already exists.** `docs/adr/ADR-036-orb-strategy-consolidation.md`
is present in the repository (620 lines) and its header states
**Status: Accepted**. This is not assumed from ADR-035's completion — it
was verified by directly opening and reading the file in full.

Critically, ADR-036's own text draws a sharp distinction between two
separate authorizations, and this Research treats that distinction as
authoritative:

- **What Acceptance authorizes today (§16, verbatim):** *"Acceptance of
  this ADR authorizes the product-direction decision only. It does not
  authorize beginning the Implementation Roadmap (§15) — step 1 of that
  roadmap (ADR-035 Phases 1–6) must independently reach
  Accepted-and-implemented status first, and each subsequent step remains
  gated by this project's normal RPI governance regardless of this ADR's
  own status."*
- **The Decision itself (§7, verbatim):** *"Titan will retire all five
  current production strategies (`LIQUIDITY_SWEEP_MSS`, `BOS_FVG`,
  `TREND_CONTINUATION`, `SESSION_BREAKOUT`, `RANGE_REVERSAL`) and register
  ORB (`OPENING_RANGE_BREAKOUT`) as the sole production strategy, once ORB
  itself is implemented and validated per ADR-035's own remaining
  phases."*

So ADR-036 is a **product-direction decision, already Accepted**, whose
own **Implementation Roadmap (§15)** remains ungated only insofar as its
individual steps each separately clear this repository's standing RPI
workflow. This Research does not re-litigate §7's decision (full
retirement, ORB as sole strategy, not partial coexistence — see §4
below) — that question is already settled by governing text, not left
open by it.

**Precondition-satisfaction check (§13's governance gate, quoted
verbatim):** *"legacy strategy retirement (§7, §11, §13, §15) must not
begin until the ORB strategy required by ADR-035 is implemented, tested,
independently reviewed, and accepted through its required phases
(ADR-035 §17 Phases 1–6)."*

This text names **"Phases 1–6"** specifically, because Phase 7 (the
formation-time news-blackout closure) did not exist when ADR-036 was
drafted. As of this Research pass:

- ADR-035 Phases 0–7 are **all** independently implemented and accepted
  (Phase 7 at implementation commit `8fc9764`, independently reviewed
  this session with disposition "PHASE 7 IMPLEMENTATION CONFORMS —
  ACCEPTED").
- Phases 1–6 specifically are therefore satisfied under either a literal
  or an intent-based reading of §13's text.
- The gate's **literal wording** is now stale documentation (it cannot
  anticipate a phase that didn't exist yet) — this is flagged as an open
  item in §13 below, not silently corrected here.

**Conclusion for this objective:** ADR-036 exists, is Accepted, and its
own stated implementation precondition (ADR-035's required phases reaching
Accepted-and-implemented status) is satisfied. This does **not** by
itself authorize any Implementation Roadmap step — each of the roadmap's
8 steps (§15) remains its own future RPI Plan/Implement/Review cycle. Most
importantly, as detailed in §12 below, **satisfying the "ORB is
implemented and tested" gate is not the same as ORB being safe to rely on
as a live replacement** — that is the single most important finding of
this Research and is surfaced as the headline adversarial risk.

---

## 2. Repository state (fresh, verified this pass)

- Branch: `claude/phantom-ea-visibility-cjjf3a`
- HEAD: `8fc9764` (`ADR-035 Phase 7: implement formation-time news-blackout
  closure (Candidate C)`)
- Upstream (`@{u}`): identical to HEAD — fully synchronized
- Working tree: clean (`git status --short` empty)

No repository artifact other than this document is created, modified, or
staged by this Research pass.

---

## 3. Current Strategy Engine reconstruction (post-ADR-035)

Reconstructed by direct, fresh reads of `titan_protocol/strategy_engine/models.py`,
`config.py`, `eligibility.py`, `selection.py`, `engine.py`,
`strategies/__init__.py`, `strategies/registry.py`, and all six concrete
strategy files, plus `titan_protocol/strategy_state_store/` and
`deployment_windows/start.py`'s wiring.

- **`StrategyId`** (`models.py`) is a **6-member enum** today:
  `LIQUIDITY_SWEEP_MSS`, `BOS_FVG`, `TREND_CONTINUATION`,
  `SESSION_BREAKOUT`, `RANGE_REVERSAL`, `OPENING_RANGE_BREAKOUT`. This
  directly contradicts ADR-036 §2/§4's own stale claim of a 5-member enum
  and "zero occurrences of `OPENING_RANGE_BREAKOUT`... anywhere under
  `titan_protocol/`" — both are historical statements true only at
  ADR-036's original drafting time, before ADR-035 Phases 1–7 existed.
- **`build_default_registry(orb_qualification_store=None,
  formation_blackout_store=None)`** (`strategies/__init__.py`) always
  registers the five legacy strategies; it registers `OrbBreakoutStrategy`
  **only when both store arguments are non-`None`**. This was verified
  both by direct source read and by a fresh, read-only in-process script
  this pass (§8 below).
- **`deployment_windows/start.py`** (line 1216) constructs both
  `OrbQualificationStore` and `FormationBlackoutStore` unconditionally at
  startup and always passes both into `build_default_registry(...)`. This
  is a materially important correction to carry forward: **ORB is
  registered in today's production registry** (6 strategies, not 5) — it
  is not "unregistered," as ADR-036's own stale §2 text and earlier
  ADR-035-phase framing describe. What keeps ORB from ever actually
  qualifying a trade in production is two independent **configuration-level
  gates**, not the absence of registration (see §7 below).
- **`selection.py`**'s cascade (`select_winning_strategy`) is a generic,
  strategy-count-agnostic 6-step narrowing (score → confidence →
  historical-ranking placeholder → portfolio-concentration placeholder →
  liquidity → news), confirmed unchanged and independently re-derived
  fresh from source this pass. It has no hardcoded assumption about which
  or how many `Strategy` instances participate.
- **`eligibility.py`**'s `check_eligibility()` is a simple membership check
  against `StrategyEngineConfig.approved_pairs_by_strategy` — also
  strategy-count-agnostic, confirmed fresh.
- **`engine.py`**'s `StrategyEngine.__init__` defaults `self.registry` to
  `build_default_registry()` (zero-arg) when no registry is explicitly
  passed, and `evaluate()`/`evaluate_batch()` iterate `self.registry.all()`
  generically — confirmed fresh, no strategy-identity coupling.

---

## 4. Interpretation of "consolidation"/"retirement" — already settled by governing text

Objective 4 asked this Research to determine plausible interpretations
without selecting one *unless* governing text settles it. It does:
ADR-036 §7 ("Decision") and §15 ("Implementation Roadmap") are explicit
and unambiguous — this is **full retirement of all five legacy strategies
and replacement by ORB as the sole production strategy**, not:

- a partial consolidation (some legacy strategies retained alongside ORB),
- a coexistence model (ORB added without removing any legacy strategy —
  this is ADR-035's own *current* state, already implemented), or
- a re-scoring/re-weighting of the existing five without registry changes.

§9 ("Non-Goals") and §18 ("Alternatives Considered") both reinforce this:
the alternative of "add ORB without retiring the legacy five" is
explicitly the *current* state ADR-036 is choosing to move on from, not a
live alternative still under consideration.

**This Research does not need an open question for "which interpretation"
— the governing ADR already answers it.** What remains genuinely open is
*when* and *under what additional preconditions* that already-decided
retirement may safely begin (§12–§13 below).

---

## 5. Legacy strategy inventory (fresh, per-strategy)

All five files were read in full this pass. Summary (full behavioral
detail feeds the overlap analysis in §6):

| Strategy | `StrategyId` | Regime | Stateful? | Gates news/holiday/market-closed directly? | Approved-pairs entry (Gate A) |
|---|---|---|---|---|---|
| `LiquiditySweepMssStrategy` | `LIQUIDITY_SWEEP_MSS` | REVERSAL | No | No — gates only on `peg_policy` | Yes |
| `BosFvgStrategy` | `BOS_FVG` | TRENDING | No | No — gates only on `peg_policy` | Yes |
| `TrendContinuationStrategy` | `TREND_CONTINUATION` | TRENDING | No | No — gates only on `peg_policy` | Yes |
| `SessionBreakoutStrategy` | `SESSION_BREAKOUT` | BREAKOUT | No | Yes — explicit news-blackout check in `qualify()` | Yes |
| `RangeReversalStrategy` | `RANGE_REVERSAL` | RANGING | No | No — gates only on `peg_policy` | Yes |
| `OrbBreakoutStrategy` (ORB) | `OPENING_RANGE_BREAKOUT` | BREAKOUT | **Yes** — two persisted stores | Yes — market_closed, holiday, news blackout (live + formation-observed), spread, liquidity | **No** (absent from `DEFAULT_APPROVED_PAIRS_BY_STRATEGY`) |

Every strategy uses only the shared `Strategy` interface
(`qualify(pair, evidence, market_intelligence, config) -> QualificationResult`),
`check_eligibility()`, and generic `StrategyDefinition`/`QualificationResult`
types — no strategy-specific coupling exists anywhere outside
`titan_protocol/strategy_engine/strategies/`. No legacy strategy holds any
persisted state, imports any store, or has any cross-cycle memory —
confirmed by direct read of all five files; this matters directly for the
migration/state analysis in §9.

None of the five legacy strategies references `OPENING_RANGE_BREAKOUT`,
`OrbBreakoutStrategy`, or either ORB store — confirmed by source read;
there is no existing coupling for retirement to have to unwind.

---

## 6. Behavioral-overlap analysis: ORB vs. each legacy strategy

| Dimension | ORB | LIQUIDITY_SWEEP_MSS | BOS_FVG | TREND_CONTINUATION | SESSION_BREAKOUT | RANGE_REVERSAL |
|---|---|---|---|---|---|---|
| Market regime | BREAKOUT | REVERSAL | TRENDING | TRENDING | BREAKOUT | RANGING |
| Session-anchor dependence | Yes — `opening_range_anchors` config, fixed formation windows | No | No | No | Yes — session-anchor gated, but a *different* mechanism (no fixed-width range construction) | No |
| Breakout vs. reversal logic | Breakout beyond a fixed opening range | Reversal off a stop-hunt sweep + CHOCH | N/A (continuation on existing BOS) | N/A (continuation on existing trend) | Breakout beyond session structure/trend classification | Reversal off a confluence zone |
| FVG use | Yes — optional confirmation only (score bonus), never gating | No | Yes — **required**, a matching unfilled FVG is the entry signal itself | No | No | No |
| Volatility/ATR gates | Yes — `orb_min_range_atr_ratio`, ATR-relative breakout-distance gate, expansion required | No explicit ATR gate | No explicit ATR gate | Uses `volatility_score` as a scoring input only, not a gate | Requires volatility expansion (boolean), no ATR-distance gate | No ATR gate; trend-score ceiling gate instead |
| Market Intelligence gates | market_closed, is_holiday, news blackout (live-cycle **and** formation-window-observed), spread, liquidity score | `peg_policy` only | `peg_policy` only | `peg_policy` only | market_closed / is_holiday / news blackout (direct check in `qualify()`) | `peg_policy` only |
| Range/anchor construction | Fixed-width opening range from configured anchors | None | None | None | Session structure, not a constructed range | None |
| Direction derivation | close vs. range boundary | stop-hunt sweep direction + CHOCH direction | BOS direction | swing-sequence trend classification | structure-event/trend-classification derived | confluence-zone source label / midpoint fallback |
| Scoring composition | session + MI session + volatility + FVG bonus | liquidity + structure components | structure + break-quality | trend + volatility | session + MI + volatility (per ADR-035 §0's own note, closest existing analog) | confluence-zone score + candlestick confidence |
| Lockout / persisted state | Yes — per-`(pair, range_start)` qualification lockout **and** formation-blackout observation | None | None | None | None | None |
| Confirmation-candle requirement | Yes — configurable minimum + direction-consistency check | No | No | No | No | No (candlestick pattern confirmation instead, a different mechanism) |
| Failure semantics on missing evidence | Fails closed at multiple points (`opening_ranges` empty, non-positive ATR, no post-range bars) | Fails closed if no sweep/CHOCH combination | Fails closed if no BOS+FVG combination | Fails closed if trend not directional | Fails closed if no directional fact | Fails closed if no confluence zone/candlestick |

**Assessment:** ORB shares *some* structural family resemblance with
`SESSION_BREAKOUT` (both are BREAKOUT-regime, both gate directly on
market_closed/holiday/news) and borrows *a* mechanism from `BOS_FVG` (FVG
confirmation, but score-only for ORB vs. gating for BOS_FVG). ORB shares
**no** meaningful behavior with `LIQUIDITY_SWEEP_MSS` (reversal regime,
no market/holiday/news gates at all — a materially different safety
posture), `TREND_CONTINUATION` (trend-following, no range/ATR-distance
logic), or `RANGE_REVERSAL` (mean-reversion at a confluence zone,
candlestick-pattern-driven). ADR-035 §0's own framing of
`SESSION_BREAKOUT` as ORB's "closest existing analog" is confirmed
accurate but the two remain genuinely distinct mechanisms (fixed-range
construction + ATR-relative distance + FVG + persisted lockout vs.
session-anchor + structure/trend-derived direction, no persisted state).

**No true 1:1 behavioral replacement exists for any of the five.** ORB is
a new, narrower mechanism; "consolidation" here means *narrowing the
production strategy set to one specialized strategy*, not *ORB
functionally subsuming what the five currently do*. This is consistent
with — and does not contradict — ADR-036's own already-settled decision
(§4 above): the decision is a deliberate strategic narrowing, not a claim
of behavioral equivalence.

---

## 7. ORB readiness-as-replacement analysis

ADR-035 Phases 0–7 being "implemented, tested, independently reviewed,
and accepted" (§13's gate) is a **code-completeness and correctness**
bar. It is **not** the same as ORB being **operationally live** in
production today. Verified fresh, both independently:

- **Gate A — pair eligibility:** `DEFAULT_APPROVED_PAIRS_BY_STRATEGY`
  (`strategy_engine/config.py`) has exactly 5 entries; `OPENING_RANGE_BREAKOUT`
  is absent. `check_eligibility()` therefore returns "not eligible" for
  ORB on **every** pair under production defaults — confirmed by direct
  source read and by a fresh in-process check this pass.
- **Gate B — opening-range anchors:** `EvidenceEngineConfig.opening_range_anchors`
  defaults to `()` (empty tuple), and the shipped
  `deployment_windows/config/titan_protocol_config.example.json` ships it
  as `"opening_range_anchors": []` with an explicit operator-facing note:
  *"opening_range_anchors defaults to an empty list, meaning Opening
  Range Breakout's opening-range mechanism is inert (fails closed) until
  an operator configures at least one anchor."* With no anchors
  configured, no opening range is ever formed for any pair, so
  `evidence.opening_ranges` is always empty and ORB's `qualify()` returns
  `_not_qualified(pair, "No opening range configured for this evaluation
  cycle")` on every cycle, for every pair, unconditionally.

Both gates are independent and either alone is sufficient to make ORB
permanently non-qualifying under current production defaults — **this
Research changes neither gate**, consistent with the governing
instruction not to alter either dormant default.

**Correction to carry forward from prior ADR-035-phase framing:** ORB is
**registered** in production (confirmed in §3 — `start.py` always
supplies both stores), so referring to it as "unregistered" is no longer
accurate post-Phase-7. The correct characterization is: **registered but
dormant**, dormant via Gates A and B, not via absence from the registry.

**Readiness conclusion:** ORB is code-complete, tested, and independently
accepted through Phase 7. It is **not** production-ready as a
replacement in the sense ADR-036's eventual retirement step requires,
because retiring the five legacy strategies while ORB remains
Gate-A/Gate-B-dormant would leave **zero live production strategies**.
This is the headline adversarial finding — detailed fully in §12.

---

## 8. Selection-cascade consequences under plausible registry compositions

Modeled read-only, in-process, using the real `build_default_registry()`
and a real temp-directory-backed `OrbQualificationStore`/
`FormationBlackoutStore` pair (no repository file touched):

| Composition | How constructed | Resulting registry cardinality | `StrategyId`s present |
|---|---|---|---|
| Five only (today's zero-arg path, e.g. `test_regression.py`'s default `StrategyEngine()`) | `build_default_registry()` | 5 | all except `OPENING_RANGE_BREAKOUT` |
| Five + ORB (today's actual **production** path, `start.py`) | `build_default_registry(orb_store, fb_store)` | 6 | all six |
| Partial-store wiring (hypothetical misconfiguration) | `build_default_registry(orb_store, None)` | 5 | all except `OPENING_RANGE_BREAKOUT` — ORB silently omitted, no error raised |
| ORB only (ADR-036's eventual end-state, not implemented by this Research) | would require a future `build_default_registry()` rewrite | N/A today | N/A today |

The "partial-store wiring" row is worth flagging: `build_default_registry()`
silently omits ORB if only one store is supplied, with no exception and
no log signal at that call site (`strategies/__init__.py`) — a caller
that intends to enable ORB but misconfigures one store gets a
silently-still-5-strategy registry, not a startup failure. This is
existing Phase-6/7 behavior (deliberate — "omitted by default so every
existing zero-argument caller is unaffected," per the module's own
docstring), not something this Research proposes changing, but it is
relevant to any future Plan that wires ORB-only construction, since the
same silent-omission shape could mask a misconfiguration during a
retirement rollout.

`select_winning_strategy()`'s 6-step cascade was re-confirmed fresh
(§3) to have no dependency on which or how many strategies are present —
it operates purely over whatever `QualificationResult` tuple
`StrategyEngine.evaluate()` produces. No selection-cascade code change is
implied by any registry-composition change.

---

## 9. Migration/state concerns

- **Legacy strategies:** none hold persisted state (§5) — retiring any
  or all of them requires no state migration, no persisted-file cleanup,
  and no data-shape versioning concern. Confirmed by direct read of all
  five files.
- **`OrbQualificationStore`** and **`FormationBlackoutStore`**: both are
  keyed by `(pair, range_start)` and persisted to their own JSON files
  under the deployment's state directory (`orb_qualification.json`,
  `orb_formation_blackout.json` per `start.py`'s current construction).
  Neither store's schema or lifecycle is affected by a legacy-strategy
  registration change — retiring the five legacy strategies changes
  nothing about how these two stores are constructed, read, or written.
  If a future Plan changes *how* or *whether* these stores are
  constructed (e.g., no longer conditionally gating ORB's registration on
  both being non-`None`, once ORB is the sole strategy), that is a
  registration-wiring change, not a state-migration one — no existing
  persisted-file content needs transformation.
- **No cleanup behavior is invented here.** The governing instruction was
  explicit not to invent migration/cleanup steps unless governing text
  requires them; ADR-036's own text (§13) does not require any
  persisted-state migration, and this Research found no reason to
  introduce one.

---

## 10. Test-impact inventory

Distinguishing tests that would **legitimately change** under retirement
from tests that **encode preservation requirements** (and must NOT
change merely because retirement occurs):

**Would legitimately require rewriting at retirement (confirmed fresh
this pass, not merely cited from ADR-036's own text):**

- `tests/titan_protocol/strategy_engine/test_regression.py:22` —
  `self.assertEqual(len(snapshot.all_qualifications), 5)` against the
  default zero-arg `StrategyEngine()`. Confirmed present, unchanged,
  fresh this pass.
- `tests/titan_protocol/runtime/test_configuration.py:78` — constructs a
  profile with `allowed_strategies=(StrategyId.TREND_CONTINUATION,)`.
  Confirmed fresh.
- `tests/titan_protocol/runtime/test_integration.py:77` and
  `tests/titan_protocol/runtime/test_phase_3c_ingestion_integration.py:168`
  — both assert `record.selected_strategy == StrategyId.TREND_CONTINUATION`
  after running a real five-strategy cycle end-to-end. Confirmed fresh,
  same line numbers ADR-036 §11 itself cites.
- Per-strategy test files exercising the five legacy strategies directly
  (`test_qualification.py`, `test_trade_intent.py` — each contains cases
  for all five) would need pruning to ORB-only cases in a future removal
  phase, not before.
- `test_selection.py` exercises genuine multi-candidate tie-break logic
  using multiple distinct `StrategyId` values as test fixtures (not
  necessarily the five *production* ones) — per ADR-036 §12.B, this is
  exactly why `StrategyId` member deletion is treated as a *separate*
  decision from production retirement: reducing the registry to one
  production strategy does not, by itself, remove the enum members
  `test_selection.py` needs for multi-candidate testability.

**Confirmed as encoding a preservation requirement, not a false
positive to be "fixed" at retirement:**

- `tests/titan_protocol/runtime/test_trading_profiles.py` —
  `_ALL_STRATEGY_IDS = frozenset(StrategyId)` and
  `test_every_named_profile_allows_every_strategy` assert against the
  **self-deriving** `StrategyId` enum, not against the five legacy names
  individually. Confirmed by direct read this pass: this test would
  continue to pass unchanged even after retirement, provided
  `StrategyId`'s enum membership itself is not simultaneously reduced —
  and per §12.B, whether to reduce it is a separate, later decision.
- `titan_protocol/runtime/profiles.py`'s own `_ALL_STRATEGIES =
  tuple(StrategyId)` and `_TRADEABLE_PAIR_UNIVERSE` (derived from
  `DEFAULT_APPROVED_PAIRS_BY_STRATEGY`) are both self-deriving — neither
  needs code changes at retirement, confirmed by direct read this pass.

**Fresh validation baseline (this Research pass, exact counts):**

| Suite | Command | Result |
|---|---|---|
| Compile check | `python3 -m compileall -q titan_protocol tests deployment_windows scripts` | Clean, exit 0 |
| Architecture/structural-boundary | `python3 scripts/check_architecture.py` | PASS — 17 packages, no circular imports, no cross-package private-state access, no pipeline-stage imports a cross-cutting observer package |
| Strategy Engine | `python3 -m unittest discover -s tests/titan_protocol/strategy_engine` | **180 tests, OK** (includes `test_orb_full_suite_integration.TestRegistryCardinality.test_with_store_returns_six_including_orb_exactly_once`, confirmed passing) |
| `strategy_state_store` | `python3 -m unittest discover -s tests/titan_protocol/strategy_state_store` | **39 tests, OK** (interleaved `OSError`/traceback output is intentional fault-injection test output, not failures — each is followed by `... ok`) |
| Evidence Engine | `python3 -m unittest discover -s tests/titan_protocol/evidence_engine` | **176 tests, OK** |
| Market Intelligence | `python3 -m unittest discover -s tests/titan_protocol/market_intelligence` | **90 tests, OK** |
| Runtime | `python3 -m unittest discover -s tests/titan_protocol/runtime` | **158 tests, OK** |
| `deployment_windows` | `python3 -m unittest discover -s tests/deployment_windows -t .` | **162 tests, OK** (requires `-t .` from repo root; without it, `unittest discover`'s default top-level-dir inference breaks this package's relative imports — a pre-existing test-runner invocation detail, not a defect introduced or found by this Research) |
| Full `titan_protocol` regression | `python3 -m unittest discover -s tests/titan_protocol -t .` | **1,428 tests, OK** |
| Live registry cardinality (zero-store / dual-store / partial-store) | ad hoc read-only script, §8 above | 5 / 6 / 5 respectively, confirmed empirically |

No test failure of any kind was observed. All fault-injection output
(`OSError: simulated disk failure` tracebacks in `strategy_state_store`
tests) is deliberate test behavior, distinguished from genuine failures
by each such test still reporting `ok`.

---

## 11. Architecture/scope analysis

**Smallest plausible file-impact surface for the eventual retirement
step** (per ADR-036 §8/§15, confirmed consistent with fresh source
reading):

- In scope, when retirement is eventually implemented: the five legacy
  strategy files under `titan_protocol/strategy_engine/strategies/`,
  `strategies/__init__.py` (`build_default_registry()`),
  `strategy_engine/config.py` (five per-strategy field groups +
  `DEFAULT_APPROVED_PAIRS_BY_STRATEGY`'s five entries), the per-strategy
  test files, `test_regression.py`, `test_selection.py` (per §12.B —
  handled deliberately, not blindly), and the three named Runtime test
  files (§10).
- **Must remain untouched** (confirmed by fresh reads, not merely
  asserted): Evidence Engine, Market Intelligence, Risk Engine,
  Compliance Engine, Bridge, `selection.py`, `eligibility.py`,
  `engine.py`, the `Strategy` interface/`StrategyRegistry`, and both ORB
  stores' own implementations. None of these packages holds a
  legacy-strategy-specific reference — confirmed by source read this
  pass, matching ADR-036's own §9/§10 claims independently.
- **Runtime requires no source-file change** at retirement time — both
  of its `StrategyId` couplings (`TradingProfile.allowed_strategies` via
  `profiles.py`'s `_ALL_STRATEGIES = tuple(StrategyId)`, and
  `RuntimeAuditRecord.selected_strategy`) are self-deriving from
  `StrategyId`'s own membership, confirmed by direct fresh read of
  `runtime/profiles.py` and `runtime/models.py` this pass — only
  Runtime's **tests** require rewriting (§10), not its source.
- No ADR text change, config-schema change, deployment-wiring change, or
  persisted-state-migration work is implied by legacy-strategy retirement
  alone (as opposed to the separate question of whether/when to also
  un-gate ORB's own Gate A/Gate B dormancy — §12).

---

## 12. Adversarial analysis

**Headline risk — ORB dormancy during retirement (the single most severe
risk this Research identified):**

ADR-036's governance gate (§13) is phrased as *"the ORB strategy required
by ADR-035 is implemented, tested, independently reviewed, and accepted
through its required phases."* That bar is now met. But **"implemented
and tested" is a code-completeness bar; it says nothing about whether ORB
is configured to ever qualify a trade in production.** As shown in §7,
ORB is dormant today via two independent gates (Gate A: zero eligible
pairs; Gate B: zero configured opening-range anchors). If a future
Implementation Roadmap step retired all five legacy strategies —
satisfying §13's literal gate — **while leaving Gate A and Gate B at
their current production defaults, the system would have zero
functioning production strategies.** Every `StrategyEngine.evaluate()`
call would return a rejected `StrategySnapshot` for every pair, every
cycle, indefinitely, with no error or crash — a silent, total loss of
trading capability that Runtime, Risk, and Compliance would all
faithfully report as `CycleOutcome.NO_STRATEGY` forever, never raising an
exception or an alarm distinct from "nothing qualified today."

This risk is **not explicitly gated by ADR-036's own text.** §13's
governance gate speaks only to ORB's implementation/test/review status,
never to its live-configuration status. This must be treated as a
required open question for the Plan phase (§13 below), not silently
assumed safe.

**The 13 named adversarial risk categories, addressed individually:**

1. **ORB dormant while a live strategy is retired** — see headline risk
   above; the single most severe finding.
2. **Accidental activation of ORB during this Research** — did not occur;
   this Research changed no config, no registry-construction call site,
   and no store-construction call site. Verified by `git status` showing
   a clean tree throughout, and by the read-only-script methodology used
   for §8's cardinality checks (temp-directory-backed stores, never
   touching the real deployment state directory).
3. **Accidental changes to pair eligibility or opening-range anchors** —
   did not occur; `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` and
   `opening_range_anchors` were only read, never edited, confirmed by the
   clean `git status`.
4. **Conflating the Phase 5 anchor-validation residual risk with ADR-036
   scope** — this Research does not perform, reference as authorizing, or
   fold in that separate follow-up. It is called out here only to
   confirm it was **not** touched.
5. **Silent partial-store misconfiguration** — see §8's "partial-store
   wiring" row: `build_default_registry()` silently omits ORB if only one
   store is supplied. A future ORB-only registration rewrite should not
   reproduce this silent-omission shape without an explicit decision to
   do so.
6. **`StrategyId` deletion conflated with production retirement** —
   ADR-036 §12.B already treats these as separate decisions; this
   Research reinforces that distinction (§10) and does not recommend
   deleting any enum member as part of any retirement step.
7. **Runtime silently breaking at retirement** — ruled out: both Runtime
   `StrategyId` couplings are self-deriving (§11); only Runtime's
   *tests*, not its source, need change.
8. **Config-schema drift (orphaned fields)** — a real risk **for the
   eventual removal phase** (ADR-036's own §14 risk table already names
   this: partial removal of the five per-strategy config-field groups
   would leave orphaned fields with no consuming strategy). Not a risk
   for this Research phase, since no field was touched.
9. **Test regression from hardcoded strategy counts** — confirmed
   concretely present today (`test_regression.py:22`), not merely
   asserted from ADR-036's own claim; a bounded, foreseeable, already-
   identified future update, not a surprise.
10. **Documentation drift (stale strategy-count claims)** — confirmed:
    ADR-036 §2/§4 are themselves now stale (pre-date ORB's actual
    implementation); ADR-026 and ADR-035 §0's own strategy-count language
    will also need updating whenever retirement actually completes. Not
    an in-scope fix for this Research pass.
11. **Loss of tie-break/selection diversity** — the five legacy
    strategies currently give `selection.py`'s cascade real candidates to
    narrow between; reducing to one strategy makes every one of the
    cascade's 6 steps except the first largely moot (a single qualified
    candidate wins immediately). This is an accepted, explicit consequence
    already named in ADR-036 §17 ("Consequences"), not a new risk this
    Research surfaces.
12. **Rollback complexity** — ADR-036 §13 already asserts rollback is
    deterministic (reverting the removal commit(s) restores all five
    files/entries/`StrategyId` members exactly). This Research did not
    find evidence contradicting that claim, but also performed no
    removal to test it against.
13. **Governance-gate textual staleness ("Phases 1–6" vs. "including
    Phase 7")** — confirmed present (§1); resolved functionally (Phase 7
    is also accepted) but the literal ADR text remains stale and is
    flagged as an open item (§13) rather than silently corrected here,
    since amending ADR-036's own text is itself an ADR-governance action
    outside this Research's scope.

---

## 13. Open questions for the Plan phase

These are surfaced explicitly, not silently resolved, per the governing
instruction:

1. **(Requires an ADR-level decision, not an ordinary Plan decision.)**
   Must ORB's Gate A (pair eligibility) and Gate B (opening-range
   anchors) be lifted — i.e., ORB made live, non-dormant, and observed
   qualifying real trades under real or paper-trading conditions — as an
   explicit precondition **before** any legacy-strategy retirement step
   begins? ADR-036's own text does not currently require this; the
   headline adversarial risk (§12.1) argues strongly that it should,
   since retiring the five while ORB remains dormant leaves zero live
   strategies. Two competing options exist:
   - **(a)** Require ORB to be live-configured and observed qualifying
     under production or paper-trading conditions before Roadmap step 2
     (Strategy removal) may begin — likely requiring an ADR-036
     amendment, since this is a new precondition not currently in its
     text.
   - **(b)** Treat "ORB implemented and tested" (the current gate) as
     sufficient, accepting the zero-live-strategy window as a deliberate,
     time-boxed operational risk to be managed procedurally (e.g.,
     retirement and Gate A/B un-gating land in the same deployment
     change) rather than architecturally.
   This Research recommends **(a)** but does not decide it — it is a
   capital-preservation-relevant product/governance decision, squarely
   within `CLAUDE.md`'s priority-order §1/§2, not an implementation
   detail.
2. **(Ordinary Plan decision.)** When Gate A/Gate B are eventually
   lifted (a separate, still-unauthorized action from this Research), is
   that its own dedicated RPI Plan (recommended, since it is a
   production-behavior change with real trading consequences), or bundled
   into the retirement Plan itself? ADR-036 §15's roadmap does not
   currently include a "make ORB live" step at all — it assumes ORB is
   already usable once "implemented, tested, independently reviewed, and
   accepted."
3. **(Ordinary Plan decision.)** ADR-036 §13's governance-gate text says
   "ADR-035 §17 Phases 1–6" verbatim, silently pre-dating Phase 7. Should
   a future, narrowly-scoped ADR-036 amendment update this citation to
   "Phases 1–7" (or "all of ADR-035's required phases") purely for textual
   accuracy — with no substantive effect, since Phase 7 is independently
   accepted regardless of the citation's wording?
4. **(Ordinary Plan decision.)** `test_selection.py`'s multi-candidate
   `StrategyId` test fixtures (§10, §12.B) — when the production registry
   eventually narrows to one strategy, does that test continue to
   construct synthetic multi-`StrategyId` fixtures independent of
   production registration (ADR-036 §12.B's own recommendation), or does
   its scope need to be explicitly re-justified at that time?
5. **(Ordinary Plan decision.)** Should the future ORB-only
   `build_default_registry()` rewrite (Roadmap step 3) preserve today's
   silent-omission-on-partial-store-misconfiguration shape (§12.5), or
   should that be hardened (e.g., fail loudly if construction reaches that
   call site with only one store supplied) as part of the same step?

---

## 14. Disposition

Every research objective given has been completed via fresh, direct
repository investigation: governance basis, current architecture
reconstruction, five-strategy inventory, settled interpretation of
"consolidation," behavioral-overlap analysis, retirement safety analysis,
ORB readiness analysis (including the corrected "registered but dormant"
characterization), selection-cascade modeling, migration/state analysis,
test-impact inventory, architecture/scope analysis, adversarial analysis
across all 13 named categories, and a fresh, fully green validation
baseline (compileall, architecture check, 180+39+176+90+158+162 = 825
package-level tests plus 1,428 in the full `titan_protocol` regression,
and live registry-cardinality checks).

ADR-036 exists, is Accepted, and its own stated implementation
precondition is satisfied. However, this Research surfaces one
significant, unresolved, ADR-level open question (§13.1 — whether ORB's
production dormancy must be lifted before legacy retirement may safely
begin) that ADR-036's current text does not itself settle, and that
materially affects whether the Implementation Roadmap can proceed safely
as currently gated.

**ADR-036 RESEARCH COMPLETE — ADR/GOVERNANCE DECISION REQUIRED BEFORE
PLAN FINALIZATION.**

This disposition reflects open question §13.1 specifically — not any
deficiency in ADR-036's existing text, not any implementation defect, and
not any failing validation (all validation is green). Every other open
question (§13.2–§13.5) is an ordinary Plan-level decision that can be
resolved inside the Plan phase itself once §13.1 is settled.

Standing reminders, restated:

- **No implementation has begun.** This document is Research only.
- **Research completing does not itself authorize legacy-strategy
  retirement** — ADR-036 §16 already states this explicitly for its own
  Acceptance; this Research's completion carries the same limitation.
- **The separate Phase 5 anchor hour/minute validation residual risk was
  not performed, referenced as authority, or folded into this work.**

---

## Plan

**Governance baseline for this Plan phase**: ADR-036 Accepted (product
direction, §7 full retirement, §8/§9 scope/Non-Goals, §10 preservation);
Amendment 1 Accepted (commit `1164062`) — operational-readiness
precondition, structural-readiness/dynamic-qualification distinction,
rollout-transition governance invariant. ADR-035 Phases 0–7 independently
accepted (Phase 7 at `8fc9764`). No ADR-036 implementation exists in the
repository as of this Plan. The Phase 5 anchor hour/minute validation
residual risk remains separate and untouched throughout.

This Plan is architecture/sequence/design finalization only — **no file
outside this Plan document is created, modified, or deleted by this
Plan-writing pass.**

## P1. Governing obligations, translated precisely

From ADR-036 §7 (Accepted, unreopened):

1. All five legacy strategies (`LIQUIDITY_SWEEP_MSS`, `BOS_FVG`,
   `TREND_CONTINUATION`, `SESSION_BREAKOUT`, `RANGE_REVERSAL`) must be
   retired from the production registry.
2. `OPENING_RANGE_BREAKOUT` (ORB) must become the registry's sole
   production strategy.
3. The `Strategy` interface, `StrategyRegistry`, and `selection.py`'s
   cascade are preserved unmodified.

From Amendment 1 (Accepted, unreopened):

4. Retirement's Removal/Completion phase (ADR-036 §13) and Roadmap step
   8 (§15) are not complete until: (a) `OPENING_RANGE_BREAKOUT` has ≥1
   entry in `approved_pairs_by_strategy` with ≥1 approved pair ("Gate A
   lifted"); (b) ≥1 valid `opening_range_anchors` entry is configured
   ("Gate B lifted"); (c) deployment startup validation fails closed if
   either (a) or (b) is not met whenever ORB is registered as the
   registry's sole member.
5. Conditions 4(a)–(c) establish **structural readiness only** — ORB
   being reachable and evaluable for ≥1 pair. They do not, and must not
   be implemented to, require ORB to actually qualify or trade. Dynamic
   `NOT_QUALIFIED` outcomes (holiday, market-closed, spread, liquidity,
   news blackout, insufficient range/ATR quality, no breakout, lockout,
   FVG absent) are explicitly outside this obligation and must never be
   treated as a structural-readiness failure.
6. No individual production deployment step may leave the five legacy
   strategies absent from the registry while 4(a)–(c) do not all hold —
   a governance invariant this Plan must satisfy with affirmative
   sequencing evidence (§P9 below), not mere assumption of atomicity.
7. Exact approved pairs, exact opening-range anchors, the startup-check's
   exact implementation, and rollout-sequencing mechanics are this
   Plan's own responsibility to resolve (or explicitly flag as blocked) —
   Amendment 1 explicitly deferred them here, not to a further document.

## P2. Current implementation surface (freshly reconstructed this pass)

Verified directly against source, not inferred from prior reports:

- **`StrategyId`** (`titan_protocol/strategy_engine/models.py`) — 6-member
  enum today (5 legacy + `OPENING_RANGE_BREAKOUT`).
- **`build_default_registry(orb_qualification_store=None,
  formation_blackout_store=None)`** (`strategy_engine/strategies/__init__.py`)
  — unconditionally registers the five legacy strategies; registers
  `OrbBreakoutStrategy` only when *both* store arguments are non-`None`.
  Zero-arg call → 5 strategies, no ORB.
- **`StrategyEngine.__init__`** (`strategy_engine/engine.py`) — defaults
  `self.registry` to `build_default_registry()` (zero-arg) whenever no
  explicit `registry` is passed.
- **Production entrypoints**: `deployment_windows/start.py:~1205-1217`
  constructs both ORB stores unconditionally and always calls
  `build_default_registry(orb_qualification_store,
  orb_formation_blackout_store)` — production registry today is 6
  strategies, ORB included but dormant (Gate A/B). `deployment_windows/install.py:~301`
  (`step_verify_runtime`) constructs `StrategyEngine(settings.strategy_config)`
  with **no explicit registry and no stores** — a one-shot,
  disposable construction-only smoke test inside the install wizard, not
  a live-running production path; today this yields the 5-legacy
  zero-arg registry (ORB absent, since no stores are threaded there).
- **`DEFAULT_APPROVED_PAIRS_BY_STRATEGY`** (`strategy_engine/config.py`)
  — 5-entry tuple, one per legacy `StrategyId`; `OPENING_RANGE_BREAKOUT`
  absent (Gate A). **Not exposed via `deployment_windows/config_loader.py`
  at all** — confirmed by direct grep: `config_loader.py` wires only
  `orb_*` threshold fields into `StrategyEngineConfig`, never
  `approved_pairs_by_strategy`. Changing any strategy's approved pairs
  today requires editing `strategy_engine/config.py`'s Python source and
  redeploying — there is no JSON-config knob for it.
- **`StrategyEngineConfig.approved_pairs_for(strategy_id)`**
  (`config.py:145-149`) — returns `()` both when `strategy_id` is absent
  from `approved_pairs_by_strategy` and when present with an empty pairs
  tuple.
- **`StrategyEngineConfig.__post_init__`** (`config.py:97-144`) —
  validates every `orb_*` threshold field's range; **validates nothing
  about `approved_pairs_by_strategy`'s own content** (no non-empty check,
  no per-`StrategyId` check). Gate A has no config-load-time fail-closed
  check at all today — the only existing fail-closed check for Gate-A-like
  conditions is `validate_profile()`, a Runtime-owned, `TradingProfile`-level
  check (below), not a Strategy-Engine-owned one.
- **`EvidenceEngineConfig.opening_range_anchors`**
  (`evidence_engine/config.py:78`) — `Tuple[Tuple[SessionName, int,
  int], ...]`, defaults `()` (Gate B). Session/time-of-day-keyed, **no
  pair dimension** — `compute_opening_ranges(bars, now, config)`
  (`evidence_engine/opening_range.py:128-150`) takes no `pair` argument;
  every configured anchor applies identically to whichever pair's bars
  the caller supplies. `EvidenceEngineConfig.__post_init__` already
  fail-closed validates anchors for internal well-formedness
  (`_validate_no_overlapping_anchors`, `_validate_range_duration_feasible`)
  — independent of this Plan, already exists.
- **`deployment_windows/config_loader.py`** — **does** wire
  `opening_range_anchors` from the deployment JSON config
  (`evidence_engine_section.get("opening_range_anchors", [])`,
  `config_loader.py:~418-443`) into `EvidenceEngineConfig` — Gate B is
  already a genuine, JSON-config-exposed operator knob. Gate A is not.
- **`deployment_windows/config/titan_protocol_config.example.json`** —
  ships `"opening_range_anchors": []`; its own operator-facing comment
  ("ORB itself remains unregistered until a later phase regardless") is
  now **stale** post-Phase-7 (ORB is registered, just dormant) — a
  pre-existing documentation-drift defect, not introduced by this Plan,
  flagged for cleanup in §P12.
- **`titan_protocol/runtime/validation.py::validate_profile(profile,
  strategy_config, compliance_config)`** — called, and fail-closed, only
  at `deployment_windows/start.py`'s startup (confirmed: `install.py`'s
  `step_verify_runtime` never calls it, a pre-existing, unrelated
  behavior). Its existing "Strategy eligibility" check already computes
  `tradeable_pairs` from `strategy_config.approved_pairs_for(sid)` for
  every `sid` in `profile.allowed_strategies`, and fails if any
  `profile.allowed_pairs` entry isn't covered — this **already** catches
  a post-retirement Gate-A regression (ORB with zero or missing pairs)
  with **zero code change**, since it operates on the return value of
  `approved_pairs_for()`, not on entry-presence. It has **no parameter
  and no logic today referencing `EvidenceEngineConfig` or
  `opening_range_anchors` at all** — Gate B has no equivalent existing
  check; this is the genuine, confirmed implementation gap Amendment 1's
  condition (c) requires closing.
- **`titan_protocol/runtime/profiles.py`** — `_ALL_STRATEGIES =
  tuple(StrategyId)` and `_TRADEABLE_PAIR_UNIVERSE` derived from
  `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` (self-deriving, confirmed no
  hardcoded 5-name list); every named profile factory uses these two
  derived defaults.
- **`titan_protocol/runtime/models.py`** — `TradingProfile.allowed_strategies:
  Tuple[StrategyId, ...]`, `RuntimeAuditRecord.selected_strategy:
  Optional[StrategyId]` — both generic, self-deriving.
- **`titan_protocol/runtime/engine.py`** — threads
  `selected_strategy=strategy.winning_strategy.strategy_id` at 5 call
  sites; `run_cycle_for_pair()`'s `if strategy.rejected: return
  _record(CycleOutcome.NO_STRATEGY, ...)` is exercised identically
  regardless of registry size (confirmed: empty-registry empirical test
  this session returned `rejected=True`, no exception).
- **`titan_protocol/runtime/logging_sink.py:47`** — serializes
  `record.selected_strategy.value` into JSON logs; no reader anywhere
  deserializes this back into a live `StrategyId` (confirmed by
  repo-wide search) — historical logs are inert text, not a migration
  hazard.
- **Persisted stores** — `OrbQualificationStore` and
  `FormationBlackoutStore` (`titan_protocol/strategy_state_store/`) are
  keyed by `f"{pair}|{range_start.isoformat()}"` — **no `StrategyId`
  anywhere in either store's key or value schema**, confirmed by direct
  read of both modules. Retirement of the five legacy strategies has
  **zero effect** on either store's schema, persisted files, or
  lifecycle.
- **No other `StrategyId` consumer exists** outside what ADR-036 §2
  already documents: `research_engine/models.py`'s generic
  `Optional[StrategyId]` field (harmless, confirmed by this Plan's own
  fresh repo-wide grep), and the coincidental unrelated `AttributionDimension.BOS_FVG`
  name in `research_engine/attribution.py`. Risk Engine, Compliance
  Engine, Bridge, Scanner, Market Intelligence, dashboard, and
  `health_check.py` hold zero `StrategyId` references (confirmed fresh
  this pass by repo-wide grep — no hits in `titan_protocol/strategy_state_store/`,
  `titan_protocol/dashboard/` if present, or `deployment_windows/health_check.py`).
- **Test surface** — `tests/titan_protocol/strategy_engine/`:
  `test_regression.py` (hardcodes `len(snapshot.all_qualifications) ==
  5` at line 22, plus a `TREND_CONTINUATION`-wins fixture),
  `test_selection.py` (multi-`StrategyId` tie-break fixtures, not
  necessarily the five production ones), `test_qualification.py` and
  `test_trade_intent.py` (per-strategy cases for all five),
  `test_orb_breakout_foundation.py`, `test_orb_formation_blackout.py`,
  `test_orb_full_suite_integration.py` (ORB's own dedicated suites,
  including a `TestRegistryCardinality` class already proving 5/6-member
  registry composition), `test_engine.py`, `test_architecture.py`,
  `test_boundary.py`, `test_determinism.py`, `test_explainability.py`,
  `test_performance.py`. `tests/titan_protocol/runtime/`:
  `test_configuration.py:78`, `test_integration.py:77`,
  `test_phase_3c_ingestion_integration.py:168` (all three concretely
  reference `StrategyId.TREND_CONTINUATION`, confirmed fresh),
  `test_trading_profiles.py:78` (self-deriving, confirmed false
  positive, no change needed), `test_architecture.py` (Runtime's own
  architecture suite), plus the remaining Runtime suites
  (`test_regression.py`, concurrency/recovery/stress/failover suites)
  verified to hold no `StrategyId` reference by fresh grep this pass.

## P3. Gate A disposition

**Governance requirement** (Amendment 1 condition (a)): ORB must have ≥1
approved production pair once it is the registry's sole member.

**Separated per §5 of this task's own instructions:**

- *Governance requirement*: `OPENING_RANGE_BREAKOUT` must have a
  non-empty `approved_pairs_by_strategy` entry.
- *Product/configuration decision*: **which specific pair(s)**. Searched
  for an authoritative, already-decided value: ADR-035 §13's original
  design table lists `orb_approved_pairs` with **"Recommended range:
  major pairs with reliable session-open liquidity"** — explicitly a
  *recommended range* for an operator to choose within, structurally
  identical in form to every other field's own "Recommended range"
  column (e.g. `orb_min_range_atr_ratio`'s "0.4-0.8") — **not itself a
  decision**, and never promoted to one by any subsequent Accepted text.
  No config file, code default, or ADR text anywhere in the repository
  assigns ORB a concrete production pair list. This is confirmed, not
  assumed: a real production pair list requires an actual product
  decision this Plan does not find pre-existing authority for.
- *Implementation mechanism*: `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` in
  `strategy_engine/config.py` gains an `OPENING_RANGE_BREAKOUT` entry
  (mirroring the five legacy strategies' own pattern — a private
  `_ORB_PAIRS: Tuple[str, ...]` constant, added to the tuple). Because
  `approved_pairs_by_strategy` is **not** JSON-config-exposed today
  (confirmed §P2), lifting Gate A in production requires an actual code
  change to this file plus redeploy — not merely a deployment-config
  edit. This is a deliberate, pre-existing architectural fact this Plan
  does not change (extending `config_loader.py` to expose
  `approved_pairs_by_strategy` as a JSON-overridable field is **out of
  scope** — ADR-036 §8 confines scope to the production strategy
  inventory, not to inventing a new configuration-surface capability;
  doing so would be scope creep beyond what retirement requires).
- **Disposition**: the *mechanism* (add ORB's own entry to the same
  tuple every legacy strategy already uses) is fully specified and
  requires no new decision. The *value* (exact pairs) is **not**
  established by Accepted governance and this Plan does not invent it —
  flagged as a required deployment-profile decision, §P15.

## P4. Gate B disposition

**Governance requirement** (Amendment 1 condition (b)): ≥1 valid
`opening_range_anchors` entry configured.

- *Governance requirement*: `EvidenceEngineConfig.opening_range_anchors`
  must be non-empty and pass its own existing fail-closed cross-field
  validation (already implemented, unrelated to this Plan).
- *Product/configuration decision*: **which specific session/hour/minute
  anchor(s)**. ADR-035 §13's original draft table lists
  `orb_session_anchors` with **"Recommended range: London open, New York
  open"** — again explicitly a recommended range, not a decision. No
  config file or Accepted ADR text assigns ORB a concrete production
  anchor. Same conclusion as Gate A: a real value requires an actual
  product decision this Plan does not find pre-existing authority for.
- *Implementation mechanism*: **already fully built** —
  `EvidenceEngineConfig.opening_range_anchors` is already a
  JSON-config-exposed field (`config_loader.py:~418-443`), already
  validated fail-closed for internal well-formedness at config-load
  time. Lifting Gate B in production requires **only a deployment
  configuration-value change** (editing the deployed JSON config's
  `evidence_engine.opening_range_anchors` array) — no code change to
  Evidence Engine, consistent with Amendment 1's own clarification that
  this does not conflict with ADR-036 §9's Non-Goal against modifying
  Evidence Engine's implementation.
- **Disposition**: the *mechanism* requires zero new code — populating
  an existing, already-validated, already-exposed config field. The
  *value* (exact session/hour/minute) is **not** established by Accepted
  governance and this Plan does not invent it — flagged as a required
  deployment-profile decision, §P15. (This is exclusively about anchor
  *presence*; the Phase 5 anchor hour/minute validation *correctness*
  residual risk remains untouched and separately gated, per Amendment 1's
  own explicit disclaimer.)

## P5. Structural-readiness validator design

**Exact inputs**: `validate_profile()`'s signature must gain one new
parameter — `evidence_config: EvidenceEngineConfig` — since Gate B lives
in a config object `validate_profile()` does not currently receive.
Revised signature: `validate_profile(profile: TradingProfile,
strategy_config: StrategyEngineConfig, compliance_config:
ComplianceEngineConfig, evidence_config: EvidenceEngineConfig) ->
ConfigValidationResult`. This is a **signature change**, propagating to
its sole existing call site (`deployment_windows/start.py`) and to every
test that constructs the call directly (`tests/titan_protocol/runtime/test_configuration.py`
and any other direct caller — enumerated fresh in §P12).

**Exact invariant** (new check, additive to existing ones — none
removed): *if* `StrategyId.OPENING_RANGE_BREAKOUT` is in
`profile.allowed_strategies` **and** no legacy `StrategyId` remains in
`profile.allowed_strategies` (i.e., ORB is this profile's sole permitted
strategy — the condition Amendment 1's condition (c) names), *then*:

- Gate A: `strategy_config.approved_pairs_for(StrategyId.OPENING_RANGE_BREAKOUT)`
  must be non-empty (already effectively enforced by the existing
  "Strategy eligibility" check, §P2 — no new logic needed for this half,
  only the trigger condition below determines *when* it's the binding
  constraint).
- Gate B: `evidence_config.opening_range_anchors` must be non-empty. New
  `ConfigValidationIssue("opening_range_anchors", "...")` appended if
  not — this is the one genuinely new check line.

**Trigger condition, precisely**: "ORB is this profile's sole permitted
strategy" is computed as `StrategyId.OPENING_RANGE_BREAKOUT in
profile.allowed_strategies and not any(sid in profile.allowed_strategies
for sid in _LEGACY_STRATEGY_IDS)` — a plain membership check, no new
state, no coupling to dynamic market data. **Never fires before
retirement** (today, `profile.allowed_strategies` always contains all
five legacy `StrategyId`s via `tuple(StrategyId)`'s self-derivation, so
the trigger condition is false at every startup until retirement
actually removes the legacy entries — confirmed no false-positive
risk pre-retirement).

**Interaction with existing `EvidenceEngineConfig` validation**: no
change to `EvidenceEngineConfig.__post_init__`'s own cross-field checks
(`_validate_no_overlapping_anchors`, `_validate_range_duration_feasible`)
— those already run at config construction, independent of and prior to
`validate_profile()`'s own call. `validate_profile()`'s new check only
adds "non-empty," not "well-formed" (already guaranteed by the time an
`EvidenceEngineConfig` instance exists at all).

**Dynamic-state coupling, explicitly avoided**: the invariant reads only
`profile.allowed_strategies`, `strategy_config.approved_pairs_by_strategy`,
and `evidence_config.opening_range_anchors` — no market data, no
`MarketIntelligenceSnapshot`, no `EvidenceSnapshot`, no time-of-day. It
cannot fail because ORB would currently reject due to holiday, spread,
liquidity, blackout, or no breakout — those conditions are invisible to
this check by construction.

**Exception/error type and propagation**: unchanged from existing
convention — `validate_profile()` returns a `ConfigValidationResult`
with `valid=False` and populated `issues`; `start.py` already checks
`if not validation_result.valid: ... return 2` (fail closed, process
exits, does not start trading). No new exception type; reuses
`ConfigValidationIssue`.

**`start.py` enforcement**: unchanged call site shape, only the new
`evidence_config` argument added to the existing call
(`validate_profile(profile, strategy_config, settings.compliance_config)`
→ `validate_profile(profile, strategy_config, settings.compliance_config,
settings.evidence_config)` — `settings.evidence_config` already exists
today, confirmed by `start.py`'s existing `EvidenceEngine(settings.evidence_config)`
construction a few lines below the `validate_profile()` call).

**`install.py` disposition, decided**: `install.py`'s `step_verify_runtime`
does not call `validate_profile()` today, for reasons unrelated to this
Amendment (pre-existing). This Plan decides: **do not add
`validate_profile()` to `install.py`.** Rationale — `step_verify_runtime`
is a one-shot, disposable construction-only smoke test confirming the 5
core engines and `RuntimeOrchestrator` construct without error; it is
never a live-running production path (confirmed §P2), holds no
persistent `TradingProfile`, and adding profile validation there would
require inventing a synthetic profile with no operator-facing meaning.
The live-production enforcement boundary is `start.py`, the only process
that actually runs trading cycles — sufficient per Amendment 1's own
"at minimum `start.py`" framing. This is a Plan-level decision, not
deferred further.

**Restart/rollback behavior**: because `validate_profile()` runs at
*every* `start.py` invocation (not once at a one-time migration step), a
restart after a partial or rolled-back deployment that leaves Gate A or
Gate B closed while ORB is the sole permitted strategy is caught
identically to a fresh deployment — fail-closed, every time, by
construction, with zero additional code beyond the check itself.

## P6. Retirement semantics, precisely defined

Re-reading ADR-036 §7/§11/§13/§15/§12.B: "full retirement" requires, at
minimum:

1. **Registry removal**: delete each legacy strategy's registration line
   from `build_default_registry()`.
2. **Config removal**: delete each legacy strategy's dedicated
   `StrategyEngineConfig` threshold fields and its
   `approved_pairs_by_strategy` entry (§14's own risk table: "must
   remove all five groups together, not partially").
3. **File deletion**: delete each legacy strategy's implementation module
   (`strategies/{liquidity_sweep_mss,bos_fvg,trend_continuation,session_breakout,range_reversal}.py`)
   — §14's "Dead code" risk explicitly requires deletion, not merely
   stop-registering.
4. **`StrategyId` enum membership — separate decision, governed by
   §12.B, NOT automatic**: ADR-036 §12.B is explicit and load-bearing —
   "production retirement and `StrategyId` enum deletion are separate
   decisions," grounded in `test_selection.py`'s own need for
   multi-`StrategyId` fixtures and historical-log interpretability. **This
   Plan does not delete any `StrategyId` member** — retention of the four
   legacy identifiers (unbacked by any registered `Strategy` class) is
   the default, evidence-grounded position §12.B establishes, and no new
   evidence has emerged in this Plan phase to justify deletion. If a
   future decision to delete them is made, it is explicitly its own,
   later, separately-evidenced RPI cycle per §12.B's own text — out of
   this Plan's scope.
5. **Test migration**: rewrite/prune the shared Strategy Engine tests
   (`test_regression.py`, `test_selection.py` per §12.B's constraint,
   `test_qualification.py`, `test_trade_intent.py`) and the three
   concretely-coupled Runtime tests (`test_configuration.py`,
   `test_integration.py`, `test_phase_3c_ingestion_integration.py`) —
   full detail in §P10/§P12.
6. **Documentation cleanup**: update ADR-026 §1 and ADR-035 §0's own
   stale "five strategies" language (§15 step 5) — **out of this Plan's
   implementation scope to perform now**, but tracked as a required
   Implement-phase step per the Roadmap's own sequencing.
7. **No persisted-state or serialization migration is required** —
   confirmed §P2: neither `OrbQualificationStore` nor
   `FormationBlackoutStore` references any `StrategyId`; historical JSON
   audit logs (`runtime/logging_sink.py`) are inert, never deserialized
   back into a live `StrategyId` by any repository component.

"Not registered" is explicitly **not** equivalent to "retired" per this
reading — steps 2 and 3 (config and file deletion) are both required by
§14's own risk table, not merely registry-line removal.

## P7. Post-retirement registry / `StrategyEngine` dependency-injection contract

**The load-bearing design question** (per this task's own §9): today,
`build_default_registry()`'s zero-arg path yields 5 legacy strategies
(never zero), and `StrategyEngine.__init__`'s default-substitution
(`registry if registry is not None else build_default_registry()`)
relies on that zero-arg path always being meaningful. **Once the five
legacy strategies are deleted from `build_default_registry()` (step P6.1),
the zero-arg path's only remaining candidate is ORB — and ORB's own
registration is currently conditional on two store arguments being
supplied.** An unmodified zero-arg call after retirement would silently
construct an **empty registry** (zero strategies) if nothing supplies
ORB's stores — reproducing the exact silent zero-live-strategy failure
mode Amendment 1 exists to prevent, but now via a *registry-construction*
path rather than a *config-gate* path.

**Decision**: post-retirement, `build_default_registry()`'s stores
become **mandatory, not optional**, parameters:

```
def build_default_registry(
    orb_qualification_store: OrbQualificationStore,
    formation_blackout_store: FormationBlackoutStore,
) -> StrategyRegistry:
    registry = StrategyRegistry()
    registry.register(OrbBreakoutStrategy(orb_qualification_store, formation_blackout_store))
    return registry
```

No `Optional[...] = None` defaults remain once ORB is the sole
production strategy — a caller **cannot** construct a registry without
its one dependency, by construction (a `TypeError` at call time, not a
silently-empty registry at runtime).

**`StrategyEngine.__init__`'s default-substitution — decided**: remove
the zero-arg `build_default_registry()` fallback entirely.
`StrategyEngine.__init__` requires an explicit `registry:
StrategyRegistry` argument (no default) once retirement completes —
**every** caller must construct and pass a registry explicitly. This is
a deliberate, evidence-driven divergence from today's convenience
default: the entire reason today's zero-arg convenience path is safe is
that it *always* yields 5 real, functioning strategies; once that
invariant no longer holds (a single-strategy registry whose one member
has real construction dependencies), preserving a "convenient" default
would require either (a) silently constructing zero-dependency stores at
an arbitrary location with no operator control (worse — hides state-file
placement decisions from `start.py`'s existing, deliberate
`settings.state_dir`-relative convention), or (b) keeping an
`Optional`-with-`None`-meaning-empty shape that reproduces exactly the
silent failure this Plan exists to close. Explicit dependency injection
at both production call sites is the fail-closed choice; this is a
Minimal-Change-compatible, not Minimal-Change-violating, decision, since
it removes a footgun rather than adding new abstraction.

**`install.py`'s construction-only path, resolved**: today
`StrategyEngine(settings.strategy_config)` (zero-arg registry).
Post-retirement, with no default registry available, this call **must**
be updated to construct the same two stores `start.py` constructs (or an
equivalent lightweight/ephemeral pair solely for the smoke test) and
pass an explicit registry — otherwise `step_verify_runtime` breaks
outright (a `TypeError`, caught by its own existing
`except Exception as exc: return StepReport(..., _FAILED, ...)` — fails
loud and correctly, not silently, but must still be fixed as part of
this retirement's own Implement phase, not left broken). Because this
smoke test is disposable and non-persistent, it may construct
throwaway/temp-file-backed stores identical in shape to the test suite's
own fixtures (§P10) rather than touching `settings.state_dir`.

## P8. Configuration migration

- **`approved_pairs_by_strategy`**: the five legacy entries removed;
  one new `OPENING_RANGE_BREAKOUT` entry added (exact pairs — §P15
  blocker). No `config_loader.py` change required (this field is not,
  and per §P3 remains not, JSON-exposed).
- **`opening_range_anchors`**: no schema change — already exists,
  already JSON-exposed, already validated. Only its populated *value*
  changes (exact anchors — §P15 blocker) as part of the deployment
  profile the operator supplies, not a code change.
- **Example config** (`titan_protocol_config.example.json`): its stale
  "ORB itself remains unregistered" comment must be corrected (documentation
  cleanup, §P6.6/§P12) once retirement lands; its shipped
  `"opening_range_anchors": []` should be updated to a real,
  non-empty example once §P15's blocker resolves — until then, the
  example legitimately continues to ship an inert (fails-closed)
  default, consistent with this codebase's existing "safe by default"
  convention (mirrors every other engine's own fail-closed-until-configured
  defaults).
- **Backward compatibility for old configs naming legacy `StrategyId`s**:
  no deployment JSON config field names a `StrategyId` by string
  anywhere in `config_loader.py` (confirmed by fresh grep — `strategy_engine`
  section only carries `orb_*` threshold overrides, never a
  strategy-name key) — **no backward-compatibility shim is required**,
  since no operator-facing config surface ever encoded the five legacy
  names in the first place.
- **Configs lacking new ORB readiness values**: covered entirely by
  §P5's fail-closed `validate_profile()` extension — an old or
  unmigrated deployment config that still has `opening_range_anchors: []`
  and/or no ORB `approved_pairs_by_strategy` entry will refuse to start
  post-retirement, with a clear `ConfigValidationIssue` message, not a
  silent zero-strategy runtime.
- **Operator-facing error behavior**: unchanged shape from today's
  existing `validate_profile()` failure path — `start.py` already logs
  `logger.error(...)`, prints `FAILED: trading profile validation
  failed: {validation_result.issues}`, and returns exit code 2. The new
  Gate-B issue reuses this exact, already-operator-tested path.

## P9. Implementation sequencing

**Design goal** (Amendment 1's rollout-transition governance invariant):
no individual production deployment step may leave the five legacy
strategies absent from the registry while Gate A/Gate B/fail-closed
enforcement are not all already in place.

**Chosen sequence** (validator-and-gates-first, retire-last — derived
from the dependency structure above, not preference):

1. **Extend `validate_profile()`** (§P5) — additive only; the new check
   cannot yet fire (its trigger condition requires ORB to be the *sole*
   permitted strategy, unreachable while all five legacy `StrategyId`s
   remain in `profile.allowed_strategies`). Deploy and verify: zero
   behavior change for any existing profile (proof obligation: existing
   test suite green, no new `ConfigValidationIssue` ever raised while
   legacy strategies remain registered).
2. **Populate Gate A and Gate B with real values** (contingent on §P15's
   blocker being resolved) — add ORB's `approved_pairs_by_strategy`
   entry; set the deployment's `opening_range_anchors` to the chosen
   value(s). At this point ORB is registered (already true today, per
   `start.py`'s unconditional store construction) **and** eligible
   **and** structurally capable of forming ranges — but the five legacy
   strategies are *still* registered too, so `validate_profile()`'s new
   trigger condition still does not fire (legacy `StrategyId`s still
   present in `profile.allowed_strategies`). Deploy and verify: ORB now
   genuinely competes in the live selection cascade alongside the five
   (a strict superset of today's behavior — no legacy strategy is
   removed yet); proof obligation — full regression green, ORB now
   sometimes wins the cascade under real conditions if it ever
   qualifies (dynamic, not required to be observed, but no longer
   structurally prevented).
3. **Retire the five legacy strategies** (§P6, all sub-steps: registry,
   config, files, tests) **in one coordinated change** — this is the
   step this Plan does mandate be atomic, and derives that requirement
   from evidence, not preference: step 2 already guarantees Gate A/Gate
   B are open and `validate_profile()`'s check is already live and
   already passing *before* this step begins, so by the time this step
   removes the legacy `StrategyId`s from `profile.allowed_strategies`
   (making `validate_profile()`'s new trigger condition true for the
   first time), the invariant it checks is already known-satisfied —
   there is no window in which the trigger condition is true and the
   gates are closed, because steps 1–2 already closed that window before
   step 3 exists. Proof obligation for this step specifically: full
   Strategy Engine + Runtime suites green against the new one-strategy
   registry (§P10); `git diff --stat` confined to
   `titan_protocol/strategy_engine/`, `runtime`'s three named test
   files, and docs (§13's own existing Validation-phase criterion,
   unmodified).
4. **Update `build_default_registry()`/`StrategyEngine.__init__`/`install.py`**
   (§P7) — performed as part of step 3's own coordinated change (they
   are mechanically inseparable: the zero-arg fallback's removal and the
   legacy strategies' removal are the same edit to the same function).
5. **Documentation cleanup** (§P6.6) — ADR-026/ADR-035 §0 stale-count
   language, example config's stale comment (§P8) — same coordinated
   change or an immediately-following one, per §15's own "Documentation
   cleanup" roadmap step.

**Why this order, not "retire first, activate later"**: retiring first
would create exactly the scenario Amendment 1 forbids — the five gone,
ORB still Gate-A/B-dormant, a real (even if momentary) zero-live-strategy
production window. **Why not a single atomic "everything in one commit"
transition**: steps 1–2 are independently low-risk, independently
verifiable, non-behavior-changing (step 1) or strictly-additive
(step 2) changes that de-risk step 3 by proving the invariant holds
*before* the risky, irreversible-without-history file-deletion step
runs — splitting them is not required by Amendment 1's own text, but is
the safer, smaller-diff-per-step choice consistent with Minimal Change
Engineer philosophy (CLAUDE.md §6) and this project's own established
per-phase RPI pattern (mirrors exactly how ADR-035 Phases 1–7 were each
their own gated, independently-reviewed step rather than one combined
change). Step 3 alone is where atomicity is actually required, and this
Plan derives that requirement from the dependency analysis above, not
from a default preference for atomic rollouts.

**Sequencing/rollback implications**: rollback after step 1 or 2 is
today's existing, already-described-safe rollback (§13's own "reverting
the future removal commit(s) restores all five... exactly as they exist
today"). Rollback *after* step 3 to a pre-step-3 state is identical —
restores the five legacy strategies and the old `build_default_registry()`
shape; Gate A/B remain populated (harmless — legacy strategies' own
`qualify()` methods never read `opening_range_anchors` or ORB's approved
pairs). Rollback to *between* step 2 and step 3 (Gates open, five still
present) is the safest possible rollback target, by design.

## P10. Test and proof matrix

Every required test, mapped to the exact scenario it proves:

| # | Scenario | Test location | Status |
|---|---|---|---|
| 1 | Final registry contains ORB only | New assertion in `test_engine.py` or a retirement-specific test | To be written, Implement phase |
| 2 | Every retired `StrategyId` absent from the *registry* (not the enum, per §12.B) | `test_engine.py`/`test_architecture.py` | To be written |
| 3 | Legacy strategy implementation files no longer importable | `test_architecture.py` (import-absence assertion) | To be written |
| 4 | Gate A missing (no ORB entry at all) → `validate_profile()` fails closed | New test in `tests/titan_protocol/runtime/test_configuration.py` | To be written |
| 5 | Gate A present but empty pairs tuple → fails closed | Same file, distinct case (exercises `approved_pairs_for()`'s degenerate-empty-tuple path, §P2) | To be written |
| 6 | Gate B empty → fails closed | Same file, new case using the new `evidence_config` parameter | To be written |
| 7 | Malformed anchors → fails closed via **existing** `EvidenceEngineConfig` validation (not new) | Already covered by `tests/titan_protocol/evidence_engine/test_opening_range.py`'s existing suite — verify still green, no new test required | Verify only |
| 8 | Both structural gates valid → profile passes | Same file, positive case | To be written |
| 9 | Dynamic ORB rejection (holiday/spread/blackout/no-breakout) does not fail structural readiness | `tests/titan_protocol/strategy_engine/test_orb_full_suite_integration.py` (already exercises this shape pre-retirement) — verify continues passing unmodified | Verify only |
| 10 | Zero-arg/default registry path cannot silently yield zero live strategies | `test_engine.py` — assert `StrategyEngine()` (no registry) raises `TypeError` post-retirement (no default exists) | To be written |
| 11 | `start.py` cannot launch with dormant ORB post-retirement | New `deployment_windows` test exercising `validate_profile()`'s new trigger with a post-retirement-shaped profile | To be written |
| 12 | `install.py` behavior matches §P7's explicit decision | `tests/deployment_windows/` — verify `step_verify_runtime` succeeds with the updated explicit-store construction | To be written/updated |
| 13 | Stale legacy config behavior matches §P8's migration contract | Covered by test 4–6 (no separate legacy-config-shape test needed, since no config ever named legacy `StrategyId`s, §P8) | N/A — no new test |
| 14 | Rollback/restart preserves the invariant | Covered by test 11 running at every `start.py` invocation — no separate rollback-simulation test required beyond confirming the check is unconditional, not one-time | Verify only |
| 15 | ORB Phase 2–7 behavior unchanged | `test_orb_breakout_foundation.py`, `test_orb_formation_blackout.py`, `test_orb_full_suite_integration.py` — full suites must remain green, byte-for-byte unmodified assertions except registry-construction fixture threading (mirrors Phase 7's own precedent for this exact class of change) | Verify only |
| 16 | Formation-blackout/qualification stores correctly wired | Same three files above | Verify only |
| 17 | Architecture/structural-boundary suites green | `test_architecture.py` (both packages), `test_boundary.py`, `scripts/check_architecture.py` | Verify only + extend for import-absence (test 3) |
| 18 | `test_regression.py`/`test_selection.py`/`test_qualification.py`/`test_trade_intent.py` rewritten for 1-strategy registry, per §12.B | All four files | To be rewritten, Implement phase |
| 19 | `test_configuration.py`/`test_integration.py`/`test_phase_3c_ingestion_integration.py` migrated off `StrategyId.TREND_CONTINUATION` | All three files | To be rewritten |
| 20 | `test_trading_profiles.py` unchanged | Confirmed self-deriving, no edit needed | Verify only |

## P11. Preservation contract

Unchanged unless explicitly listed above as a required change:

- ORB's own qualification gates (eligibility → market_closed/holiday/news
  blackout → spread/liquidity → opening-range presence/validity →
  formation-blackout read-gate → ATR/range-quality → breakout
  detection → volatility expansion → distance/body-ratio → confirmation
  candles → FVG scoring bonus → lockout consumption) — **zero logic
  change** to `orb_breakout.py`'s `qualify()` body.
- FVG confirmation remains score-only, never gating (unchanged from
  Phase 3).
- Lockout semantics (`OrbQualificationStore.try_consume()`) — unchanged.
- Formation-time and evaluation-time blackout behavior (Phase 7,
  `FormationBlackoutStore`) — unchanged.
- Both persisted stores' schemas, key shapes, and fault-containment
  behavior — unchanged (confirmed §P2, no `StrategyId` coupling exists
  to even require preservation language beyond "don't touch").
- Evidence Engine's `compute_opening_ranges()` and all opening-range
  computation logic — unchanged; only the *value* of
  `opening_range_anchors` changes, never the code that consumes it.
- Market Intelligence, Risk Engine, Compliance Engine, Execution,
  Bridge — unchanged (confirmed zero `StrategyId` coupling, §P2).
- `selection.py`'s 6-step cascade — unchanged (already
  count/identity-agnostic).
- Runtime's cycle ordering (Evidence → Market Intelligence → Strategy →
  Risk → Compliance → Bridge) — unchanged.
- Phase 5 configuration semantics **other than** the two changes
  expressly required here (Gate A entry, Gate B value) — unchanged;
  every other `orb_*` threshold field, its default, and its
  `config_loader.py` wiring stays exactly as Phase 5 left it.
- **The Phase 5 anchor hour/minute validation residual risk remains
  entirely out of scope** — nothing in this Plan touches anchor-time
  *correctness* validation, only anchor *presence*.

## P12. File-impact matrix

| File | Disposition |
|---|---|
| `titan_protocol/strategy_engine/strategies/liquidity_sweep_mss.py` | REQUIRED DELETE |
| `titan_protocol/strategy_engine/strategies/bos_fvg.py` | REQUIRED DELETE |
| `titan_protocol/strategy_engine/strategies/trend_continuation.py` | REQUIRED DELETE |
| `titan_protocol/strategy_engine/strategies/session_breakout.py` | REQUIRED DELETE |
| `titan_protocol/strategy_engine/strategies/range_reversal.py` | REQUIRED DELETE |
| `titan_protocol/strategy_engine/strategies/orb_breakout.py` | READ ONLY / VERIFIED UNCHANGED (§P11) |
| `titan_protocol/strategy_engine/strategies/__init__.py` | REQUIRED CHANGE (§P7 — mandatory store params, drop 5 registrations) |
| `titan_protocol/strategy_engine/strategies/registry.py` | READ ONLY / VERIFIED UNCHANGED (already generic) |
| `titan_protocol/strategy_engine/strategies/base.py` | READ ONLY / VERIFIED UNCHANGED |
| `titan_protocol/strategy_engine/engine.py` | REQUIRED CHANGE (§P7 — remove zero-arg default) |
| `titan_protocol/strategy_engine/config.py` | REQUIRED CHANGE (remove 5 field groups + entries; add ORB entry + Gate A value, §P15) |
| `titan_protocol/strategy_engine/eligibility.py` | READ ONLY / VERIFIED UNCHANGED (already generic) |
| `titan_protocol/strategy_engine/selection.py` | READ ONLY / VERIFIED UNCHANGED |
| `titan_protocol/strategy_engine/models.py` (`StrategyId`) | READ ONLY / VERIFIED UNCHANGED — no member deleted, §12.B |
| `titan_protocol/strategy_state_store/*.py` | READ ONLY / VERIFIED UNCHANGED (§P2 — no `StrategyId` coupling) |
| `titan_protocol/evidence_engine/config.py` | READ ONLY / VERIFIED UNCHANGED (only the deployed *value* changes, not code) |
| `titan_protocol/evidence_engine/opening_range.py` | READ ONLY / VERIFIED UNCHANGED |
| `titan_protocol/runtime/validation.py` | REQUIRED CHANGE (§P5 — new `evidence_config` param + Gate B check) |
| `titan_protocol/runtime/models.py` | READ ONLY / VERIFIED UNCHANGED (no field shape changes) |
| `titan_protocol/runtime/profiles.py` | READ ONLY / VERIFIED UNCHANGED (self-deriving) |
| `titan_protocol/runtime/engine.py` | READ ONLY / VERIFIED UNCHANGED |
| `titan_protocol/runtime/logging_sink.py` | READ ONLY / VERIFIED UNCHANGED |
| `deployment_windows/start.py` | REQUIRED CHANGE (thread new `evidence_config` arg into `validate_profile()` call; §P7 registry construction unaffected in shape, still explicit) |
| `deployment_windows/install.py` | REQUIRED CHANGE (§P7 — explicit store construction for `step_verify_runtime`) |
| `deployment_windows/config_loader.py` | READ ONLY / VERIFIED UNCHANGED (no new field exposed, §P3) |
| `deployment_windows/config/titan_protocol_config.example.json` | REQUIRED CHANGE (stale comment fix, §P8; anchor value update contingent on §P15) |
| `tests/titan_protocol/strategy_engine/test_regression.py` | TEST CHANGE (rewrite for 1-strategy registry) |
| `tests/titan_protocol/strategy_engine/test_selection.py` | TEST CHANGE (per §12.B — synthetic multi-`StrategyId` fixtures, not production-registry-derived) |
| `tests/titan_protocol/strategy_engine/test_qualification.py` | TEST CHANGE (prune to ORB-only) |
| `tests/titan_protocol/strategy_engine/test_trade_intent.py` | TEST CHANGE (prune to ORB-only) |
| `tests/titan_protocol/strategy_engine/test_engine.py` | TEST CHANGE (new zero-arg-raises test, registry-composition assertions) |
| `tests/titan_protocol/strategy_engine/test_architecture.py` | TEST CHANGE (import-absence assertions) |
| `tests/titan_protocol/strategy_engine/test_boundary.py` | READ ONLY / VERIFIED UNCHANGED unless it references a legacy file directly (verify at Implement time) |
| `tests/titan_protocol/strategy_engine/test_orb_breakout_foundation.py` | TEST CHANGE (mechanical fixture threading only, mirrors Phase 7 precedent — no assertion content change) |
| `tests/titan_protocol/strategy_engine/test_orb_formation_blackout.py` | READ ONLY / VERIFIED UNCHANGED |
| `tests/titan_protocol/strategy_engine/test_orb_full_suite_integration.py` | TEST CHANGE (mechanical fixture threading only, mirrors Phase 7 precedent) |
| `tests/titan_protocol/runtime/test_configuration.py` | TEST CHANGE (migrate off `StrategyId.TREND_CONTINUATION`; add Gate A/B test cases, §P10) |
| `tests/titan_protocol/runtime/test_integration.py` | TEST CHANGE (migrate assertion to ORB) |
| `tests/titan_protocol/runtime/test_phase_3c_ingestion_integration.py` | TEST CHANGE (migrate assertion to ORB) |
| `tests/titan_protocol/runtime/test_trading_profiles.py` | READ ONLY / VERIFIED UNCHANGED (confirmed false positive) |
| `tests/titan_protocol/runtime/test_architecture.py` | READ ONLY / VERIFIED UNCHANGED unless a legacy reference is found at Implement time |
| `tests/deployment_windows/*` | TEST CHANGE (new `step_verify_runtime` / `validate_profile` coverage, §P10 items 11-12) |
| `docs/adr/ADR-026-strategy-engine.md` | REQUIRED CHANGE (§15 step 5 — stale count language) |
| `docs/adr/ADR-035-orb-strategy.md` | REQUIRED CHANGE (§15 step 5 — stale "five registered strategies" framing) |
| `docs/adr/ADR-036-orb-strategy-consolidation.md` | OUT OF SCOPE — not modified by this Plan or its future Implement phase (governance document, not implementation) |
| Any Phase 5 anchor hour/minute validation file | OUT OF SCOPE — untouched |

No file's disposition above is left uncertain; every REQUIRED CHANGE/DELETE
is paired with an exact reason traceable to §P1's obligations.

## P13. Validation plan (commands for the future Implement phase)

- `python3 -m compileall -q titan_protocol tests deployment_windows scripts`
- `python3 -m unittest discover -s tests/titan_protocol/strategy_engine` — expect the new, smaller total (five legacy suites' cases pruned; ORB's own suites' counts unchanged)
- `python3 -m unittest discover -s tests/titan_protocol/runtime` — expect the three migrated files still passing, `test_trading_profiles.py` unchanged
- `python3 -m unittest discover -s tests/titan_protocol/evidence_engine` — expect unchanged count (no code change)
- `python3 -m unittest discover -s tests/titan_protocol/strategy_state_store` — expect unchanged count (no code change, §P2)
- `python3 -m unittest discover -s tests/deployment_windows -t .` — expect new/updated `install.py`/`start.py` coverage
- `python3 -m unittest discover -s tests/titan_protocol -t .` — full regression, expect green
- `python3 scripts/check_architecture.py` — expect PASS, 17 packages, 0 violations (unchanged package count — no new package introduced)
- **Live registry cardinality**: `build_default_registry(orb_store, fb_store)` must return exactly 1 member (`OPENING_RANGE_BREAKOUT`); calling it with a missing store argument must raise `TypeError`, not construct a degenerate registry.
- **Structural-readiness profile checks**: `validate_profile()` against (a) a pre-retirement-shaped profile — zero new issues; (b) a post-retirement profile with Gate A open, Gate B closed — exactly one new issue; (c) both gates open — zero issues; (d) Gate A entry present-but-empty — exactly one issue (proves the degenerate-empty-tuple path, §P2).

**Expected post-implementation deterministic invariants**: `len(tuple(StrategyId)) == 6` (unchanged, §12.B); `len(build_default_registry(orb_store, fb_store)) == 1`; `StrategyEngine()` (no args) raises `TypeError`; `git diff --stat` against the pre-retirement commit confined to the files listed REQUIRED CHANGE/DELETE/TEST CHANGE in §P12, nothing else.

## P14. Adversarial Plan review

| # | Scenario | This Plan's answer |
|---|---|---|
| 1 | All legacy strategies removed before Gate A opens | Prevented by sequencing (§P9): Gate A is opened in step 2, legacy removal is step 3 — step 3 cannot execute before step 2 in this Plan's own required order |
| 2 | All legacy strategies removed before Gate B opens | Same — step 2 opens both gates together before step 3 |
| 3 | Both gates open but startup check missing | Prevented: step 1 (validator extension) precedes step 2/3 in sequencing |
| 4 | Startup check exists but `start.py` bypasses it | `start.py`'s existing `if not validation_result.valid: return 2` is unchanged control flow — only the call's argument list changes (§P5); no new bypass path introduced |
| 5 | `install.py` silently constructs zero-strategy engine | Prevented by §P7's decision — `install.py` updated to construct explicit stores; if not updated, `StrategyEngine()`'s missing-registry `TypeError` (§P7) fails loud, not silently |
| 6 | `StrategyEngine` default constructor silently becomes zero-strategy | Prevented by §P7 — no default constructor path remains once retirement completes |
| 7 | Stale config names deleted `StrategyId`s | No `StrategyId` is deleted (§12.B); no config field ever named one by string (§P8) — not applicable |
| 8 | Stale persisted artifacts reference deleted `StrategyId`s | No `StrategyId` deleted; persisted stores hold none anyway (§P2) — not applicable |
| 9 | Example config remains dormant | Acceptable and intentional until §P15's blocker resolves — "fails closed by default" is this codebase's own established convention, not a defect |
| 10 | Test-only ORB pair/anchor accidentally becomes production policy | Guarded against explicitly: §P3/§P4 both state this Plan does not invent production values; §P15 flags the blocker rather than silently defaulting to test fixture values |
| 11 | Malformed anchor config | Already fail-closed by pre-existing, unmodified `EvidenceEngineConfig.__post_init__` validation (§P2/§P10 item 7) |
| 12 | Valid structural config but ORB dynamically rejects | Explicitly not a failure per §P1.5/§P11 — structural readiness ≠ trading |
| 13 | Rollback restores dormant config after retirement | Caught at next `start.py` invocation by the now-unconditional validator (§P5/§P9) |
| 14 | Restart bypasses readiness | Cannot — the check runs at every `start.py` startup, not once (§P5) |
| 15 | Legacy module/import survives retirement | Prevented by §P6.3's explicit file-deletion requirement (not merely registry-line removal) and `test_architecture.py`'s new import-absence assertion (§P10 item 3) |
| 16 | Registry has ORB plus a forgotten legacy strategy | Prevented mechanically — `build_default_registry()`'s post-retirement body (§P7) contains only the ORB registration line; no legacy `register()` call can silently remain since the whole function body is rewritten in step 3's single coordinated change |
| 17 | Phase 2–7 ORB behavior changes unintentionally | Guarded by §P11's explicit preservation contract and §P10 items 15-16's byte-for-byte-assertion requirement (mirrors Phase 7's own precedent) |
| 18 | Phase 5 anchor-validation follow-up leaks into scope | Explicitly excluded throughout (§P1.7, §P4, §P11, §P12) — never referenced as authority, never touched |

No unresolved adversarial finding beyond the two already-tracked blockers
(§P15).

## P15. Plan-finalization determination

Per this task's own explicit instruction not to invent production
values: **exact ORB-approved production pairs (Gate A) and exact
production opening-range anchors (Gate B) are not established by
Accepted governance (ADR-035/ADR-036/Amendment 1) or any other
authoritative repository source.** ADR-035 §13's own draft table
labels both as "Recommended range" — operator guidance for a future
choice, not itself a decision, structurally identical to every other
threshold field's own non-binding "Recommended range" column. No
config file, code default, or Accepted ADR text assigns either a
concrete production value anywhere in the repository (confirmed by
direct, fresh source inspection this Plan phase, §P3/§P4).

Every other element of this Plan — the retirement mechanism, the
sequencing, the structural-readiness validator's exact design, the
registry/dependency-injection contract, the test matrix, the
preservation contract, and the file-impact matrix — is fully specified
and requires no further decision; none of it depends on knowing the
specific pairs or anchors in advance (the mechanism is identical
regardless of which values eventually fill it).

**Determination: Option B.** This Plan's architecture and sequence are
fully finalized. Implementation authorization for the two
value-dependent steps (populating `approved_pairs_by_strategy`'s ORB
entry, and setting the deployment's `opening_range_anchors`) is
**conditional on a separately supplied deployment-profile decision** —
an ordinary product/operator decision (which pairs, which session
anchors), not a new ADR-level ambiguity, since ADR-036/Amendment 1
already correctly classified this as Plan/configuration-level, not
ADR-level, work (Amendment 1's own "explicitly deferred to future
Research/Plan work" list names exactly these two items). This is not
"governance decision required" (Option C) — no product-direction or
safety-contract ambiguity remains unresolved; it is a concrete,
bounded, easily-suppliable configuration input.

**What is authorized now**: independent implementation-readiness review
of this Plan's architecture, sequencing, validator design, retirement
semantics, registry contract, and test/file matrices.

**What remains blocked**: actually executing steps that populate Gate
A/Gate B with real values (Plan step 2, §P9) until an operator/product
owner supplies the specific pairs and anchors — everything else in the
sequence (steps 1, 3, 4, 5) can proceed independent of that decision,
since none of them read or depend on the specific values chosen.

---

## Plan Disposition

Architecture, sequencing, structural-readiness validator design,
retirement semantics, registry/dependency-injection contract,
configuration migration, test/proof matrix, preservation contract, and
file-impact matrix are all fully finalized and internally consistent
with Accepted ADR-036 and Accepted Amendment 1. Two production values
(ORB's approved pairs, ORB's opening-range anchors) remain outstanding
deployment-profile decisions this Plan correctly declines to invent.

**ADR-036 PLAN ARCHITECTURE FINALIZED — DEPLOYMENT-PROFILE DECISION
REQUIRED BEFORE IMPLEMENTATION AUTHORIZATION**

Standing reminders:

- No implementation has begun. This Plan document is the only artifact
  this phase produces.
- This Plan's completion does not itself authorize legacy-strategy
  retirement, ORB activation, or any production/config/test change —
  an independent implementation-readiness review of this Plan remains
  required first, per this project's standing RPI governance.
- The separate Phase 5 anchor hour/minute validation residual risk was
  not performed, referenced as authority, or folded into this Plan.
