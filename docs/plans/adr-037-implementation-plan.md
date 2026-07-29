# Plan — ADR-037 Implementation (Opportunity Selection Engine + Runtime Barrier)

Status: **Plan — revised after independent review; awaiting independent
re-review. No implementation performed by this document.** Written per
`.claude/commands/rpi/plan.md` (RPI Plan phase, `TEAM.md` §9). Acting as
**Software Architect** (this change introduces a new engine/package and
crosses the `runtime` / `strategy_engine` package boundary —
`.claude/commands/rpi/plan.md`'s own routing rule).

**Revision history:** first finalized at commit `cac2ba0`. An independent
"ADR-037 Implementation Plan — Independent Plan Review" re-derived every
claim fresh from source (not from this Plan's own report) and found the
package boundary, additive field, persistence pattern, cardinality
handling, Watchdog determination, and file-impact matrix sound, but
identified two HIGH findings in the safety-critical Runtime completeness
mechanism and Gate-A-width heuristic, one MEDIUM-HIGH gap in audit-record
construction, and several smaller gaps. That review returned **ADR-037
IMPLEMENTATION PLAN REQUIRES REVISION**. This revision fixes every
finding: §3's completeness signal is now a single, unambiguous
`strategy_completed` boolean, never inferred from which `CycleOutcome`
value a terminal record carries; §5's structural-readiness mechanism now
uses an explicit `cross_pair_selection_enabled` flag (defaulting `False`,
inert) rather than a Gate-A-pair-count heuristic that was never actually
established precedent and could misclassify a legitimate fixed multi-pair
deployment; §3 now specifies promoting the audit-record-construction
closure into a proper instance method callable from both per-pair and
aggregate window-resolution code; §1/§6's persistence contract now states
`decide_once()`'s full signature including `duration_minutes`, sourced
from `EvidenceEngineConfig.opening_range_duration_minutes` via Runtime's
already-held `self.evidence_engine.config` reference, never invented or
recomputed. Every other section is reconciled against these fixes (§8–§11
below).

**Second revision (this document, building on `e139076`):** a subsequent
independent "ADR-037 Implementation Plan — Independent Plan Re-Review"
found one HIGH finding — the persistence design would durably persist a
"no winner" outcome (zero candidates, or an unresolved tie) starting from
a window's very first evaluated cycle, which is almost always empty
during opening-range formation (`orb_breakout.py::qualify()` returns
`NOT_QUALIFIED` until formation completes); because `range_start` is
calendar-day-stable (`evidence_engine/opening_range.py`), idempotency on
that persisted `None` would then silently prevent any later legitimate
breakout from ever being selected for the rest of that day — plus one LOW
finding (two duplicated text blocks in §5) and a sequential-re-invocation
proof-coverage observation for §10. This revision fixes the HIGH finding
by never persisting a "no winner this cycle" outcome at all (§1/§6): only
a genuine, single winning pair is ever durably written; the key remains
absent until then, so every pre-winner cycle stays freely re-computable
with no invented "window closed" boundary, while a genuine winner, once
persisted, remains permanently locked exactly as ADR-037 §9 requires. Both
duplicated §5 blocks are removed, and §10 gains six new multi-cycle
lifecycle tests including a sequential (non-concurrent) same-window
re-invocation case. See §11 row 18 and §13 for the full disposition.

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
  same default value `0.5` the product-policy decision specifies;
  **`cross_pair_selection_enabled: bool = False`** — the explicit
  selection-mode/flavor indicator ADR-037 §11 item 3 itself names as a
  candidate mechanism ("an explicit separate flavor-selection flag"),
  chosen over a Gate-A-pair-count heuristic for the reasons §5 details
  below; **defaults to `False`**, so any deployment that never touches
  this field remains entirely inert with respect to every structural-
  readiness invariant §5 adds, regardless of Gate A's actual width —
  this is the safe migration default the revision requires).
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
  that function is module-private (it is not in `strategy_engine/
  selection.py`'s own `__all__ = ["select_winning_strategy"]`), so
  importing it from another package would be an ordinary encapsulation
  violation regardless of any specific automated check (**correction from
  the independent review:** the earlier draft additionally cited
  `scripts/check_architecture.py`'s `ALLOWED_SUBMODULES` as supporting
  authority for this decision — that script targets the unrelated
  `phantom_pipeline/` tree, per §0's own correction, and is dropped as a
  citation here; it never changes the decision itself, which rests solely
  on `_narrow_by` never being part of `strategy_engine`'s exported public
  surface). Reusing the established *algorithm* (tolerance-band, `<=`
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
  mirroring `try_consume()`'s "no get/set split" principle exactly, its
  full signature:

  ```python
  def decide_once(
      self,
      range_start: datetime,
      session_name: SessionName,
      candidates: Tuple[OpportunityCandidate, ...],
      tie_tolerance: float,
      duration_minutes: int,
      now: datetime,
  ) -> Optional[str]:
  ```

  **`duration_minutes` is never invented or recomputed by Runtime or the
  new engine** — the caller (Runtime, via `OpportunitySelectionEngine.
  evaluate_window()`) sources it from the one authoritative field that
  already governs every opening range's own width, `EvidenceEngineConfig.
  opening_range_duration_minutes`, read via Runtime's already-held
  `self.evidence_engine.config.opening_range_duration_minutes` reference
  (`EvidenceEngine.config`, confirmed directly against source — no new
  constructor parameter needed, mirroring the same pattern already used
  for `self.strategy_engine.config` in §3). This is a single, global value
  shared by every configured anchor (confirmed directly:
  `EvidenceEngineConfig._validate_no_overlapping_anchors(self.
  opening_range_anchors, self.opening_range_duration_minutes)` passes one
  shared duration for all anchors) — there is no per-anchor duration to
  select between, so no additional lookup or matching logic is needed
  beyond reading this one field.

  **Persistence timing — corrected (a second, HIGH-severity finding from
  the independent Plan re-review, resolved here): only a genuine, single
  winning pair is ever written to the store. A "no winner this cycle"
  outcome (zero candidates, or an unresolved tie) is never persisted at
  all — it is a cycle-local result only, and the key remains absent so a
  later cycle recomputes fresh.** The original design persisted every
  `decide_once()` outcome unconditionally, including an empty-candidate
  result — because `orb_breakout.py::qualify()` returns `NOT_QUALIFIED`
  throughout a range's entire *formation* period (`is_formed = now >=
  range_end`, verified directly against `evidence_engine/opening_range.py`
  — no pair can possibly produce an enabled-window ORB candidate before a
  range has even formed), the very first evaluated cycle of a window's
  life will, in the overwhelming majority of real deployments, have zero
  candidates. Persisting that as a locked `None` would, via idempotency,
  permanently and silently prevent any genuine breakout detected in a
  *later* cycle of the *same still-relevant* window from ever being
  selected — the window remains `currently_relevant` (via `orb_breakout.
  py`'s own `latest_range_end` filtering) for as long as no newer range for
  the same anchor has formed, which for a once-daily anchor is effectively
  the rest of the calendar day (`compute_opening_ranges()`'s own `range_
  start = now.replace(hour=..., minute=..., ...)` construction, verified
  directly against source, produces the identical `range_start` for the
  entire day — there is no source-derivable boundary earlier than calendar-
  day rollover at which a window's opportunity to produce a candidate can
  be said to have definitively ended). **Rather than inventing an
  unsupported terminal-window cutoff, this Plan avoids needing one
  entirely**: because only a genuine winner is ever locked in, no negative
  decision ever needs a "when is it too late to reconsider" boundary — every
  cycle before a winner exists remains fully, safely re-triable.

  Exact contract, under the lock (the stale-window check runs first,
  unconditionally, exactly as before):

  1. **Stale-window defense-in-depth** (ADR-037 §12, unchanged): if
     `range_start + timedelta(minutes=duration_minutes) < now`, log a
     distinct `stale_window_encountered` signal and return `None` without
     touching the store at all — this is a should-never-happen guard
     (Runtime only ever presents a `range_start` Evidence Engine just
     computed as currently relevant this cycle), unaffected by the
     persistence-timing correction above.
  2. **If `range_start.isoformat()` is already a key** (a genuine winner
     was durably decided on a prior call): return the persisted pair
     **unchanged**, without even constructing `candidates` into `select_
     winner()` — this is the "once a genuine winner has been selected and
     durably persisted, later cycles must never replace it" guarantee,
     satisfied unconditionally and irrespective of what a later cycle's
     own candidate set contains.
  3. **Else** (no key yet): call `select_winner(candidates, tie_tolerance)`.
     - If it returns a genuine single winner: persist `{"session_name":
       session_name.value, "pair": winner, "decided_at": now.isoformat()}`
       and return the winner. The stored `pair` field is **always a real
       pair string** once a key exists at all — there is no longer a
       persisted `None` value to distinguish from "not yet decided";
       "key absent" and "no winner yet" are now the same fact, simplifying
       the schema the independent review's original design required.
     - If it returns no winner (zero candidates or an unresolved tie):
       **persist nothing**, return `None` for this cycle only. The key
       remains absent, so any later cycle — including one with a
       completely different candidate set — recomputes fully fresh, with
       no memory of this cycle's non-outcome.

  The entire check-then-persist sequence (steps 2–3) executes under one
  lock acquisition, exactly as `try_consume()` already does — this is what
  makes two genuinely concurrent calls for the same `range_start` safe:
  whichever acquires the lock first either finds no key yet (computes, and
  persists only if it found a real winner) or already has one (returns it
  immediately); the second call, once it acquires the lock, re-checks the
  key — now possibly just populated by the first call — *before* computing
  anything of its own, so it can never independently select and persist a
  second, different winner.

  **Observability of a "no winner yet" cycle is unaffected by this
  correction** — ADR-037 §12's own already-required per-cycle signals
  ("No candidates available for a session," "Tie / no-winner produced
  despite candidates existing") are emitted by `logging_sink.py`/
  `metrics.py` (§1 above) on every such cycle regardless of whether the
  store persists anything; an operator can already reconstruct "this
  window never produced a winner" from the absence of a "winner selected"
  signal across the window's relevant cycles, without the winner store
  itself needing to record every negative outcome. ADR-037 §9's own
  "Persistence: the winner (or the fact that no winner was selected) must
  be recorded" is satisfied by this observability trail, not by requiring
  the cardinality-enforcing winner store to durably lock in every negative
  cycle — §9's own idempotency constraint is worded specifically around
  "after **a winner** is already persisted," never around a persisted
  negative outcome, which is consistent with this reading.
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
methods on `RuntimeOrchestrator`, plus one further, small refactor the
independent review found necessary (the `_build_audit_record` extraction
below) — both changes are behavior-preserving extractions of already-
existing code, not new logic:

- **`_build_audit_record(...)`** — a new **private instance method**
  (not a nested closure), replacing today's `_record()` nested closure
  with the identical construction logic, taking every value the closure
  currently captures as **explicit parameters**: `cycle_id, pair, profile,
  started_at, now, stage_timings, outcome, stage_reached, evidence_id=
  None, selected_strategy=None, trade_intent=TradeIntent.NONE, risk_
  approved=None, compliance_decision=None, bridge_error=None, reasons=(),
  evidence=None, market_intelligence=None, risk=None, compliance=None,
  bridge_correlation_id=None`. **Why this extraction is required, found by
  the independent review, not present in the original draft:** the
  original design said barrier-participant termination records
  (`NOT_SELECTED_OPPORTUNITY_WINDOW`) would be built "via the existing
  `_record()` closure" — but `_record()` is defined *inside* `run_cycle_
  for_pair()`'s own single call, and a closure cannot be invoked once its
  enclosing call has returned. `run_cycle()`'s new per-window resolution
  code (step 3 below) runs *after* every pair's `_run_front_half`/`_run_
  back_half` invocation has already returned, so it structurally cannot
  reach any per-pair `_record()` closure — it needs its own callable path
  to the identical construction logic. Promoting the logic to a plain
  instance method is the smallest change that supplies this without
  duplicating the construction logic anywhere: `_run_front_half`'s own
  early-exit returns, `_run_back_half`'s own returns, and `run_cycle()`'s
  new per-window termination code all call `self._build_audit_record(...)`
  with their own explicit arguments. **Existing audit semantics are
  preserved exactly** — the method body is a verbatim move of the current
  closure's logic; only its calling convention changes (explicit
  parameters instead of closure capture), which is transparent to every
  existing test asserting on `RuntimeAuditRecord` field values.
- **`_run_front_half(pair, bars, events, ..., profile, now, cycle_id)`** —
  everything from `run_cycle_for_pair()`'s current start through the
  `strategy.rejected` check (today's lines ~205–239), calling `self.
  _build_audit_record(...)` for its own early-exit returns instead of a
  local closure. **Returns a `(strategy_completed: bool, result: Union[
  RuntimeAuditRecord, _FrontHalfResult])` pair** — see below for exactly
  what `strategy_completed` means and why it, not the returned value's
  type or `CycleOutcome`, is the sole authority for completeness tracking
  (this directly fixes the independent review's HIGH completeness
  finding). `_FrontHalfResult` (module-private dataclass) carries
  `evidence`, `market_intelligence`, `strategy`, `evidence_id`, `stage_
  timings` accumulated so far, and `started_at` (`= now`, identical for
  every pair in one cycle, carried through so `run_cycle()`'s later
  per-window termination code can call `_build_audit_record` without
  needing `run_cycle()` to separately track it per pair).
- **`_run_back_half(front_half, portfolio_state, trade_history,
  account_state, profile, now, cycle_id)`** — everything from today's
  `last_stage = CycleStage.RISK` onward (Risk → Compliance → Bridge,
  unchanged verbatim), taking a `_FrontHalfResult` instead of re-deriving
  anything, calling `self._build_audit_record(...)` for its own returns.
- **`run_cycle_for_pair()` itself becomes:** call `_run_front_half`; if it
  returned a terminal record, return it; otherwise immediately call
  `_run_back_half` with the `_FrontHalfResult` and return *that*.
  **Byte-for-byte identical observable behavior to today's monolithic
  function for every existing caller and test** — this is the load-
  bearing backward-compatibility guarantee that lets every existing
  `run_cycle_for_pair`-level test keep passing unmodified; it simply
  discards the `strategy_completed` boolean, which only `run_cycle()`'s
  own new sequencing needs.

**The `strategy_completed` signal — the single, unambiguous completeness
condition (replaces the independent review's HIGH finding entirely):**
set to `True` at exactly one place in `_run_front_half`'s body — the
statement immediately after `strategy = self.strategy_engine.evaluate(...)`
**returns successfully**, before any inspection of `strategy.rejected` or
any other field. It is never derived from, or inferred by pattern-matching
on, which `CycleOutcome` value or `stage_reached` a terminal record
happens to carry — those are observability labels, not the completeness
signal. Consequently, and exhaustively:

- `OUTSIDE_TRADING_WINDOW` (returned before Evidence Engine is even
  called) → `strategy_completed = False`.
- `SESSION_NOT_ALLOWED` (returned after Evidence, before Market
  Intelligence/Strategy) → `strategy_completed = False`.
- `FAILED`, when the exception occurred anywhere before the Strategy
  Engine call returns (Evidence, Market Intelligence, or during the
  Strategy call itself) → `strategy_completed = False` — this is the
  precise reading of ADR-037 §5.D's "an exception before Strategy Engine
  runs... has not reached a terminal outcome," and is **not** the same
  test as "the record's `stage_reached` equals `CycleStage.STRATEGY`,"
  since `last_stage` is set to `CycleStage.STRATEGY` immediately *before*
  the Strategy call executes — an exception raised by the call itself
  still carries `stage_reached=CycleStage.STRATEGY` on its `FAILED`
  record, yet must **not** count as terminal. Only the boolean, set
  strictly *after* the call returns, distinguishes these correctly.
- `NO_STRATEGY` (the call returned, `strategy.rejected` is `True`) →
  `strategy_completed = True`.
- A `_FrontHalfResult` is returned (the call returned, `strategy.rejected`
  is `False`) → `strategy_completed = True` **unconditionally** — this
  covers every one of ADR-037 §5.D's remaining terminal categories alike
  (an eventual legacy-strategy winner, a non-enabled-window ORB result, or
  an enabled-window ORB candidate) without needing to distinguish between
  them at this point at all.

`run_cycle()` (step 2 below) uses this boolean directly as `reached_
terminal[pair]` for pairs in `tracked_pairs` — never `record.outcome`,
never `record.stage_reached`, never "was a `RuntimeAuditRecord` returned
at all" (every branch returns one or leads to one eventually; returning a
record is not itself evidence of completeness, which is exactly what the
independent review's HIGH finding identified).

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
   - Call `_run_front_half`, receiving `(strategy_completed, result)`.
   - **If `pair in tracked_pairs`: set `reached_terminal[pair] =
     strategy_completed` directly — this single assignment is the
     complete completeness rule; nothing else ever sets or reads this
     dict.** (Non-tracked pairs never populate or consult `reached_
     terminal` at all — it is irrelevant to them.)
   - **If `result` is a terminal record:** append it to `records` exactly
     as today, whatever its outcome (`OUTSIDE_TRADING_WINDOW`, `SESSION_
     NOT_ALLOWED`, `NO_STRATEGY`, or `FAILED`) — `reached_terminal[pair]`
     was already correctly set above, independent of which of these four
     it is. **This is the exact fix for the independent review's HIGH
     completeness finding**: `NO_STRATEGY` is terminal not because "it
     returned a record" (every branch does) but because `strategy_
     completed` was `True` when it was produced; `OUTSIDE_TRADING_WINDOW`/
     `SESSION_NOT_ALLOWED`/a pre-Strategy `FAILED` are non-terminal not
     because of some special-cased exclusion but because `strategy_
     completed` was `False` when *they* were produced. One condition,
     no exceptions to state.
   - **If `result` is a `_FrontHalfResult`:** classify using only
     already-computed fields (ADR-037 §5.B): read `strategy.winning_
     strategy` (`None` is impossible here, since `strategy.rejected`
     already routed to the terminal-record branch above) and its
     `strategy_id`/`qualification.range_start`. **Invariant, verified
     directly against `orb_breakout.py`'s own control flow: `winning_
     strategy.strategy_id is OPENING_RANGE_BREAKOUT` implies `qualification.
     range_start is not None`** — every `NOT_QUALIFIED` return in `qualify()`
     precedes the line that sets `range_start` on the `QUALIFIED` result
     (§2), so ORB can never become `winning_strategy` without a real
     `range_start`. This Plan does not implement a defensive `range_start
     is None` branch for this combination; if one is ever added, it must
     be treated as an internal fail-closed error (log distinctly, treat
     the pair as non-participating, increment a dedicated invariant-
     violation counter) — never as an ordinary, expected path, since no
     such path exists under this design. **Membership check against
     currently-enabled windows** — build the set of this cycle's enabled
     `range_start` values once, by matching each `EnabledOpportunityWindow`'s
     `(anchor_hour_utc, anchor_minute_utc)` against `now`'s date (mirroring
     `evidence_engine/opening_range.py`'s own `now.replace(hour=...,
     minute=..., second=0, microsecond=0)` construction — Runtime does not
     re-derive "is this range currently relevant," it only recomputes the
     *label* of an enabled config entry into today's concrete `range_
     start`, a pure timestamp construction, not a trading decision).
     - If `winning_strategy.strategy_id is not OPENING_RANGE_BREAKOUT`, or
       its `range_start` is not one of this cycle's enabled `range_start`
       values: **non-participating.** Call `_run_back_half` immediately
       and append the result to `records` — **no waiting, no latency
       change**, exactly today's behavior. (`reached_terminal` was
       already set `True` above, unconditionally, for any `_FrontHalfResult`
       — no further action needed here.)
     - Else (ORB won, and its `range_start` matches an enabled window):
       **barrier participant.** (`reached_terminal` already `True`.) **Do
       not call `_run_back_half` yet** — append the pair's `(_FrontHalf
       Result, portfolio_state, trade_history, account_state)` tuple to a
       per-cycle `Dict[datetime, List[...]]` keyed by that `range_start`
       (this is exactly the "cycle-scoped orchestration state" ADR-031
       Amendment 1 §4 authorizes — see below for why it needs no new
       dataclass).
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
       ("opportunity window scan incomplete this cycle",)`, via **`self.
       _build_audit_record(...)`** (§3's own extracted instance method,
       not a closure — this is exactly the call site the independent
       review found had no reachable construction path under the original
       design): `stage_reached=CycleStage.STRATEGY`, `selected_strategy=
       OPENING_RANGE_BREAKOUT`, `trade_intent=strategy.trade_intent`,
       `evidence=`/`market_intelligence=`/`stage_timings=`/`started_at=`
       populated from its own held `_FrontHalfResult` — Risk/Compliance
       never invoked, so `risk_approved`/`compliance_decision` stay
       `None`. Appended to `records`.
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
         For **every other** pending entry in this window: terminate
         (via `self._build_audit_record(...)`, exactly as the incomplete-
         scan branch above) with `CycleOutcome.NOT_SELECTED_OPPORTUNITY_
         WINDOW`, `reasons=("another candidate was selected for this
         opportunity window",)`.
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
pair's **terminal** disposition (`_build_audit_record()` — §3's extracted
instance method — is called exactly once per pair per cycle, today and
after this change). A barrier participant simply has no `RuntimeAudit
Record` yet while pending — its "waiting" state is represented purely by
its presence in the in-memory pending list described above, which the new
logging/metrics calls (§1, engine-side; plus a Runtime-side "window scan
started with N pending candidates" log line, emitted once per enabled
window immediately before that window's completeness/selection resolution
in step 3) make observable without requiring a persisted, terminal-shaped
audit type to represent a non-terminal moment. This is a deliberate,
justified choice of "another representation" — the third option ADR-031
Amendment 1 §7 explicitly leaves open. **This representation is not
merely asserted — §10 now includes an executable test (`test_pending_
candidates_logged_before_window_resolution`) proving the log line is
actually emitted with the correct pending count**, closing the
independent review's MEDIUM observation that this claim previously had
no corresponding proof.

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

**Structural-readiness mechanism, corrected (the independent review's
second HIGH finding):** the original draft inferred "cross-pair selection
is active" from `len(strategy_config.approved_pairs_for(OPENING_RANGE_
BREAKOUT)) > 1`, presenting this as an established ADR-036 Amendment 1
precedent. **Fresh re-inspection finds this claim false and the mechanism
itself unsafe.** A direct grep of `docs/adr/ADR-036-orb-strategy-
consolidation.md` for "narrow"/"broad" finds no numeric pair-count
definition anywhere in that document — its conditions 1–3 require only
"≥1 approved production pair" and "≥1 valid anchor entry," with no
upper-bound distinction. ADR-037 §11 item 3 itself states plainly that
the exact detection mechanism is unresolved and names **both** candidates
explicitly: *"a Gate-A-width threshold, or an explicit separate flavor-
selection flag — that is Plan-level work."* A pure pair-count threshold
carries a real misclassification risk ADR-037 §13 itself anticipates:
"a narrow/fixed Gate A" is explicitly defined there as *"a single pair,
**or a small fixed list**"* — i.e., a deployment can legitimately run a
fixed, non-cross-pair-selecting Gate A with more than one approved ORB
pair. A bare `> 1` test would misclassify exactly that deployment as
"selection active," forcing it to satisfy invariants (a non-empty
`enabled_windows`, full Gate-B-anchor coverage) it never needed and never
asked for.

**Corrected mechanism: an explicit, operator-set intent flag —
`OpportunitySelectionEngineConfig.cross_pair_selection_enabled: bool =
False` (§1)** — replacing the pair-count heuristic entirely. This cannot
misclassify a fixed multi-pair deployment, because intent is declared,
never inferred: a deployment that never sets this field stays at its
default (`False`) regardless of Gate A's width, and none of the checks
below ever run for it. **This is also the safe migration default this
revision requires**: any existing or newly-created deployment profile
that does not explicitly construct an `OpportunitySelectionEngineConfig`
with `cross_pair_selection_enabled=True` remains entirely inert with
respect to every invariant in this section, regardless of how many pairs
Gate A happens to approve for ORB.

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
first three parameters are entirely unaffected — this remains the same
additive-parameter precedent ADR-031 Amendment 1 §1 cites, verified fresh:
`validate_profile()`'s current signature genuinely has no Gate B-aware
check today — confirmed directly against source, not assumed):

1. **Every `EnabledOpportunityWindow` entry must reference an existing
   Gate B anchor** (ADR-037 §11 item 1) — **runs unconditionally,
   whenever `enabled_windows` is non-empty, independent of `cross_pair_
   selection_enabled`**, since a dangling entry pointing at no real
   anchor is a configuration bug regardless of whether selection is
   declared active: its `(anchor_hour_utc, anchor_minute_utc)` must
   exactly match one `evidence_config.opening_range_anchors` entry's
   `(hour, minute)`; as a defense-in-depth consistency check, its
   declared `session_name` must also match that same anchor's own
   declared `SessionName` (catching an operator typo/drift between the
   two, rather than trusting the enabled-window's own label blindly).
2. **Whenever `cross_pair_selection_enabled` is `True`: every configured
   Gate B anchor not referenced by any enabled window is a
   misconfiguration** (ADR-037 §11 item 2). Never checked when the flag
   is `False`.
3. **Whenever `cross_pair_selection_enabled` is `True`: `enabled_windows`
   must be non-empty** (ADR-037 §11 item 3's "structurally-satisfiable-
   but-inert" invariant) — declaring selection active with no configured
   windows is a fail-closed misconfiguration, never silently tolerated.
   Never checked when the flag is `False`.
4. **Whenever `cross_pair_selection_enabled` is `True`: Gate A's ORB-
   approved-pairs count (`strategy_config.approved_pairs_for(StrategyId.
   OPENING_RANGE_BREAKOUT)`) must be `> 1`** — this is the same numeric
   fact the original draft used, but now applied only as a *consequence*
   of an operator's own explicit declaration, never as the mechanism for
   inferring that declaration: ADR-037 §11's own "Gate A... must remain a
   broad structural eligibility list when cross-pair selection is in
   effect... a single-pair Gate A would make this ADR's mechanism a no-op"
   is a real invariant *given* selection is declared active, and is safe
   to check only because the flag, not the count, establishes that
   precondition. Never checked when the flag is `False` — a fixed/narrow
   deployment may have any Gate A width without ever tripping this.

**The five required states are now each unambiguous and fail-closed:**

| State | Condition | Result |
|---|---|---|
| Fixed/no-cross-pair-selection deployment | `cross_pair_selection_enabled = False` (the default) | Checks 2–4 never run, regardless of Gate A width or `enabled_windows` contents; check 1 still catches a stray dangling entry if any exist |
| Cross-pair selection active, fully valid | `True`; every enabled window matches a Gate B anchor; every anchor is referenced; `enabled_windows` non-empty; Gate A width `> 1` | All four checks pass — structurally ready |
| Selection requested, enabled windows missing | `True`; `enabled_windows = ()` | Check 3 fails closed |
| Enabled window lacking a matching Gate B anchor | any `enabled_windows` entry with no matching `(hour, minute)` | Check 1 fails closed, unconditionally |
| Selection active, structurally incapable of operating | `True`; Gate A width `≤ 1` | Check 4 fails closed |

**Structural readiness remains categorically separate from dynamic
qualification** (ADR-037 §11's own explicit preservation): all four
checks run once, at startup/config-load time, over static configuration
only — none of them inspect a live `QualificationResult`, a scan outcome,
or any per-cycle state.

**No exact Gate A pairs or Gate B anchor values are chosen by this Plan.**
`DEFAULT_APPROVED_PAIRS_BY_STRATEGY`'s ORB entry and `EvidenceEngineConfig.
opening_range_anchors`' default both remain untouched (`()` / absent), and
`cross_pair_selection_enabled` defaults `False` — these four checks are
dormant, never triggered, at every default/test configuration this Plan
itself introduces, exactly as Gate A/B remain closed/empty throughout.
**This is not a Plan-finalization blocker**: ADR-037 and ADR-031 Amendment
1 were both drafted and Accepted with Gate A closed and Gate B empty the
entire time; this Plan specifies the exact *mechanism* these checks
require, fully testable against synthetic non-production values, without
needing the real production list/anchors to exist first. Populating them
is the next, separate, deployment-profile decision (ADR-036-governed for
Gate A; a dedicated future decision for Gate B's exact clock values, and
for when to flip `cross_pair_selection_enabled` itself), unaffected by
and not blocking this Plan.

**`opportunity_selection_config`'s fields never hardcode London/Overlap/
Early New York, and `cross_pair_selection_enabled` never hardcodes an
"active" default.** The initial production *values* (three
`EnabledOpportunityWindow` entries with those specific `session_name`s,
whatever anchor hour/minute the eventual deployment-profile decision
picks, and the eventual flip of `cross_pair_selection_enabled` to `True`)
are deployment configuration content supplied at startup, the same way
`DEFAULT_APPROVED_PAIRS_BY_STRATEGY`'s ORB entry or `opening_range_
anchors` are today — never a constant inside `opportunity_selection_
engine/`, `runtime/`, or `validation.py` itself.

## 6. Persistence contract

Specified fully in §1's `store.py` description. Summary against the
task's own required dimensions:

- **Key:** `range_start` alone (`isoformat()`-encoded string), never a
  composite with `pair` or `session_name` — matches `OrbQualificationStore`/
  `FormationBlackoutStore`'s own key-encoding convention, applied to a
  different identity.
- **Value:** `{"session_name": str, "pair": str, "decided_at": str}` —
  corrected in §1 (second HIGH finding from the independent Plan
  re-review): a "no winner this cycle" outcome (zero candidates, or an
  unresolved tie) is **never persisted at all**; the key remains absent
  and the cycle is recomputed fresh next time. Once a key exists, `pair`
  is always a real, single winning pair string — never `None` — so "key
  absent" and "no winner yet" are the same fact, and there is no longer a
  distinct persisted "decided, no winner" state to define or guard.
- **Idempotency:** re-evaluating a `range_start` whose key is **absent**
  recomputes from the current candidate set every time (§1) — this is
  intentional, not a gap: `orb_breakout.py::qualify()` returns
  `NOT_QUALIFIED` throughout a range's formation period and
  `compute_opening_ranges()` makes `range_start` calendar-day-stable
  (`evidence_engine/opening_range.py`), so no source-derivable boundary
  exists for declaring an opportunity window's negative outcome final
  before a genuine winner appears. Re-evaluating a `range_start` whose key
  **is present** returns the persisted winner unchanged, without
  reconstructing candidates or calling `select_winner()` at all — this
  matches ADR-037 §9's idempotency requirement exactly as worded, which
  applies specifically to "after a winner is already persisted."
- **Restart behavior:** `_entries` loads once at construction (mirroring
  the existing precedent). If a genuine winner was durably persisted
  before the restart, it resumes locked in, unchanged. If nothing was
  persisted yet (whether because no cycle had run, or every prior cycle
  had zero candidates or a tie), the window resumes freely re-decidable —
  restart fabricates no prior decision, and the same fact ("nothing
  durable happened yet") holds identically whether the process restarted
  or simply ran its next scheduled cycle.
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
3. **`_build_audit_record` extraction** (promoting the current `_record()`
   closure to a private instance method with explicit parameters, §3) and
   the **`run_cycle_for_pair` split** into `_run_front_half`/`_run_back_
   half`, with **no change to `run_cycle()`'s loop yet** — `run_cycle_for_
   pair` still calls both halves back-to-back itself and discards the new
   `strategy_completed` boolean. Run the full existing Runtime suite
   unmodified; it must pass byte-for-byte, proving both the extraction and
   the split are behavior-preserving before any new sequencing is
   introduced. *This is the step most important to keep atomic and
   isolated from step 4 — it must be provably a no-op before the barrier
   logic is added on top of it.*
4. **`run_cycle()` restructuring** (frozen tracking universe, the
   `strategy_completed`-based `reached_terminal` assignment, per-pair
   classification, per-window grouping/selection/termination) — the new
   `CycleOutcome` member, the two new `validate_profile()` parameters and
   the four corrected structural-readiness checks (§5), and the full new
   Runtime-side test matrix (§10) land together, since they are one
   coherent behavioral unit that cannot be meaningfully tested in isolated
   slices.
5. **`tests/titan_protocol/runtime/test_architecture.py`'s** disclosed
   `ALLOWED_UPSTREAM_PREFIXES` addition — made in the same commit as step
   4, since step 4 is what introduces the new upstream import; never
   landed alone or ahead of the dependency that requires it.
6. **`deployment_windows/start.py` wiring** — constructs the new config
   with **`cross_pair_selection_enabled=False` and `enabled_windows=()`,
   its explicit safe defaults** (empty/inert regardless of Gate A's actual
   width — no existing or newly-deployed profile is affected by this
   wiring landing, since none of §5's four checks ever run while the flag
   is `False`), plus the store and engine, and threads them through to
   `RuntimeOrchestrator` and `validate_profile()`'s call site. *Last*,
   since it depends on every prior step existing; a fresh-install/startup
   smoke test (mirroring this session's own established convention for
   deployment changes) runs after this step specifically, confirming
   startup still succeeds with these defaults.
7. Full-repository regression validation (§9 below), `CHANGELOG.md`
   entry, commit.

No step between 1 and 6 changes Gate A, Gate B, or any default config
value, and `cross_pair_selection_enabled` is never introduced as anything
but `False` by default — the entire sequence is exercisable and testable
with Gate A closed, Gate B empty, and selection mode inert throughout,
exactly as they remain today. **No intermediate state in this sequence
ever permits unrestricted multi-pair ORB execution**: before step 4 lands,
`run_cycle()`'s loop is unchanged and no barrier exists at all (today's
exact behavior); from step 4 onward, the barrier and its fail-closed paths
land as one atomic unit, never partially.

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
| **Pre-Strategy early exit (`OUTSIDE_TRADING_WINDOW`) incorrectly counted as complete** | `...test_outside_trading_window_does_not_set_strategy_completed` — asserts `strategy_completed is False` and the resulting scan is `incomplete`, directly regression-testing the independent review's first HIGH finding |
| **Pre-Strategy early exit (`SESSION_NOT_ALLOWED`) incorrectly counted as complete** | `...test_session_not_allowed_does_not_set_strategy_completed` — same assertion shape as above |
| **`NO_STRATEGY` incorrectly counted as incomplete** | `...test_no_strategy_sets_strategy_completed_true` — asserts `strategy_completed is True` for a rejected-but-completed Strategy evaluation, and that the scan is judged complete when it is the only tracked pair, directly regression-testing that the fix did not overcorrect in the opposite direction |
| **Pre-Strategy `FAILED` (exception before Strategy's call returns) incorrectly counted as complete** | `...test_pre_strategy_exception_does_not_set_strategy_completed` — asserts a `FAILED` outcome whose exception occurred during Evidence/Market Intelligence/the Strategy call itself leaves `strategy_completed is False`, distinguishing this from `stage_reached == CycleStage.STRATEGY` matching (§3's own noted ambiguity) |
| ORB `NOT_QUALIFIED` rejection counts as terminal | `...test_orb_rejection_counts_toward_completeness` |
| Legacy-strategy winner coexistence | `...test_legacy_winner_never_waits_at_barrier` |
| Duplicate-front-half prevention | `...test_front_half_invoked_exactly_once_per_pair_regardless_of_window_count` (asserts Evidence/MI/Strategy call counts via instrumented fakes) |
| Barrier-pending state is actually observable (ADR-031 Amendment 1 §7 item 1) | `...test_pending_candidates_logged_before_window_resolution` — asserts the "window scan started with N pending candidates" log line is emitted with the correct count before that window's completeness/selection resolution; closes the independent review's MEDIUM finding that this representation previously had no executable proof |
| Audit-record construction reachable from aggregate `run_cycle()` code | `...test_build_audit_record_reused_by_window_resolution_path` — asserts `_build_audit_record` (not a closure) is the single construction path for `NOT_SELECTED_OPPORTUNITY_WINDOW` records, and that its output field-for-field matches what the pre-refactor closure would have produced for an equivalent existing outcome (e.g. `NO_STRATEGY`), proving the extraction changed no observable behavior |
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
| **Zero candidates on cycle N, valid unique candidate on cycle N+1** | `...test_zero_candidates_cycle_does_not_block_later_unique_winner` — calls `decide_once()` with an empty candidate tuple for a given `range_start`, asserts the return is `None` **and no key is persisted** (`path.exists()` is `False`, or the entries dict has no matching key), then calls `decide_once()` again for the same `range_start` with one qualifying candidate and asserts it is now selected and persisted. Directly proves the HIGH persistence/re-evaluation defect is fixed. |
| **Tie on cycle N, unique candidate on a later cycle** | `...test_tied_cycle_does_not_block_later_unique_winner` — same shape as above, but cycle N's candidate set produces an unresolved tie (two candidates within `tie_tolerance`) rather than an empty set; asserts no key is persisted after the tie, and a later cycle with a single qualifying candidate is selected normally. |
| **Winner persisted on cycle N, different/better candidate later cannot replace it** | `...test_persisted_winner_survives_a_later_higher_scoring_candidate` — cycle N selects and persists a winner; cycle N+1 is called with a *different* candidate set whose top score strictly exceeds the persisted winner's original score; asserts the return is still the original winner, unchanged, and `select_winner()` is never even invoked for cycle N+1 (via an instrumented fake), proving the "key present → return unchanged, no recomputation" contract, not merely "the same answer by coincidence." |
| **Restart before any winner does not fabricate a prior decision** | `...test_restart_before_winner_starts_with_no_persisted_decision` — constructs a store, calls `decide_once()` once with zero candidates (no key persisted), discards the instance, constructs a fresh `OpportunityWinnerStore` against the same state file (simulating a process restart), and asserts the fresh instance has no entry for that `range_start` and freely selects a winner when next given a qualifying candidate — restart never invents a "decided, no winner" record that was never written. |
| **Restart after a winner preserves that winner** | `...test_restart_after_winner_preserves_persisted_winner` — persists a winner, constructs a fresh store instance against the same state file, and asserts `decide_once()` returns the original winner unchanged without recomputing, mirroring `OrbQualificationStore`'s own restart-resume precedent. |
| **Sequential same-window re-invocation (not merely concurrent)** | `...test_sequential_decide_once_calls_same_process_converge_on_one_winner` — a single-threaded, in-process test calling `decide_once()` repeatedly for the same `range_start` across simulated cycles (zero candidates, then a tie, then a real winner, then a different later candidate set) in strict sequence, asserting the terminal state is exactly one persisted winner and every call after it returns that winner unchanged — the concurrency test above proves thread-safety under a race; this test proves the same invariant holds in the far more common sequential/single-threaded case. |
| Non-winner never reaches Risk | `tests/titan_protocol/runtime/test_engine.py::...test_non_winner_stage_reached_is_strategy_never_risk` |
| Winner failing Risk/Compliance/Bridge, no runner-up | `...test_winner_rejected_by_risk_produces_no_fallback_to_runner_up` |
| Arbitrary-cardinality config | (covered by the 0/1/2/3/4-window tests above, plus) `tests/titan_protocol/opportunity_selection_engine/test_config.py::test_enabled_windows_accepts_any_length_tuple` |
| Structural-readiness failures (all four §5 checks, corrected mechanism) | `tests/titan_protocol/runtime/test_validation.py::test_enabled_window_without_matching_gate_b_anchor_fails` (check 1, unconditional); `test_unreferenced_gate_b_anchor_fails_when_selection_active` (check 2, gated on the flag); `test_selection_active_with_empty_enabled_windows_fails` (check 3, gated on the flag); `test_selection_active_with_single_pair_gate_a_fails` (check 4, gated on the flag) |
| **Fixed multi-pair Gate A does not falsely activate cross-pair selection** | `...test_multi_pair_gate_a_with_selection_disabled_passes_validation_untouched` — Gate A has 3+ approved ORB pairs, `cross_pair_selection_enabled` left at its default `False`; asserts checks 2–4 never fire and `ConfigValidationResult.valid` is unaffected by Gate A width alone. Directly regression-tests the independent review's second HIGH finding |
| Selection mode active with zero windows | `...test_selection_active_with_empty_enabled_windows_fails` (same as check 3 above) |
| Missing/mismatched Gate B anchor for an enabled window | `...test_enabled_window_without_matching_gate_b_anchor_fails` (same as check 1 above) |
| Preservation of existing Risk/Compliance/Bridge semantics | full existing `tests/titan_protocol/risk_engine/`, `compliance_engine/`, `bridge/` suites re-run unmodified (must stay green, no new test needed — proof by non-regression) |
| Architecture-test consequence | `tests/titan_protocol/runtime/test_architecture.py::test_only_permitted_upstream_packages_are_imported` (extended `ALLOWED_UPSTREAM_PREFIXES`, re-run to confirm it still passes and rejects any *other* new upstream import) |
| New package's own architecture boundary | `tests/titan_protocol/opportunity_selection_engine/test_architecture.py` (forbidden sizing/execution vocabulary; `ALLOWED_UPSTREAM_PREFIXES = ("titan_protocol.strategy_engine",)` only; no randomness/ML imports) |

## 11. Adversarial review of this Plan

**This section is now a fresh adversarial pass against the *revised*
design**, performed after the corrections in §1–§10 above, specifically
targeting the scenarios the independent review's revision instructions
named plus every row the original pass already covered:

| # | Risk checked | Finding |
|---|---|---|
| 1 | **Pre-Strategy early exit incorrectly counted as complete** | Fixed by this revision: `strategy_completed` (§3) is `False` for `OUTSIDE_TRADING_WINDOW`, `SESSION_NOT_ALLOWED`, and any `FAILED` whose exception occurred before the Strategy call returns — verified against `run_cycle_for_pair`'s exact current control flow, not merely asserted; §10 carries three dedicated regression tests. |
| 2 | **`NO_STRATEGY` incorrectly counted as incomplete** | Fixed: `strategy_completed` is `True` the instant `self.strategy_engine.evaluate(...)` returns, before `strategy.rejected` is even inspected — `NO_STRATEGY` (rejected=`True`) and every non-rejected result set it identically; §10's `test_no_strategy_sets_strategy_completed_true` regression-tests this was not overcorrected into treating `NO_STRATEGY` as incomplete. |
| 3 | **Fixed multi-pair Gate A incorrectly activating cross-pair selection** | Fixed: §5's four structural-readiness checks are now gated entirely on the explicit `cross_pair_selection_enabled` flag (default `False`), never on Gate A's pair count — a fixed deployment with any Gate A width never trips checks 2–4 unless it explicitly opts in; §10's `test_multi_pair_gate_a_with_selection_disabled_passes_validation_untouched` is the direct regression test. |
| 4 | Selection mode active with zero windows | §5 check 3, unchanged in substance from the original design (only its gating condition changed) — still fails closed. |
| 5 | Missing/mismatched Gate B anchors | §5 check 1, unconditional regardless of the flag — still fails closed. |
| 6 | **Audit records unavailable from aggregate `run_cycle()` logic** | Fixed by this revision: `_build_audit_record` (§3) is a plain instance method, not a closure, reachable from `_run_front_half`, `_run_back_half`, and `run_cycle()`'s own per-window termination code alike — verified against the actual scoping rule that a Python closure cannot be invoked once its enclosing call has returned, which the original design's "via the existing `_record()` closure" language did not account for. |
| 7 | **Stale-window validation missing duration** | Fixed: `decide_once()`'s full signature (§1/§6) now states `duration_minutes: int` explicitly, sourced from `self.evidence_engine.config.opening_range_duration_minutes` — verified this is a single, global field shared by every anchor (not per-anchor), so no matching/lookup logic beyond reading it once is needed. |
| 8 | Duplicated front-half execution | Unchanged from the original pass: §9's implementation sequence step 3 requires the split (now including the `_build_audit_record` extraction) to be proven behavior-preserving before step 4 introduces any new sequencing; the per-pair loop still runs exactly once, never once per window. |
| 9 | Non-winner reaching Risk | Unchanged in substance, re-verified against the corrected design: exactly one call site ever invokes `_run_back_half` for a barrier participant (the winner-equality branch); every other pending entry is terminated via `self._build_audit_record()` directly, which never touches Risk. |
| 10 | **Selector/store failure restoring unrestricted execution** | Re-verified: incomplete-scan and selector-failure branches still produce the identical `NOT_SELECTED_OPPORTUNITY_WINDOW`/zero-winners shape; nothing in the `cross_pair_selection_enabled` addition creates a new failure path that falls back to per-pair-unrestricted execution — the flag only gates *validation* checks, never Runtime's own selection/termination logic. |
| 11 | **Hidden assumption of exactly three windows** | Re-verified after the Gate A mechanism change: window count still appears in exactly one place (`for window in config.enabled_windows`); the new `cross_pair_selection_enabled` flag is a pure boolean, carrying no count information itself, so it introduces no new place a count could be hardcoded. |
| 12 | Runtime accidentally owns ranking | Re-verified unchanged: `run_cycle()`'s new code performs only set/dict membership, grouping, one call to the new engine, and equality checks on its `Optional[str]` result — no score comparison, threshold, or weight appears in `runtime/engine.py`. |
| 13 | Duplicate ORB/session logic | Re-verified unchanged: Runtime's `range_start` construction only *labels* a config entry for membership comparison; `orb_breakout.py::qualify()` remains the sole authority for "currently relevant range." |
| 14 | Test fixtures becoming production policy | Re-verified, strengthened: `deployment_windows/start.py`'s wiring (§9 step 6) now explicitly constructs `cross_pair_selection_enabled=False` **and** `enabled_windows=()` — two independent inert defaults, not one. |
| 15 | Accidental coupling to ADR-036 retirement | Re-verified unchanged: no ADR-036/legacy-retirement file appears in the file-impact matrix (§8); the five legacy strategies remain VERIFIED UNCHANGED; `StrategyId`'s six members are untouched. |
| 16 | Downstream engines importing the new package | Re-verified unchanged: nothing in `risk_engine/`, `compliance_engine/`, or `bridge/` imports `opportunity_selection_engine` under this Plan. |
| 17 | The new package's own `ALLOWED_UPSTREAM_PREFIXES` too broad | Re-verified unchanged: exactly `("titan_protocol.strategy_engine",)`. |
| 18 | **Persisting a "no winner this cycle" outcome (zero candidates, or an unresolved tie) could permanently lock a window to `None` starting from its very first evaluated cycle, since `orb_breakout.py::qualify()` returns `NOT_QUALIFIED` throughout formation and `range_start` is calendar-day-stable (`evidence_engine/opening_range.py`), leaving no source-derivable "window is definitively over" boundary before real breakouts can occur** | Fixed by this revision (§1/§6): a "no winner this cycle" outcome is never persisted at all — the key remains absent, and the cycle is fully re-computable on every later call, with no boundary needing to be invented. Once a genuine winner is persisted it remains permanently locked, exactly as ADR-037 §9 requires. §10 carries six dedicated regression tests for this exact defect (zero-candidates-then-later-winner, tie-then-later-winner, winner-cannot-be-replaced, restart-before-winner, restart-after-winner, sequential re-invocation). |

Every row in this table either identifies the exact revision that closed a
previously-real gap (rows 1–7 and 18, mapped directly to independent review
findings across both revisions) or re-confirms a prior finding still holds
after the corrections around it (rows 8–17) — none required a further
design change beyond what §1–§10 already specify.

## 12. Validation (Plan-only — no production behavior changes; this Plan itself contains no code)

Since this is a Plan artifact, the validation below confirms the *existing* repository state remains green and that this revision's diff is confined to this one document:

- `git status --short` — only `docs/plans/adr-037-implementation-plan.md` modified (re-verified fresh for this revision).
- `python3 -m compileall -q titan_protocol tests` — clean.
- `python3 -m unittest discover -s tests/titan_protocol/runtime` — 158/158 green, unmodified (this Plan changes no code yet).
- `python3 -m unittest discover -s tests/titan_protocol/strategy_engine` — 180/180 green, unmodified.
- `python3 -m unittest tests.titan_protocol.runtime.test_architecture` — 6/6 green, unmodified (the `ALLOWED_UPSTREAM_PREFIXES` change is specified, not yet made).
- Gate A closed, Gate B empty, no Opportunity Selection Engine implementation, no legacy-strategy retirement — all re-confirmed after this revision, unchanged.

## 13. Unresolved blockers

**None found after this second revision.** The first revision (`e139076`)
resolved four findings (two HIGH, one MEDIUM-HIGH, one MEDIUM) from the
first independent review, in §1/§3/§5/§6, with a single, unambiguous
mechanism each — no residual ambiguity is left for a later implementer to
invent. The two remaining smaller observations from that pass
(barrier-pending-state proof; the inapplicable `scripts/
check_architecture.py` citation) are also closed (§3, §1, §10).

This second revision resolves the one HIGH finding raised by the
subsequent independent Plan re-review — the persistence/re-evaluation
defect (§1/§6/§10/§11 row 18) — plus the LOW duplicate-text finding (§5,
both duplicated blocks removed). No source/governance contradiction was
found while designing the fix: `orb_breakout.py`, `evidence_engine/
opening_range.py`, and ADR-037 §9 together support "only a genuine winner
is ever durably persisted" as the smallest correct design, without
inventing any unsupported terminal-window cutoff or trading policy.

Every item this Plan's own instructions forbade inventing (exact Gate A
pairs, exact Gate B anchor clock times, Watchdog inclusion decided by
fiat rather than evidence, config-ownership left vague, a fabricated
"window closed" boundary) remains either resolved with fresh evidence
(§7's Watchdog determination; §1's config-ownership specification; §1/§6's
persistence-timing correction) or explicitly identified as
deployment-profile content this Plan's mechanism does not require to
exist yet (§5's Gate A/B values, and the eventual flip of
`cross_pair_selection_enabled` itself). All are correctly deferred, not
blocking.

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
