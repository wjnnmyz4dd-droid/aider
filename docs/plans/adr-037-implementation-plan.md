# Plan — ADR-037 Implementation (Opportunity Selection Engine + Runtime Barrier)

Status: **Plan — not yet independently reviewed. No implementation
performed by this document.** Written per `.claude/commands/rpi/plan.md`
(RPI Plan phase, `TEAM.md` §9). Acting as **Software Architect** (this
change introduces a new engine/package and crosses the `runtime` /
`strategy_engine` package boundary — `.claude/commands/rpi/plan.md`'s own
routing rule).

Research this Plan builds on, without reopening: `docs/adr/ADR-037-orb-
cross-pair-session-opportunity-selection.md` (Accepted, `527e6ba`);
`docs/adr/ADR-031-runtime-orchestrator.md` Amendment 1 (Accepted, `5e6bbea`);
`docs/plans/adr-031-pipeline-amendment-research.md` (`489eb8a`); `docs/plans/
adr-037-ranking-tie-session-policy-research.md` (`1d43759`); `docs/plans/
adr-037-ranking-tie-session-policy-decision.md`, independently reviewed and
closed (`a140210`). This Plan treats every decision in those documents as
settled input, not open for renegotiation — it exists solely to translate
them into an exact, minimal, implementation-ready surface.

---

## 0. Repository baseline (re-verified fresh for this Plan)

- Branch `claude/phantom-ea-visibility-cjjf3a`, HEAD `a140210`, clean tree,
  in sync with upstream, confirmed before any source reading began.
- ADR-037: Accepted. ADR-031 Amendment 1: Accepted. Product policy: closed
  (three initial windows — London, London–New York Overlap, Early New
  York; score-alone ranking; reject-on-tie at `0.5`/`<=`).
- Gate A closed (`OPENING_RANGE_BREAKOUT` absent from `DEFAULT_APPROVED_
  PAIRS_BY_STRATEGY`), Gate B empty (`opening_range_anchors == ()`), no
  Opportunity Selection Engine implementation exists, `StrategyId` still 6
  members — all re-confirmed by direct execution immediately before this
  Plan was written.
