# Plan: ADR-036 — Legacy Strategy Retirement / ORB Consolidation

Status: Research
Owner (Research phase): Software Architect
Touched components: `titan_protocol/strategy_engine/`, `titan_protocol/runtime/`
(read-only this phase — no file under either package, or anywhere else,
is modified by this Research)

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