- **Correction to this session's own prior validation habit, found while
  reconstructing the implementation surface fresh (not carried over from
  any prior report):** `scripts/check_architecture.py` targets
  `phantom_pipeline/` (the old, reference-only tree, `CLAUDE.md` §2) —
  its `PIPELINE_STAGE_PACKAGES` set names `phantom_pipeline`'s own package
  names (`data_pipeline`, `scanner`, `scoring_engine`, `execution_
  validator`, `position_manager`, etc.), not `titan_protocol`'s. Every
  "architecture check PASS" this session's prior tasks reported was
  genuine and accurate for what it checked, but it was never actually
  exercising `titan_protocol`'s own package-boundary rules. `titan_
  protocol`'s real, per-package architecture enforcement lives in each
  touched package's own `tests/titan_protocol/<package>/test_
  architecture.py` (9 exist today: `runtime`, `strategy_engine`,
  `evidence_engine`, `market_intelligence`, `risk_engine`, `compliance_
  engine`, `reliability`, `research_engine`, `validation_engine`) — this
  Plan's validation section (§9) uses these, plus a new one this Plan
  adds for the new package, not `scripts/check_architecture.py`.

## 1. Implementation architecture — package boundary and public interface

**New package: `titan_protocol/opportunity_selection_engine/`** — a
pipeline-stage-level component in the same sense as every existing engine
package (ADR-037 §4, ADR-031 Amendment 1 §2). Sits, in the Runtime-
consulted sequence, between Strategy Engine and Risk Engine, exactly as
ADR-037 §5 places it — it is a component Runtime *consults*, not a sixth
`CycleStage` Runtime itself performs (see §3 for why no new `CycleStage`
member is added).

Files (mirroring the existing per-engine convention exactly — `models.py`
+ `config.py` + a computation module + `engine.py` + `logging_sink.py` +
`metrics.py` + `__init__.py`, the same shape `evidence_engine`/`market_
intelligence`/`strategy_engine`/`risk_engine`/`compliance_engine` already
use):

- **`models.py`** — `OpportunityCandidate` (frozen dataclass: `pair: str`,
  `score: float`, `trade_intent: TradeIntent` — carried through for the
  eventual back-half command, nothing else; deliberately **not** carrying
  `confidence`, spread, or liquidity, since v1's contract consumes none of
  them, and carrying unused fields would misrepresent the selection
  contract's actual inputs); `SessionWindowIdentity` (`session_name:
  SessionName`, `range_start: datetime` — the `range_start`-alone key,
  `session_name` descriptive only, per ADR-037 §8); `SelectionOutcome`
  (`winner: Optional[str]`, `reason: str` — `"single candidate"` /
  `"tie within tolerance"` / `"no candidates"` / one winner's pair); the
  persisted-record shape `PersistedOpportunityWinnerState` (`schema_
  version: int`, `entries: Dict[str, dict]` mirroring `strategy_state_
  store`'s own `PersistedOrbQualificationState` shape) and its own
  `CorruptStateError` (a distinct exception class, not reused from `strategy_
  state_store` — cross-package exception reuse would itself be a private-
  submodule import; a three-line duplicate class is correctly tolerated
  here per `CLAUDE.md` §6).
- **`config.py`** — `OPPORTUNITY_SELECTION_ENGINE_VERSION` (string
  constant, mirroring `STRATEGY_ENGINE_VERSION` etc.); `EnabledOpportunity
  Window` (frozen dataclass: `session_name: SessionName` — descriptive
  only; `anchor_hour_utc: int`, `anchor_minute_utc: int` — the actual
  identity reference into Gate B's `opening_range_anchors`, per ADR-037
  §8's explicit "references one specific configured anchor entry, not
  merely a `SessionName` label" requirement; `enabled: bool = True`);
  `OpportunitySelectionEngineConfig` (frozen dataclass: `enabled_windows:
  Tuple[EnabledOpportunityWindow, ...] = ()` — empty by default, the
  architecturally-required degenerate case; `tie_tolerance: float = 0.5`
  — **its own field, not literally sharing `StrategyEngineConfig.score_
  tie_tolerance`**, resolving the Decision's own §4 "left to Plan"
  question: reusing a field across two unrelated engines would itself be
  a new cross-engine coupling with no independent justification, whereas
  every existing engine already owns its tuning parameters fully — this
  Plan chooses the same, established, no-new-coupling pattern, at the
  same default value `0.5` the product-policy decision specifies).
  `__post_init__` validates `0.0 <= tie_tolerance` (mirroring `Strategy
  EngineConfig`'s own validation-at-construction convention) and that no
  two `enabled_windows` entries share the same `(anchor_hour_utc, anchor_
  minute_utc)` pair (a config-internal duplicate-entry guard, distinct
  from, and in addition to, the cross-config Gate-B-reference check in
  §5 below, which needs `EvidenceEngineConfig` and therefore cannot live
  in `__post_init__` alone).
- **`selection.py`** — `select_winner(candidates: Tuple[OpportunityCandidate,
  ...], tie_tolerance: float) -> SelectionOutcome`, a pure, side-effect-
  free function (ADR-037 §6's own "pure function of the candidate-set
  input" contract). Reimplements the tiny tolerance-band comparison
  (`best = max(c.score for c in candidates)`; every candidate with `best -
  c.score <= tie_tolerance` is "tied"; a single tied candidate wins,
  more than one produces no winner, zero candidates produces no winner)
  **locally, not by importing `strategy_engine.selection._narrow_by`** —
  that function is module-private (not in `strategy_engine/selection.py`'s
  own `__all__`) and lives in a submodule (`selection`) that is not among
  the `models`/`trace`/`registry` submodules any package's own `test_
  architecture.py` treats as a legitimate cross-package surface (verified
  directly against `scripts/check_architecture.py`'s `ALLOWED_SUBMODULES`
  and every existing package's own `ALLOWED_UPSTREAM_PREFIXES` pattern,
  §9). Reusing the established *algorithm* (tolerance-band, `<=`
  inclusive) while not importing private cross-package code is the
  correct minimal-change choice — three duplicated lines, never a forbidden
  dependency.
- **`store.py`** — `OpportunityWinnerStore`, mirroring `strategy_state_
  store/store.py::OrbQualificationStore`'s exact, already-Accepted design
  precedent line-for-line: `threading.Lock`-guarded, load-once-at-
  construction `_entries: Dict[str, dict]` (never re-read from disk mid-
  process — the same property that makes `OrbQualificationStore` immune to
  "read-time" corruption/unavailability, reused here rather than inventing
  new semantics), tempfile+`fsync`+atomic-rename+`.bak`-backup persistence,
  fail-closed (raises, uncaught, propagating to deployment startup) on
  corrupt/unreadable state at construction. **One public method**,
  mirroring `try_consume()`'s "no get/set split" principle exactly:
  `decide_once(range_start: datetime, session_name: SessionName,
  candidates: Tuple[OpportunityCandidate, ...], tie_tolerance: float,
  now: datetime) -> Optional[str]`. Under the lock: if `range_start.
  isoformat()` is already a key, return the **already-persisted** pair
  value unchanged (idempotent re-evaluation never recomputes — chosen
  explicitly over "reject" per ADR-037 §9's own left-open choice, because
  recomputing against a possibly-different candidate set on a later
  re-evaluation could produce a second, different winner for the same
  key, which is strictly worse than trusting the first decision); if
  absent, call `select_winner()`, persist `{"session_name": session_name.
  value, "pair": outcome.winner, "decided_at": now.isoformat()}`, return
  `outcome.winner`. **Stale-window defense-in-depth** (ADR-037 §12): before
  computing or returning anything, if `range_start + timedelta(minutes=
  duration_minutes) < now` (the caller passes `duration_minutes` from
  `EvidenceEngineConfig.opening_range_duration_minutes`), log a distinct
  `stale_window_encountered` signal and return `None` without persisting —
  this is a should-never-happen defense (Runtime only ever presents a
  `range_start` Evidence Engine just computed as currently relevant this
  cycle) that fails closed rather than trusting or silently recomputing
  suspect input.
- **`engine.py`** — `OpportunitySelectionEngine.evaluate_window(range_start,
  session_name, candidates, now) -> SelectionOutcome`, thin composition of
  `select_winner()` (via the store's `decide_once()`, so persistence and
  selection are never called out of order) plus logging/metrics calls.
  No public method resembling a decision API beyond this one purpose-built
  call (mirrors `test_architecture.py`'s existing "no `select`/`decide`-
  named surface on the *orchestrator that consults* it" pattern — here
  inverted: this package's whole *purpose* is selection, so its forbidden-
  vocabulary test instead asserts it never gains a sizing/execution/order
  method, per §9).
- **`logging_sink.py` / `metrics.py`** — mirror every existing engine's
  shape exactly: `log_opportunity_window_result(...)` and `Opportunity
  SelectionEngineMetrics` with counters for scans, winners, ties, empty-
  candidate-sets, incomplete-scan suppressions, and selector failures —
  covering every ADR-037 §12 observability bullet this stage itself
  produces (the remaining bullets are Runtime's own, §3 below).
- **`__init__.py`** — public re-exports: `OpportunitySelectionEngine`,
  `OpportunitySelectionEngineConfig`, `EnabledOpportunityWindow`,
  `OpportunityCandidate`, `OpportunityWinnerStore`,
  `OPPORTUNITY_SELECTION_ENGINE_VERSION`.

**No duplication of existing logic:** ORB qualification (`orb_breakout.py`),
opening-range/session computation (`evidence_engine/opening_range.py`,
`session.py`), liquidity/spread filtering (`orb_breakout.py`'s own gates,
`market_intelligence/liquidity_intelligence.py`), and same-pair cross-
strategy selection (`strategy_engine/selection.py`) are none of them
touched, re-implemented, or re-derived anywhere in the new package — it
consumes only `QualificationResult`'s already-computed `score`/`pair`/
`trade_intent`/`range_start` fields.

## 2. Additive Strategy Engine model change (minimum surface)

**Add exactly one field to `QualificationResult`
(`titan_protocol/strategy_engine/models.py`):**

```python
range_start: Optional[datetime] = None
```

Defaults to `None` for every existing construction call site (all five
legacy strategies, and ORB's own `NOT_QUALIFIED`/ineligible paths) —
**zero behavioral change to any existing strategy**, mirroring `Trade
Intent`'s own Amendment 1 precedent exactly (additive, default-preserving,
only the one qualifying strategy ever sets a real value).

**One-line change to `orb_breakout.py`'s `QUALIFIED`-path constructor
call** (the single call site building the `qualified_result` around line
227): pass `range_start=opening_range.range_start` — the value `orb_
breakout.py` already computed locally (`opening_range = currently_
relevant[0]`, line 133) and already uses for its own lockout-store key
(`self._store.try_consume(pair, opening_range.range_start, ...)`).
**No new computation, no re-derivation of "which range is currently
relevant"** — this is the exact same value flowing one field further,
satisfying `CLAUDE.md` §1.4's "no duplicate filters."

**`StrategySnapshot` itself gains no new field.** `StrategySnapshot.
winning_strategy.qualification.range_start` already gives Runtime
everything ADR-037 §4/ADR-031 Amendment 1 §2 require ("Runtime reads this
value, it does not compute it") — adding a second, redundant `range_start`
field directly to `StrategySnapshot` would create two sources of truth for
the same fact the moment `winning_strategy` exists, which the minimal
correct design avoids. Runtime reads it via `strategy.winning_strategy.
qualification.range_start` (guarded by `strategy.winning_strategy is not
None`, which Runtime already checks via `strategy.rejected`).

**No change to `WinningStrategy`, `StrategyDefinition`, `TradeIntent`,
`QualificationStatus`, `selection.py`, or any of the five legacy
strategies.**

## 3. Runtime restructuring (ADR-031 Amendment 1's implementation)

**`run_cycle_for_pair()`'s public signature and behavior are unchanged for
every existing caller.** Internally, it is split into two private
methods on `RuntimeOrchestrator`:

- **`_run_front_half(pair, bars, events, ..., profile, now, cycle_id)`** —
  everything from `run_cycle_for_pair()`'s current start through the
  `strategy.rejected` check (today's lines ~205–239), returning either
  (a) a terminal `RuntimeAuditRecord` (trading-window/session-not-allowed/
  no-strategy/exception-`FAILED` — every early-exit that exists *before*
  Risk Engine today, unchanged), or (b) an internal `_FrontHalfResult`
  (module-private dataclass: `evidence`, `market_intelligence`, `strategy`,
  `evidence_id`, `stage_timings` accumulated so far) when Strategy
  produced a non-rejected result. **No behavior changes** — this is a
  pure extraction of already-existing code into a named boundary, not new
  logic.
- **`_run_back_half(front_half, portfolio_state, trade_history,
  account_state, profile, now, cycle_id)`** — everything from today's
  `last_stage = CycleStage.RISK` onward (Risk → Compliance → Bridge,
  unchanged verbatim), taking a `_FrontHalfResult` instead of re-deriving
  anything.
- **`run_cycle_for_pair()` itself becomes:** call `_run_front_half`; if it
  returned a terminal record, return it; otherwise immediately call
  `_run_back_half` with the result and return *that*. **Byte-for-byte
  identical observable behavior to today's monolithic function for every
  existing caller and test** — this is the load-bearing backward-
  compatibility guarantee that lets every existing `run_cycle_for_pair`-
  level test keep passing unmodified.

**`run_cycle()` gains the new cross-pair sequencing** (ADR-031 Amendment
1 §2–§4), replacing today's single `for pair in sorted(pairs): ...
records.append(self.run_cycle_for_pair(...))` loop with:

1. **Freeze the tracking universe once, at cycle start:** `tracked_pairs =
   set(self.strategy_engine.config.approved_pairs_for(StrategyId.
   OPENING_RANGE_BREAKOUT)) & set(profile.allowed_pairs)` — reusing
   `RuntimeOrchestrator`'s **already-held** `self.strategy_engine`
   reference; no new constructor parameter is needed. This is exactly
   ADR-037 §7 / ADR-031 Amendment 1 §2's frozen `Gate A ∩ allowed_pairs`
   tracking subset — computed once, held fixed for the cycle, **never**
   the complete set of pairs evaluated (every pair in `profile.
   allowed_pairs` still gets its front half regardless of `tracked_pairs`
   membership, exactly as today).
2. **Unchanged per-pair loop:** `for pair in sorted(pairs): if pair not
   in profile.allowed_pairs: continue` (verbatim, unchanged — this is
   also what already gives candidate-set assembly its deterministic,
   symbol-sorted order for free, satisfying ADR-031 Amendment 1 §8
   without new sorting logic). For each pair:
   - Call `_run_front_half`.
   - **If it returned a terminal record:** append to `records` exactly as
     today. If `pair in tracked_pairs`, mark it `reached_terminal = True`
     in a per-cycle `Dict[str, bool]` local (this covers `NO_STRATEGY`
     explicitly — **resolving the prior LOW finding directly**: a
     completed Strategy evaluation that rejected every candidate is a
     genuine terminal front-half outcome, per ADR-037 §5.D's own
     "whether... or a legacy strategy winning instead of ORB" being
     illustrative, not exhaustive, and per ADR-031 Amendment 1 §3's
     identical, already-Accepted text — it must never be classified
     alongside an early exit at Evidence/session-check, which does *not*
     set `reached_terminal`).
   - **If it returned a `_FrontHalfResult`:** classify using only
     already-computed fields (ADR-037 §5.B): read `strategy.winning_
     strategy` (`None` is impossible here, since `strategy.rejected`
     already routed to the terminal-record branch above) and its
     `strategy_id`/`qualification.range_start`. **Membership check
     against currently-enabled windows** — build the set of this cycle's
     enabled `range_start` values once, by matching each `Enabled
     Opportunity Window`'s `(anchor_hour_utc, anchor_minute_utc)` against
     `now`'s date (mirroring `evidence_engine/opening_range.py`'s own
     `now.replace(hour=..., minute=..., second=0, microsecond=0)`
     construction — Runtime does not re-derive "is this range currently
     relevant," it only recomputes the *label* of an enabled config
     entry into today's concrete `range_start`, a pure timestamp
     construction, not a trading decision).
     - If `winning_strategy.strategy_id is not OPENING_RANGE_BREAKOUT`,
       or its `range_start` is not one of this cycle's enabled `range_
       start` values (includes: no formed range at all, since then
       `range_start` is `None`): **non-participating.** Call `_run_back_
       half` immediately and append the result to `records` — **no
       waiting, no latency change**, exactly today's behavior. If `pair
       in tracked_pairs`, mark `reached_terminal = True` (Strategy *did*
       produce a final result this cycle — a legacy winner or a non-
       enabled-window ORB result both count, per ADR-037 §5.D/ADR-031
       Amendment 1 §3, unaltered).
     - Else (ORB won, and its `range_start` matches an enabled window):
       **barrier participant.** Mark `reached_terminal = True` (Strategy
       ran and produced a QUALIFIED result — a genuine terminal outcome).
       **Do not call `_run_back_half` yet** — append the pair's `(_Front
       HalfResult, portfolio_state, trade_history, account_state)` tuple
       to a per-cycle `Dict[datetime, List[...]]` keyed by that `range_
       start` (this is exactly the "cycle-scoped orchestration state"
       ADR-031 Amendment 1 §4 authorizes — see below for why it needs no
       new dataclass).
3. **After the per-pair loop completes** (every pair's front half has run
   exactly once — satisfying "at most once per cycle regardless of
   enabled-window count," ADR-037 §5.A/F, ADR-031 Amendment 1 §8, since
   this loop runs once total, never once per window):
   - **Completeness, computed once, cycle-wide** (ADR-037 §7, not
     per-window): `incomplete = any(pair not in reached_terminal or not
     reached_terminal[pair] for pair in tracked_pairs)`. **Because the
     same frozen `tracked_pairs`/`reached_terminal` values are reused
     for every enabled window's own check, one tracked pair's fault
     (an Evidence/session-level early exit, or a `FAILED` exception,
     before its Strategy result exists) renders *every* enabled window's
     scan incomplete that cycle — not merely the window it might have
     been relevant to.** This is not a design gap; it is the exact,
     deliberate consequence ADR-037 §5's own disclosure names ("a
     deliberate consequence of this project's capital-preservation-over-
     profit posture... this revision does not soften it") — this Plan
     states it explicitly rather than leaving it implicit, since it is a
     genuinely surprising behavior worth naming precisely for the
     eventual test matrix (§8) and independent review.
   - **For each configured, enabled `EnabledOpportunityWindow`** (iterated
     in the order `OpportunitySelectionEngineConfig.enabled_windows` lists
     them — a static, deterministic, config-declared order, not re-sorted
     by Runtime):
     - Resolve this cycle's concrete `range_start` for the window (same
       construction as step 2's membership check).
     - Gather its pending list (may be empty — a valid input, ADR-037
       §5.E.2).
     - **If `incomplete`:** no selector call is made for this window at
       all (ADR-037 §5.E.2's "never passed to the engine"). Every pending
       candidate in this window's list is terminated with the new
       `CycleOutcome.NOT_SELECTED_OPPORTUNITY_WINDOW` outcome, `reasons=
       ("opportunity window scan incomplete this cycle",)`, via the
       existing `_record()` closure (`stage_reached=CycleStage.STRATEGY`,
       `selected_strategy=OPENING_RANGE_BREAKOUT`, `trade_intent=strategy.
       trade_intent`, `evidence=`/`market_intelligence=` populated from
       its own held `_FrontHalfResult` — Risk/Compliance never invoked,
       so `risk_approved`/`compliance_decision` stay `None`). Appended to
       `records`.
     - **Else (complete):** wrap the following in a `try/except Exception`
       scoped to this one window (see below for why this is Runtime's own
       new exception boundary, not the engine's): build the `tuple` of
       `OpportunityCandidate(pair, qualification.score, qualification.
       trade_intent)` for every pending entry (order: the pending list's
       own append order, which is already the outer loop's `sorted(pairs)`
       order — no re-sorting needed, satisfying determinism "for free"),
       and call `self.opportunity_selection_engine.evaluate_window(range_
       start, window.session_name, candidates, now)`.
       - **On success with a winner:** find that pair's held pending
         tuple, call `_run_back_half` for it now (this is where Risk →
         Compliance → Bridge genuinely execute for the winner — the one
         authorized, disclosed latency change: the winner's back half
         runs strictly after every pair's front half has completed, not
         immediately after its own). Append the result to `records`.
         For **every other** pending entry in this window: terminate with
         `CycleOutcome.NOT_SELECTED_OPPORTUNITY_WINDOW`, `reasons=
         ("another candidate was selected for this opportunity window",)`.
       - **On success with no winner** (tie, or an empty candidate list):
         terminate every pending entry (if any) the same way, `reasons=
         ("no candidate selected for this opportunity window (tie or no
         qualifying candidate)",)`.
       - **On any exception** (the engine's own call, candidate
         construction, or the store's `decide_once()`): catch it here,
         log a distinct `opportunity_selection_failure` signal (ADR-037
         §12's "selector failure of any kind"), and terminate every
         pending entry with `CycleOutcome.NOT_SELECTED_OPPORTUNITY_
         WINDOW`, `reasons=("opportunity selection failed for this
         window",)` — **identical fail-closed shape to the incomplete-
         scan branch**, satisfying "never falls back to unrestricted
         per-pair ORB execution" by construction: there is no code path
         in this design that ever calls `_run_back_half` for a pending
         candidate except the single "this pair is the returned winner"
         branch above.
4. Return `CycleReport` exactly as today (unchanged shape) — `records`
   now additionally contains the new terminal-outcome records for any
   barrier participants, interleaved with the unchanged records every
   other pair already produced.

**Why no new `RuntimeContext` field and no new dataclass beyond one
private tuple:** `RuntimeContext` (`runtime/models.py`) is documented as
"one immutable record **per pair per cycle**" — a *per-pair* snapshot
passed into individual stage calls. The state this restructuring needs
(`tracked_pairs`, `reached_terminal`, the per-window pending lists) is
inherently **cycle-scoped**, spanning every pair, not pair-scoped —
structurally the same kind of thing `run_cycle()` already holds today as
a bare local (`records: List[RuntimeAuditRecord]`). This Plan adds three
more local variables of the same kind inside `run_cycle()`'s own function
body, not a new persisted or cross-call type — satisfying ADR-031
Amendment 1 §4's "authorizes the existence of this state; does not design
its data structures" by choosing the smallest structure that already
fits the existing pattern.

**Why no new `CycleStage` member:** `CycleStage`'s six members enumerate
exactly ADR-031 §3's six pipeline stages Runtime itself invokes in
sequence. The Opportunity Selection Engine is explicitly **not** one of
those six — ADR-037 §5 places it as a component Runtime *consults*
between Strategy and Risk, never as a stage Runtime performs. Adding a
seventh `CycleStage` member would misrepresent it as a stage in the same
sense the existing six are, which ADR-031's Hard Rules (Runtime generates
nothing) and ADR-037's own ownership decision (§4: the reduction is the
new engine's, never Runtime's) both argue against. `stage_reached`
remains `CycleStage.STRATEGY` for every non-winning barrier participant —
Strategy genuinely is the last of the six official stages that ran for
it, exactly matching the existing `NO_STRATEGY` outcome's own convention.

**Exactly one new `CycleOutcome` member is required, resolving ADR-031
Amendment 1 §7's deferred naming:**

```python
NOT_SELECTED_OPPORTUNITY_WINDOW = "NOT_SELECTED_OPPORTUNITY_WINDOW"
```

covering both "lost the cross-pair comparison" and "this window's scan
was incomplete/failed" — distinguished by the `reasons` tuple text, the
same established convention `RISK_REJECTED`/`COMPLIANCE_REJECTED` already
use to carry many distinct underlying reasons under one outcome value.

**ADR-031 Amendment 1 §7 item 1's "a candidate waiting at the barrier"
requires no new `CycleOutcome`/`CycleStage` member at all.** `RuntimeAudit
Record` is, by its own already-Accepted design, emitted only at a
pair's **terminal** disposition (`_record()` is called exactly once per
pair per cycle, today and after this change). A barrier participant
simply has no `RuntimeAuditRecord` yet while pending — its "waiting"
state is represented purely by its presence in the in-memory pending list
described above, which the new logging/metrics calls (§1, engine-side;
plus a Runtime-side "window scan started with N pending candidates" log
line) make observable without requiring a persisted, terminal-shaped
audit type to represent a non-terminal moment. This is a deliberate,
justified choice of "another representation" — the third option ADR-031
Amendment 1 §7 explicitly leaves open.

**New exception boundary, Runtime-side, not engine-side:** today, `run_
cycle_for_pair()` has its own per-pair `try/except` (unchanged). The new
per-window `try/except` around the `evaluate_window()` call site is a
**second, new, per-window** boundary — necessary because this operation
spans multiple pairs' already-computed results and must never let one
window's failure affect another window's independent resolution, nor
crash the whole `run_cycle()` call. This mirrors the existing per-pair
isolation principle (ADR-031 §8) at the new, coarser "per-window"
granularity ADR-037 introduces.

## 4. Candidate-set grouping and arbitrary cardinality

Because every pair's front half runs exactly once regardless of how many
windows are enabled (§3 step 2), and grouping/selection (§3 step 3)
happens once, after that single shared pass, filtering the same shared
pending state to each window's own `range_start`: **zero, one, two,
three, or any greater number of enabled windows all reuse the identical
front-half result set, with no duplicated Evidence/Market Intelligence/
Strategy Engine execution for any cardinality.** The `for window in
config.enabled_windows` loop in §3 step 3 is the only place window count
appears at all, and it is a plain iteration over whatever the config
lists — nothing sizes, names, or counts windows anywhere else in Runtime
or the new engine. Zero enabled windows means step 3's per-window loop
simply does not execute (every barrier-eligible pending entry — there
can be none, since nothing is ever added to a pending list for a window
that was never enabled to begin with, per step 2's own membership check
— never accumulates), and every pair proceeds via the *non-participating*
path unconditionally, degenerating cleanly to today's exact behavior.

## 5. Configuration and structural-readiness validation

**`validate_profile()` (`titan_protocol/runtime/validation.py`) gains two
new, optional parameters**, mirroring this codebase's own established
additive-parameter pattern (`RuntimeOrchestrator.__init__`'s own `bridge_
submit: Optional[...] = None` / `in_flight_commands: Optional[...] =
None`):

```python
def validate_profile(
    profile: TradingProfile,
    strategy_config: StrategyEngineConfig,
    compliance_config: ComplianceEngineConfig,
    evidence_config: Optional[EvidenceEngineConfig] = None,
    opportunity_selection_config: Optional[OpportunitySelectionEngineConfig] = None,
) -> ConfigValidationResult:
```

**New checks, performed only when both new parameters are supplied**
(existing callers/tests that construct `validate_profile()` with only the
first three parameters are entirely unaffected — this is exactly the
`validate_profile()` extension precedent ADR-036 Amendment 1 itself
recommends and ADR-031 Amendment 1 §1 cites, verified fresh: `validate_
profile()`'s current signature genuinely has no Gate B-aware check today
— confirmed directly against source, not assumed):

1. **Every `EnabledOpportunityWindow` entry must reference an existing
   Gate B anchor** (ADR-037 §11 item 1): its `(anchor_hour_utc, anchor_
   minute_utc)` must exactly match one `evidence_config.opening_range_
   anchors` entry's `(hour, minute)`; as a defense-in-depth consistency
   check, its declared `session_name` must also match that same anchor's
   own declared `SessionName` (catching an operator typo/drift between
   the two, rather than trusting the enabled-window's own label blindly).
2. **Every Gate B anchor not referenced by any enabled window is a
   misconfiguration whenever cross-pair selection is active** (ADR-037
   §11 item 2) — "active" defined, per this Plan's own minimal reading of
   ADR-036 Amendment 1's already-established Gate-A-width test, as
   `len(strategy_config.approved_pairs_for(StrategyId.OPENING_RANGE_
   BREAKOUT)) > 1` (the same signal ADR-036 Amendment 1 itself already
   uses to distinguish "broad" from "narrow" Gate A, reused rather than
   inventing a second one).
3. **Broad Gate A with an empty enabled-windows list is a fail-closed
   misconfiguration** (ADR-037 §11 item 3): whenever the same broad-Gate-A
   test above is true and `opportunity_selection_config.enabled_windows`
   is empty, this is exactly the "structurally-satisfiable-but-inert"
   invariant ADR-037 requires be caught, not silently tolerated.

**Structural readiness remains categorically separate from dynamic
qualification** (ADR-037 §11's own explicit preservation): these three
checks run once, at startup/config-load time, over static configuration
only — none of them inspect a live `QualificationResult`, a scan outcome,
or any per-cycle state.

**No exact Gate A pairs or Gate B anchor values are chosen by this Plan.**
`DEFAULT_APPROVED_PAIRS_BY_STRATEGY`'s ORB entry and `EvidenceEngineConfig.
opening_range_anchors`' default both remain untouched (`()` / absent) —
these three checks are dormant, never triggered, at every default/test
configuration this Plan itself introduces, exactly as Gate A/B remain
closed/empty throughout. **This is not a Plan-finalization blocker**:
ADR-037 and ADR-031 Amendment 1 were both drafted and Accepted with Gate A
closed and Gate B empty the entire time; this Plan specifies the exact
*mechanism* these checks require, fully testable against synthetic
non-production values, without needing the real production list/anchors
to exist first. Populating them is the next, separate, deployment-profile
decision (ADR-036-governed for Gate A; a dedicated future decision for
Gate B's exact clock values), unaffected by and not blocking this Plan.

**`opportunity_selection_config`'s three fields never hardcode London/
Overlap/Early New York.** The initial production *values* (three
`EnabledOpportunityWindow` entries with those specific `session_name`s and
whatever anchor hour/minute the eventual deployment-profile decision
picks) are deployment configuration content supplied at startup, the same
way `DEFAULT_APPROVED_PAIRS_BY_STRATEGY`'s ORB entry or `opening_range_
anchors` are today — never a constant inside `opportunity_selection_
engine/`, `runtime/`, or `validation.py` itself.

## 6. Persistence contract

Specified fully in §1's `store.py` description. Summary against the
task's own required dimensions:

- **Key:** `range_start` alone (`isoformat()`-encoded string), never a
  composite with `pair` or `session_name` — matches `OrbQualificationStore`/
  `FormationBlackoutStore`'s own key-encoding convention, applied to a
  different identity.
- **Value:** `{"session_name": str, "pair": Optional[str], "decided_at":
  str}` — `pair: None` is a **valid, persisted, distinct** value meaning
  "this window was decided and had no winner" (tie or empty candidate
  set), never confused with "never decided" (key absent entirely).
- **Idempotency:** re-evaluating an already-decided `range_start` returns
  the existing persisted value unchanged, never recomputes or overwrites
  — chosen and justified in §1.
- **Restart behavior:** `_entries` loads once at construction (mirroring
  the existing precedent) — a restart mid-window resumes with whatever
  was durably persisted before the restart; if nothing was persisted yet,
  the window is correctly re-decidable exactly once when it is next
  reached, since `range_start` (a full date+time) is restart-stable by
  construction (`evidence_engine/opening_range.py`'s own guarantee,
  unaltered).
- **Stale-window protection:** the defense-in-depth check in `decide_
  once()` (§1) — logs distinctly, fails closed (no winner, not persisted),
  never trusts or recomputes a `range_start` whose window should already
  be closed.
- **Corruption/unavailability:** construction-time corruption fails closed
  at startup (uncaught, mirroring `OrbQualificationStore`'s own documented
  "uncaught here" convention in `deployment_windows/start.py`); a runtime
  **persist**-write failure is caught and logged inside `decide_once()`
  exactly as `OrbQualificationStore._persist()` already does — the
  in-memory decision still stands for this process's lifetime (this is
  the established precedent's own philosophy, not a new invention); Read
  failures mid-process are structurally impossible once `_entries` is
  loaded, by the same design property `OrbQualificationStore` already
  relies on.
- **Concurrency/race semantics:** the entire read-decide-persist sequence
  inside `decide_once()` executes under one `threading.Lock`, mirroring
  `try_consume()`'s own "entire sequence executes while holding the lock —
  no caller can observe an intermediate state" guarantee — this is what
  makes "two winners persisted for the same `range_start` due to a race"
  (ADR-037 §15 row 8) structurally impossible, not merely unlikely.
- **"Winner selected" vs. "trade subsequently passed Risk/Compliance/
  Bridge" are distinct, never conflated:** the store records only the
  *selection* decision (§3's `evaluate_window()` call). Whether the
  selected pair's back half then succeeds, is `RISK_REJECTED`,
  `COMPLIANCE_REJECTED`, `BRIDGE_ERROR`, or `SUBMITTED` is recorded, as
  always, only in that pair's own `RuntimeAuditRecord` (§3) — the winner
  store is never updated again after the one `decide_once()` call for
  that `range_start`, and nothing in this Plan makes the store's
  persisted `pair` value depend on what Risk/Compliance/Bridge later
  decide.

**No-fallback contract preserved exactly** (ADR-037 §10, unaltered): if
selection fails, the scan is incomplete, persistence fails, or the
selected winner is later rejected by Risk/Compliance/Bridge, no runner-up
is ever promoted, and no code path in this Plan ever reverts to
unrestricted multi-pair ORB execution — verified structurally in §3
(there is exactly one place `_run_back_half` is ever called for a barrier
participant: the single "this pair equals the returned winner" branch).

## 7. Watchdog integration — determined from source, not carried over as an open question

**Decision: Watchdog restart-integration is not added for the Opportunity
Selection Engine, and this is not merely deferred by assertion — fresh
source evidence supports it.** `titan_protocol/runtime/watchdog_
integration.py::APPROVED_RESTART_COMPONENTS` is a static tuple of four
stateless engines; `is_approved_for_restart()`/`attempt_recovery()`
(`titan_protocol/reliability/recovery.py`) are tested, available
capabilities, but a repository-wide search found **no live call site**
wiring either into `deployment_windows/start.py`'s actual running
watchdog/monitoring loop today — the four already-approved engines
themselves are not currently auto-restarted by any live process, only
*authorized* to be if such a loop is ever built. Since the mechanism this
new engine would need to opt into is not itself exercised in production
today, there is no evidence compelling its inclusion, and adding it now
would be speculative scope, not a documented requirement. This matches,
and is now grounded rather than merely repeated from, ADR-031 Amendment 1
§5's own "no evidence compelling... left as an explicit future Plan-level
question" — this Plan answers that question with fresh evidence: **not
required now.**

## 8. File-impact matrix

| Path | Classification | Notes |
|---|---|---|
| `titan_protocol/opportunity_selection_engine/models.py` | REQUIRED ADD | §1 |
| `titan_protocol/opportunity_selection_engine/config.py` | REQUIRED ADD | §1, §5 |
| `titan_protocol/opportunity_selection_engine/selection.py` | REQUIRED ADD | §1 |
| `titan_protocol/opportunity_selection_engine/store.py` | REQUIRED ADD | §1, §6 |
| `titan_protocol/opportunity_selection_engine/engine.py` | REQUIRED ADD | §1 |
| `titan_protocol/opportunity_selection_engine/logging_sink.py` | REQUIRED ADD | §1 |
| `titan_protocol/opportunity_selection_engine/metrics.py` | REQUIRED ADD | §1 |
| `titan_protocol/opportunity_selection_engine/__init__.py` | REQUIRED ADD | §1 |
| `titan_protocol/strategy_engine/models.py` | REQUIRED CHANGE | §2 — one additive field on `QualificationResult` |
| `titan_protocol/strategy_engine/strategies/orb_breakout.py` | REQUIRED CHANGE | §2 — one line, `range_start=` passed at the existing `QUALIFIED` constructor call |
| `titan_protocol/strategy_engine/strategies/*.py` (5 legacy) | VERIFIED UNCHANGED | new field defaults `None`; no call site touched |
| `titan_protocol/strategy_engine/selection.py` | VERIFIED UNCHANGED | §1 — not imported by, not modified for, the new engine |
| `titan_protocol/strategy_engine/config.py` | VERIFIED UNCHANGED | Gate A / `score_tie_tolerance` untouched |
| `titan_protocol/runtime/engine.py` | REQUIRED CHANGE | §3 — `run_cycle_for_pair` split into `_run_front_half`/`_run_back_half` (behavior-preserving), `run_cycle` restructured |
| `titan_protocol/runtime/models.py` | REQUIRED CHANGE | §3 — one new `CycleOutcome` member; no new `CycleStage`, no `RuntimeContext` change |
| `titan_protocol/runtime/validation.py` | REQUIRED CHANGE | §5 — two new optional parameters, three new additive checks |
| `titan_protocol/runtime/watchdog_integration.py` | VERIFIED UNCHANGED | §7 |
| `titan_protocol/runtime/config.py`, `profiles.py`, `bridge_handoff.py`, `in_flight_commands.py`, `in_flight_store.py`, `logging_sink.py`, `metrics.py` | VERIFIED UNCHANGED | no dependency on this change |
| `titan_protocol/evidence_engine/*`, `titan_protocol/market_intelligence/*` | VERIFIED UNCHANGED | consumed only via already-existing, unmodified output |
| `titan_protocol/risk_engine/*`, `titan_protocol/compliance_engine/*`, `titan_protocol/bridge/*` | VERIFIED UNCHANGED | ADR-037 §10, unaltered — remain entirely downstream and unaware |
| `titan_protocol/strategy_state_store/*` | VERIFIED UNCHANGED | winner store deliberately lives in the new package, not here (§1) |
| `deployment_windows/start.py` | REQUIRED CHANGE | construct `OpportunitySelectionEngineConfig` (empty `enabled_windows` by default, matching Gate A/B's own closed/empty state), `OpportunityWinnerStore` (new `settings.state_dir / "opportunity_selection_winners.json"` file, mirroring the existing `orb_qualifications.json`/`orb_formation_blackout.json` convention exactly), `OpportunitySelectionEngine`, and pass them into `RuntimeOrchestrator`'s construction and `validate_profile()`'s call site |
| `tests/titan_protocol/opportunity_selection_engine/test_architecture.py` | REQUIRED ADD | §9 — new package's own boundary test, following the established per-package template |
| `tests/titan_protocol/opportunity_selection_engine/test_*.py` (selection, store, engine) | REQUIRED ADD | §10 |
| `tests/titan_protocol/strategy_engine/test_*.py` | REQUIRED CHANGE | additive-field tests (§10) |
| `tests/titan_protocol/runtime/test_architecture.py` | REQUIRED CHANGE | `ALLOWED_UPSTREAM_PREFIXES` gains exactly `titan_protocol.opportunity_selection_engine` — the single, disclosed consequence (ADR-031 Amendment 1 §9); no other line changes |
| `tests/titan_protocol/runtime/test_*.py` (engine, models, validation) | REQUIRED CHANGE | §10 |
| `docs/adr/ADR-036-*`, ADR-036 Amendment 1 implementation surfaces | OUT OF SCOPE | legacy-strategy retirement is not part of ADR-037 implementation; not touched |
| any of the five legacy strategy files' own logic (beyond the untouched default field) | OUT OF SCOPE | |
| `titan_protocol/reliability/*` | VERIFIED UNCHANGED | §7 |
| `docs/adr/ADR-031-runtime-orchestrator.md`, `ADR-037-*.md` | VERIFIED UNCHANGED | already Accepted; this Plan implements, does not amend |

## 9. Implementation sequence

Ordered so that no intermediate commit ever leaves selection half-wired in
a way that could permit unrestricted ORB execution — the two riskiest
transitions (splitting `run_cycle_for_pair`, and switching `run_cycle`'s
loop body) are each their own atomic step with the full existing
regression suite green before proceeding to the next:

1. **New package skeleton** (`opportunity_selection_engine/` — models,
   config, selection, store, engine, logging_sink, metrics, `__init__`)
   plus its own `test_architecture.py` and unit tests (§10, categories 1,
   9–16). Fully testable in isolation; touches nothing else. *Atomic
   unit; must be green before step 2.*
2. **Additive `QualificationResult.range_start` field** + the one-line
   `orb_breakout.py` change + its own tests (§10 category 3, plus the
   existing ORB test suite re-run to confirm zero behavioral change).
   *Atomic unit; independent of steps 1/3.*
3. **`run_cycle_for_pair` split** into `_run_front_half`/`_run_back_half`
   with **no change to `run_cycle()`'s loop yet** — `run_cycle_for_pair`
   still calls both halves back-to-back itself. Run the full existing
   Runtime suite unmodified; it must pass byte-for-byte, proving the
   split is behavior-preserving before any new sequencing is introduced.
   *This is the step most important to keep atomic and isolated from step
   4 — it must be provably a no-op before the barrier logic is added on
   top of it.*
4. **`run_cycle()` restructuring** (frozen tracking universe, per-pair
   classification, per-window grouping/selection/termination) — the new
   `CycleOutcome` member, the two new `validate_profile()` parameters and
   checks, and the full new Runtime-side test matrix (§10 categories 2,
   4–8, 17–21) land together, since they are one coherent behavioral unit
   that cannot be meaningfully tested in isolated slices.
5. **`tests/titan_protocol/runtime/test_architecture.py`'s** disclosed
   `ALLOWED_UPSTREAM_PREFIXES` addition — made in the same commit as step
   4, since step 4 is what introduces the new upstream import; never
   landed alone or ahead of the dependency that requires it.
6. **`deployment_windows/start.py` wiring** — constructs the new config
   (empty `enabled_windows`), store, and engine, and threads them through
   to `RuntimeOrchestrator` and `validate_profile()`'s call site. *Last*,
   since it depends on every prior step existing; a fresh-install/startup
   smoke test (mirroring this session's own established convention for
   deployment changes) runs after this step specifically.
7. Full-repository regression validation (§9 below), `CHANGELOG.md`
   entry, commit.

No step between 1 and 6 changes Gate A, Gate B, or any default config
value — the entire sequence is exercisable and testable with Gate A
closed and Gate B empty throughout, exactly as they remain today.

## 10. Test / proof matrix

| Requirement | Test location |
|---|---|
| One enabled window | `tests/titan_protocol/runtime/test_engine.py::TestOpportunityBarrier.test_single_enabled_window_selects_highest_score` |
| Two enabled windows | `...test_two_enabled_windows_are_fully_independent` |
| Three enabled windows (initial production cardinality) | `...test_three_enabled_windows_no_hardcoded_assumption` |
| More than three enabled windows | `...test_four_enabled_windows_generalizes_without_change` (parametrized on window count, proving no code path is count-specific) |
| Zero enabled windows | `...test_zero_enabled_windows_every_pair_takes_non_participating_path` |
| Complete scan, no candidates | `...test_complete_scan_zero_candidates_is_not_a_failure` |
| Incomplete scan (one tracked pair never reaches Strategy) | `...test_incomplete_scan_fails_every_enabled_window_closed` (also asserts *every* window is suppressed, not only the "affected" one, per §3's disclosed consequence) |
| `NO_STRATEGY` counts as terminal | `...test_no_strategy_outcome_counts_toward_completeness` (the prior LOW finding, now a regression test) |
| ORB `NOT_QUALIFIED` rejection counts as terminal | `...test_orb_rejection_counts_toward_completeness` |
| Legacy-strategy winner coexistence | `...test_legacy_winner_never_waits_at_barrier` |
| Duplicate-front-half prevention | `...test_front_half_invoked_exactly_once_per_pair_regardless_of_window_count` (asserts Evidence/MI/Strategy call counts via instrumented fakes) |
| Candidate grouping by `range_start` | `tests/titan_protocol/opportunity_selection_engine/test_engine.py::test_candidates_grouped_by_range_start_not_session_name` |
| Winner selection (clear highest score) | `tests/titan_protocol/opportunity_selection_engine/test_selection.py::test_highest_score_wins` |
| Tolerance-boundary tie (`0.5` exactly) | `...test_difference_of_exactly_0_5_is_tied` |
| Just-outside tolerance (`0.51`) | `...test_difference_of_0_51_is_not_tied` |
| Clamp-induced `100.0`/`100.0` tie | `...test_two_candidates_both_clamped_to_100_produce_no_winner` (regression test for the independent review's LOW finding — explicitly asserts **no new tiebreaker** is invoked) |
| Selector exception/timeout | `tests/titan_protocol/runtime/test_engine.py::...test_selector_exception_yields_zero_winners_for_that_window_only` |
| Store corruption at construction | `tests/titan_protocol/opportunity_selection_engine/test_store.py::test_corrupt_state_fails_closed_at_construction` |
| Store persist-failure mid-run | `...test_persist_failure_logged_in_memory_decision_still_stands` |
| Duplicate-winner race / idempotency | `...test_concurrent_decide_once_calls_never_produce_two_winners` (threaded test, mirroring `OrbQualificationStore`'s own concurrency test convention) |
| Restart | `...test_restart_resumes_from_persisted_decision` |
| Stale winner | `...test_stale_range_start_fails_closed_and_is_logged` |
| Non-winner never reaches Risk | `tests/titan_protocol/runtime/test_engine.py::...test_non_winner_stage_reached_is_strategy_never_risk` |
| Winner failing Risk/Compliance/Bridge, no runner-up | `...test_winner_rejected_by_risk_produces_no_fallback_to_runner_up` |
| Arbitrary-cardinality config | (covered by the 0/1/2/3/4-window tests above, plus) `tests/titan_protocol/opportunity_selection_engine/test_config.py::test_enabled_windows_accepts_any_length_tuple` |
| Structural-readiness failures | `tests/titan_protocol/runtime/test_validation.py::test_enabled_window_without_matching_gate_b_anchor_fails`, `test_unreferenced_gate_b_anchor_fails_when_selection_active`, `test_broad_gate_a_with_empty_enabled_windows_fails` |
| Preservation of existing Risk/Compliance/Bridge semantics | full existing `tests/titan_protocol/risk_engine/`, `compliance_engine/`, `bridge/` suites re-run unmodified (must stay green, no new test needed — proof by non-regression) |
| Architecture-test consequence | `tests/titan_protocol/runtime/test_architecture.py::test_only_permitted_upstream_packages_are_imported` (extended `ALLOWED_UPSTREAM_PREFIXES`, re-run to confirm it still passes and rejects any *other* new upstream import) |
| New package's own architecture boundary | `tests/titan_protocol/opportunity_selection_engine/test_architecture.py` (forbidden sizing/execution vocabulary; `ALLOWED_UPSTREAM_PREFIXES = ("titan_protocol.strategy_engine",)` only; no randomness/ML imports) |

## 11. Adversarial review of this Plan (performed before finalizing)

| # | Risk checked | Finding |
|---|---|---|
| 1 | Runtime accidentally owns ranking | `run_cycle()`'s new code performs only: set intersection (tracked universe), dict/list membership and grouping, one function call to the new engine, and equality checks on its returned `Optional[str]`. No score comparison, threshold, or weight appears anywhere in `runtime/engine.py` under this Plan — verified against the exact code sketch in §3. |
| 2 | Duplicate ORB/session logic | §2/§3 confirmed: Runtime constructs a `range_start` value using the *same* `now.replace(hour=..., minute=..., second=0, microsecond=0)` shape Evidence Engine already uses, only to *label* an enabled config entry for membership comparison — it never re-runs `orb_breakout.py::qualify()`'s "currently relevant range" logic, which remains the sole authority (§2's `QualificationResult.range_start` is read, never recomputed). |
| 3 | Duplicated front-half execution | §9's implementation sequence step 3 requires the split to be proven behavior-preserving (full existing suite green) *before* step 4 introduces any new sequencing — and §3's design runs the per-pair loop exactly once, never once per window, by construction. |
| 4 | Incomplete scans mistaken for zero candidates | §3 explicitly separates `incomplete` (any tracked pair missing a terminal outcome) from "complete scan, pending list happens to be empty" — two different branches, distinguishable in the test matrix (§10) and never sharing a code path. |
| 5 | Non-winners reaching Risk | §3/§6 verified structurally: exactly one call site ever invokes `_run_back_half` for a barrier participant (the winner-equality branch); every other pending entry is terminated via `_record()` directly, which never calls Risk. |
| 6 | Unrestricted fallback on any failure | §3/§6: incomplete scan and selector-failure branches produce the identical `NOT_SELECTED_OPPORTUNITY_WINDOW`/zero-winners shape — there is no third branch that releases pending candidates unrestricted. |
| 7 | Stale/cross-window winner reuse | §6: `range_start`-alone keying (Gate B's own overlap validation guarantees uniqueness) plus the stale-window defense-in-depth check in `decide_once()`. |
| 8 | Hidden three-session assumption | §4/§5: window count appears in exactly one place (`for window in config.enabled_windows`, a plain iteration); `OpportunitySelectionEngineConfig.enabled_windows` defaults to `()`; no test in §10 hardcodes "three" as anything other than one of several parametrized cardinalities tested alongside 0/1/2/4. |
| 9 | Test fixtures becoming production policy | §5/§8: `deployment_windows/start.py`'s wiring constructs an **empty** `enabled_windows` by default — the same "closed/empty until a real deployment-profile decision populates it" posture Gate A/B already have; no test fixture value is ever the default shipped in `start.py`. |
| 10 | Accidental coupling to ADR-036 retirement | §8 file-impact matrix: no ADR-036/legacy-retirement file appears in REQUIRED CHANGE or REQUIRED ADD; the five legacy strategies are explicitly VERIFIED UNCHANGED; `StrategyId`'s six members are untouched. |
| 11 (new, found during this review) | Downstream engines importing the new package | Checked: nothing in `risk_engine/`, `compliance_engine/`, or `bridge/` needs, or under this Plan gains, any import of `opportunity_selection_engine` — ADR-037 §10's "entirely unmodified, unaware" is preserved; only `runtime/` and `deployment_windows/start.py` ever reference the new package, matching the existing per-engine import direction (every engine flows into Runtime, never sideways into another engine). |
| 12 (new) | The new package's own `ALLOWED_UPSTREAM_PREFIXES` accidentally too broad | Specified in §1/§9 as exactly `("titan_protocol.strategy_engine",)` — narrower than `strategy_engine`'s own (which also needs `evidence_engine`/`market_intelligence`/`strategy_state_store`), since the new engine consumes only `QualificationResult`, nothing else. |

No finding in this table required a design change during the review — each was checked against the design already specified in §1–§9, not discovered as a defect requiring rework. This is recorded as the adversarial pass, not a post-hoc rationalization: every row states what was checked and where the design already answers it.

## 12. Validation (Plan-only — no production behavior changes; this Plan itself contains no code)

Since this is a Plan artifact, the validation below confirms the *existing* repository state remains green and that this document is the only change:

- `git status --short` — only `docs/plans/adr-037-implementation-plan.md` added.
- `python3 -m compileall -q titan_protocol tests` — clean.
- `python3 -m unittest discover -s tests/titan_protocol/runtime` — 158/158 green, unmodified (this Plan changes no code yet).
- `python3 -m unittest discover -s tests/titan_protocol/strategy_engine` — 180/180 green, unmodified.
- `python3 -m unittest tests.titan_protocol.runtime.test_architecture` — 6/6 green, unmodified (the `ALLOWED_UPSTREAM_PREFIXES` change is specified, not yet made).
- Gate A closed, Gate B empty, no Opportunity Selection Engine implementation, no legacy-strategy retirement — all re-confirmed after writing this Plan, unchanged.

## 13. Unresolved blockers

**None found for Plan finalization.** Every item this task's own
instructions forbade inventing (exact Gate A pairs, exact Gate B anchor
clock times, Watchdog inclusion decided by fiat rather than evidence,
config-ownership left vague) has been either resolved with fresh evidence
(§7's Watchdog determination; §1's config-ownership specification) or
explicitly identified as deployment-profile content this Plan's mechanism
does not require to exist yet (§5's Gate A/B values). Both are correctly
deferred, not blocking.

## 14. Explicit authorization boundaries (restated)

This Plan authorizes no implementation by itself — it is the design a
future, separately-authorized `/rpi:implement` pass would follow exactly,
after its own independent Plan review. It does not authorize: Gate A or
Gate B activation; any exact production pair, anchor, or clock value;
legacy-strategy retirement or any ADR-036 implementation sequencing;
runner-up fallback policy; the ADR-035 Phase 5 anchor hour/minute
validation follow-up (separately gated, unrelated throughout); or any
change to Risk, Compliance, or Bridge behavior (all VERIFIED UNCHANGED,
§8).

---

*This document is the Plan artifact for ADR-037 implementation. It
requires its own independent Plan review before any `/rpi:implement`
pass may begin. No implementation was performed while writing it.*
