# Phantom vNext — Definitive Implementation Roadmap

Status: **planning artifact, not implementation.** No production code
was written to produce this document; nothing in `phantom/`, `mt5/`, or
`tests/` was touched. This roadmap is the ordering/dependency/interface/
test-plan specification requested for the architecture locked in
`PHANTOM_FINAL_ARCHITECTURE.md`; producing it is planning work, not the
"implementation" the gate below blocks — no component's code is built
here or authorized to be built as a result of this document alone.

## 0. The gate this roadmap does not bypass

Per this task's explicit constraint, no implementation of any component
below may begin until all three hold:

1. Phase 1 MetaEditor compile passes (real MetaEditor, not this
   sandbox's static tokenizer check).
2. Phase 1 MT5 demo validation passes (`02_demo_validation_plan.md`'s
   31 tests, executed for real).
3. `08_signoff_template.md` is completed with an **Approve** recommendation.

Current status of all three: **not yet run.** Nothing in this document
changes that. Everything from Phase 2 onward is sequencing/interface
planning for the moment those three gates clear — it is not itself
authorization to start Phase 2.

## 1. Locked component roster (reference only)

Nine components exactly as locked — no new engine, package, or layer
is introduced anywhere in this document. Full per-file responsibility
already exists in `PHANTOM_FINAL_ARCHITECTURE.md` §2–3; this roadmap
only adds the deltas the new lock message specified (Risk Schedule,
three-score Market Intelligence output, locked `phantom/shared/`
contents) and the build sequencing that document deferred.

| # | Component | Status |
|---|---|---|
| 1 | PhantomBridgeEA | Built, frozen, gated on §0 |
| 2 | Evidence Engine | Not started |
| 3 | Strategy Engine | Not started |
| 4 | Portfolio Statistical Risk Engine | Not started |
| 5 | Market Intelligence Engine | Not started |
| 6 | Prop Firm Compliance Engine | Not started |
| 7 | Research & Learning Engine | Not started |
| 8 | System Reliability Engine | Not started |
| 9 | Validation (offline only) | Not started |
| — | `phantom/shared/` | Not started — locked contents below |
| — | `phantom/runtime/` (thin orchestrator, not a 9th engine) | Not started — see §6.1 and `docs/specs/00_runtime_orchestrator.md` |

## 2. `phantom/shared/` — locked contents

Exactly as specified, no more:

- `Pair`, `Direction`, `Timeframe` — immutable value types/enums
- `Clock` — a protocol (interface), never a concrete scheduler or
  event loop; each component supplies its own clock implementation
  the same way `phantom/bridge` already does (`clock: Callable[[],
  datetime]` passed into `BridgeEngine`/`serve`) — `shared/` defines
  the shape, not a runtime
- `Price`, `Volume`, `Money` — immutable numeric value types with
  their own equality/precision rules, so no two components round or
  compare these differently
- `SCHEMA_VERSION` — the same versioning convention
  `phantom/bridge/models.py` already established, generalized as a
  shared constant-and-convention, not a shared mutable registry
- Shared enums, shared immutable value objects, shared constants,
  shared error types — as needed by more than one component, added
  only when a second consumer actually needs it (see §7 rule)

**No business logic, no trading logic, no decision authority, no
strategy code, no risk code** — enforced the same way Phase 1 already
enforces its own boundary
(`tests/phantom/bridge/test_structural_boundary.py`): a
`tests/phantom/shared/test_structural_boundary.py` asserting no file
under `phantom/shared/` imports anything from any other `phantom.*`
package, and no function in it takes a decision-shaped name
(`decide_`, `score_`, `size_`, `approve_`, `select_`).

**Decision recorded, not assumed:** `phantom/bridge/` (Phase 1) keeps
its own locally-defined types (`phantom/bridge/models.py`) rather than
being retrofitted onto `phantom/shared/`. Phase 1 is frozen and out of
scope for modification; adopting shared types there is a future,
separately-approved decision, not something this roadmap assumes or
schedules.

## 3. Specification deltas from the previous freeze

### 3.1 Portfolio Statistical Risk Engine — Risk Schedule

Evidence Engine's per-pair 0–100 score now has a locked mapping to a
risk-allocation tier, owned and applied exclusively by
`phantom/risk/confidence_scaling.py` (no other file computes this
mapping — one authority, per the lock's own rule):

| Score band | Tier | Effect |
|---|---|---|
| 95–100 | Maximum approved risk | Highest sizing multiplier this schedule allows |
| 90–94 | High risk allocation | |
| 85–89 | Standard allocation | |
| 80–84 | Reduced allocation | |
| 75–79 | Conservative allocation | |
| 70–74 | Minimal allocation | |
| 65–69 | Minimum qualified trade | Smallest size this schedule still allows a trade at |
| Below 65 | Reject | `position_sizing.py` returns a veto, not a size — the trade idea never reaches Prop Firm Compliance Engine |

This table is the entire contract between Evidence Engine's score and
Risk Engine's sizing tier — `confidence_scaling.py` is a pure lookup
against it plus whatever multiplier-per-tier config
`phantom/risk/config.py` defines; it must not encode any other
scoring logic (that would be a second scoring authority, which the
lock forbids).

### 3.2 Market Intelligence Engine — three per-pair scores

The previous freeze had two outputs (`news_score`, `pair_safety_score`).
The lock specifies three: **News Score**, **Market Impact Score**, and
**Pair Safety Score**. Delta from `PHANTOM_FINAL_ARCHITECTURE.md`'s
file list:

- Add `phantom/intelligence/market_impact_score.py` — scores the
  *magnitude* of upcoming/recent event impact for a pair (distinct
  from `news_score.py`, which scores the pair's general news
  environment, and from `pair_safety_score.py`, which is the
  aggregate of both plus session/liquidity/spread/volatility quality).
- `economic_calendar.py`'s scope now explicitly includes holiday
  schedules (added to the lock's evaluation list) — folded into the
  existing file rather than a new one, per the "three similar lines
  before a new abstraction" rule; a dedicated holiday file is only
  justified if holiday logic later grows independent of calendar
  normalization.
- `event_classifier.py`'s scope now explicitly includes Employment and
  PMI event types alongside the previously-listed CPI/PPI/GDP/NFP/
  rate-decisions/speeches/central-bank events — no new file, same
  classification responsibility, more event types.

**Automatic entry blocking is a hard gate, not merely advisory
suppression.** The lock states high-impact/critical events
"automatically block new entries on affected pairs" — stronger than
the previous freeze's "can suppress." This is implemented as a single
queryable, deterministic gate:

```
intelligence_engine.get_entry_gate(pair, now) -> EntryGateDecision
    ALLOWED
  | BLOCKED_NEWS_BLACKOUT
  | BLOCKED_HOLIDAY
  | BLOCKED_PEG_POLICY_EVENT
```

Strategy Engine's `selector.py` must treat this exactly like
PhantomBridgeEA's own pre-flight checks treat `CheckTradingPreconditions`
(per `docs/research/mt5-standard-library-research.md` §8's synthesized
best-practice #5: validate capability before every attempt, not just
once) — a mandatory precondition checked immediately before emitting a
`TradeIdea`, never a score it merely factors in. This keeps Market
Intelligence Engine's role "advisory only, never generates trades"
intact: it does not choose *which* trade, it only states a fact
("entries are currently blocked on this pair"), the same way
Compliance Engine's rules are facts about limits, not trade selection.

## 4. Dependency graph

```
Phase 1: PhantomBridgeEA  (built, frozen, gated on §0)
        |
        |  (execution telemetry: positions, account state)
        v
Phase 2: phantom/shared/  (no dependencies beyond stdlib)
        |
        +------------------------+------------------------+
        v                        v                        v
Phase 3a: Evidence Engine   Phase 3b: Market            Phase 3c: System
  (shared/ only, plus own     Intelligence Engine         Reliability Engine
  market-data ingestion)      (shared/ only, plus own      (core) -- shared/
                               news/calendar ingestion)     + Phase 1's telemetry
        |                        |
        +-----------+------------+
                    v
Phase 4a: Strategy Engine       Phase 4b: Validation (offline harness)
  (Evidence Engine's score/       (Evidence Engine's models.py +
   structure + Market              Strategy Engine's playbook
   Intelligence's entry gate)       interface, as each lands)
        |
        v
Phase 5: Portfolio Statistical Risk Engine
  (Strategy Engine's TradeIdea, Evidence Engine's confidence,
   Market Intelligence's Pair Safety Score, PhantomBridgeEA's
   position telemetry for correlation/exposure/heat)
        |
        v
Phase 6: Prop Firm Compliance Engine
  (Risk Engine's SizingRecommendation, PhantomBridgeEA's account
   state for drawdown/trade-count tracking)
        |
        v
   [full live decision chain complete -- still gated on §0 for any
    real execution, and on this task's own "no implementation until
    approved" constraint for even beginning to build it]
        |
        v
Phase 7: Research & Learning Engine
  (needs real trade history from the completed chain above)
        |
        v
Phase 8: System Reliability Engine (full extension)
  (broker_connectivity/latency_monitor/auto_recovery deepen once
   every other component exists to monitor)
```

Validation (Phase 4b) is not a one-time phase — see §6.

## 5. Build phases — scope, dependencies, interfaces, test plans

Each phase below assumes the prior phase's exit criteria are met and
that §0's gate has cleared. None of this begins until both are true.

### Phase 2 — `phantom/shared/`

- **Scope:** exactly the locked contents in §2. No engine logic.
- **Dependencies:** none beyond the Python standard library.
- **Interfaces:** every other component imports `Pair`, `Direction`,
  `Timeframe`, `Price`, `Volume`, `Money`, `Clock`, `SCHEMA_VERSION`,
  and whatever shared enums/value objects/constants/error types are
  added, from `phantom.shared` — never redefines its own.
- **Test plan:** pure unit tests for every value type's equality/
  precision/immutability; the structural-boundary test in §2 (no
  business logic, no cross-package imports, no decision-shaped
  function names); no integration tests needed (nothing to integrate
  with yet).
- **Exit criteria:** 100% unit coverage on value-type behavior; the
  structural-boundary test passes; no other package yet depends on it
  (this phase produces no observable system behavior on its own).

### Phase 3a — Evidence Engine

- **Scope:** full file list per `PHANTOM_FINAL_ARCHITECTURE.md`
  (`market_data_source.py`, `market_structure.py`, `regime.py`,
  `indicators.py`, `scorer.py`, `confidence.py`, `evidence_engine.py`,
  plus `models.py`/`config.py`/`logging_sink.py`/`metrics.py`).
- **Dependencies:** `phantom/shared/` only, plus its own market-data
  ingestion (no dependency on PhantomBridgeEA's telemetry — price
  history is a different data domain, per the architecture freeze's
  §13 finding #4).
- **Interfaces:**
  `evidence_engine.get_pair_evidence(pair: Pair, now: Clock) ->
  PairEvidence` where `PairEvidence` carries the 0–100 `PairScore`,
  the `PairConfidence` explanation, and the underlying structure/
  regime findings. This is the *only* function Strategy Engine (Phase
  4a) and Risk Engine (Phase 5) are permitted to call into this
  package through.
- **Test plan:** deterministic unit tests per indicator/structure
  detector against fixed historical fixtures (same score in, same
  score out, every run — no floating nondeterminism); a
  structural-boundary test asserting no other package under
  `phantom/` implements its own indicator/structure logic (enforces
  "no duplicate indicators" from the lock); integration test producing
  a full `PairEvidence` end to end for a fixture pair.
- **Exit criteria:** every enabled pair produces a score + explanation
  from historical fixture data with no nondeterminism across repeated
  runs; boundary test green.

### Phase 3b — Market Intelligence Engine

- **Scope:** full file list per §3.2 above (adds
  `market_impact_score.py` to the prior freeze's list).
- **Dependencies:** `phantom/shared/` only, plus its own news/calendar
  ingestion.
- **Interfaces:**
  `intelligence_engine.get_pair_intelligence(pair, now) ->
  PairIntelligence` (carrying `NewsScore`, `MarketImpactScore`,
  `PairSafetyScore`) and, separately,
  `intelligence_engine.get_entry_gate(pair, now) -> EntryGateDecision`
  per §3.2 — two distinct calls, because the gate is a mandatory
  precondition check and the scores are inputs to sizing; conflating
  them into one call would let a caller accidentally use the gate
  value as a score or vice versa.
- **Test plan:** unit tests per event classification/quality-scoring
  module against fixture calendars; a dedicated test suite asserting
  `get_entry_gate` returns `BLOCKED_*` for every fixture event the lock
  names as high-impact/critical (CPI, NFP, rate decisions, etc.) and
  `ALLOWED` otherwise; structural-boundary test asserting no other
  package parses news/calendar data independently (enforces "no
  duplicate news processing").
- **Exit criteria:** entry-gate fixture tests fully green (this is the
  component whose correctness Strategy Engine will structurally trust
  without re-checking).

### Phase 3c — System Reliability Engine (core)

- **Scope:** `watchdog.py`, `kill_switch.py`, `logging.py`,
  `health_monitor.py` (basic form). `broker_connectivity.py`,
  `latency_monitor.py`, `auto_recovery.py` deepen in Phase 8 once more
  components exist to watch.
- **Dependencies:** `phantom/shared/`, plus PhantomBridgeEA's already-
  existing telemetry (`ConnectionHealth`, structured logs) for the
  connectivity piece.
- **Interfaces:** `reliability_engine.kill_switch.trip(reason) ->
  None` — the one system-wide halt authority above PhantomBridgeEA's
  own transport-level `EmergencyStopState`, per the architecture
  freeze's §13 item 5 distinction; every later live component (Phases
  4a–7) must check `reliability_engine.is_halted()` as a precondition,
  the same pattern as Market Intelligence's entry gate.
- **Test plan:** unit tests for kill-switch state transitions; an
  integration test proving that tripping the kill switch halts a
  fixture caller regardless of what that caller's own internal state
  says (mirrors Phase 1's own emergency-stop test pattern).
- **Exit criteria:** kill switch demonstrably halts a stub caller; log
  aggregation receiving events from at least PhantomBridgeEA's existing
  `logging_sink.py` stream end to end.

### Phase 4a — Strategy Engine

- **Scope:** full file list per the architecture freeze
  (`playbook.py`, five `playbooks/*.py` files, `registry.py`,
  `selector.py`, `strategy_engine.py`).
- **Dependencies:** Evidence Engine (Phase 3a) for `PairEvidence`;
  Market Intelligence Engine (Phase 3b) for `get_entry_gate`; System
  Reliability Engine (Phase 3c) for `is_halted()`.
- **Interfaces:** `strategy_engine.evaluate(pair) -> Optional[TradeIdea]`
  — internally: check `is_halted()` first, then `get_entry_gate(pair,
  now)`, then call `registry.applicable_playbooks(evidence)` and let
  exactly one playbook (or none) produce a `TradeIdea`; never sizes,
  never executes.
- **Test plan:** one fixture-driven unit test suite per playbook
  (given known Evidence Engine fixture output, does the playbook fire
  correctly and only when its own pattern is actually present — no
  playbook fires on another playbook's pattern, enforcing "no
  duplicate signals" from the Charter's Strategy philosophy);
  `registry.py` auto-discovery test (new playbook file appears in the
  registry without a hand-edited list, matching the drift-risk lesson
  already on record); integration test proving a `BLOCKED_*` entry
  gate suppresses idea generation even when a playbook's pattern is
  otherwise present.
- **Exit criteria:** all five playbooks individually verified against
  fixtures; entry-gate suppression integration test green.

### Phase 4b — Validation (offline harness), standing alongside 4a

- **Scope:** full file list per the architecture freeze
  (`backtest_engine.py`, `replay_engine.py`, `forward_test.py`,
  `performance_reports.py`, `strategy_comparison.py`, `runner.py`).
- **Dependencies:** Evidence Engine's `models.py` (Phase 3a) and
  Strategy Engine's playbook interface (Phase 4a), consumed as each
  playbook lands — this phase is not sequenced strictly after 4a
  completes; its harness can and should exist before all five
  playbooks are done, so each playbook is backtestable the moment it's
  written, per the architecture freeze's own rationale for why
  Validation exists (§11).
- **Interfaces:** `backtest_engine.run(strategy_kind, historical_range)
  -> BacktestResult` — imports only `models.py` types from every live
  component it evaluates, never their `engine.py`/orchestrator
  modules, keeping the offline/online boundary structurally
  enforceable.
- **Test plan:** a structural-boundary test (mirrors Phase 1's
  pattern) asserting no file under `phantom/validation/` imports any
  live component's orchestrator; a known-outcome regression test (a
  fixture historical window with a hand-verified expected backtest
  result, so a future change to `backtest_engine.py` itself is
  caught).
- **Exit criteria:** at least one playbook backtestable end to end
  against fixture history with a stable, reproducible result.

### Phase 5 — Portfolio Statistical Risk Engine

- **Scope:** full file list per the architecture freeze, plus the
  Risk Schedule (§3.1) implemented in `confidence_scaling.py`.
- **Dependencies:** Strategy Engine's `TradeIdea` (Phase 4a); Evidence
  Engine's confidence score (Phase 3a); Market Intelligence's
  `PairSafetyScore` (Phase 3b); PhantomBridgeEA's position telemetry
  (Phase 1, already built) for `correlation.py`/`exposure.py`/
  `portfolio_heat.py`.
- **Interfaces:** `risk_engine.evaluate(idea: TradeIdea) ->
  Union[SizingRecommendation, RiskVeto]` — the veto path is used for
  sub-65 scores per the Risk Schedule and for statistical grounds
  (correlation/heat/ruin-probability breach); `SizingRecommendation`
  is a value type structurally incapable of being increased by any
  downstream consumer (no public setter/mutator on it — enforced at
  the type level, not by convention, per the freeze's §14
  recommendation #3).
- **Test plan:** unit tests per statistical module (Monte Carlo/VaR/
  CVaR/risk-of-ruin/Kelly/expectancy/Sharpe/Sortino) against
  fixed-seed inputs with hand-verified expected outputs; a Risk
  Schedule table test asserting every score band 65–100 maps to
  exactly the tier in §3.1 and every score below 65 vetoes; a
  structural-boundary test asserting `phantom/risk/` is the only
  package computing Sharpe/Sortino/expectancy (enforces "no duplicate
  portfolio calculations," pre-committing the reuse contract Research
  & Learning Engine (Phase 7) must honor).
- **Exit criteria:** Risk Schedule test green across all eight bands;
  Monte Carlo/VaR determinism confirmed under a fixed seed (no run-to-
  run variance for the same inputs).

### Phase 6 — Prop Firm Compliance Engine

- **Scope:** full file list per the architecture freeze.
- **Dependencies:** Risk Engine's `SizingRecommendation` (Phase 5);
  PhantomBridgeEA's account state (balance/equity history, trade
  count) for drawdown/day/trade-limit tracking (Phase 1, already
  built).
- **Interfaces:** `compliance_engine.evaluate(sizing:
  SizingRecommendation) -> Union[TradeCommand, ComplianceRejection]`
  — the success path produces exactly the `phantom.bridge.models.
  TradeCommand`/`CommandKind` shape Phase 1's `BridgeEngine.
  submit_command` already accepts; this is the real, concrete
  integration point back into the already-built bridge, not a new
  execution path (enforces "one execution authority" — Compliance
  Engine never talks to MT5 itself, it only ever produces the same
  command shape Phase 1 already validates and queues).
- **Test plan:** unit tests per rule (`daily_drawdown.py`,
  `total_drawdown.py`, `trading_day_rules.py`, `position_limits.py`,
  `daily_trade_limits.py`, `emergency_lockout.py`) against fixture
  account histories, including at-the-boundary cases (exactly at the
  limit, one cent/one trade over); an integration test proving
  Compliance Engine can only shrink or reject a `SizingRecommendation`,
  never enlarge it (feeds the type-level constraint from Phase 5
  directly); an end-to-end integration test submitting a Compliance-
  approved `TradeCommand` into a real (test) `phantom.bridge.
  BridgeEngine` instance and confirming it queues correctly — this is
  the first point in the roadmap where a new component's output is
  proven compatible with Phase 1's actual, already-built code, not
  just a fixture.
- **Exit criteria:** full chain (Evidence -> Strategy -> Intelligence
  gate -> Risk -> Compliance -> `BridgeEngine.submit_command`) proven
  end to end against fixture data, still never touching a real MT5
  terminal. This is the "full live decision chain complete" milestone
  in §4's dependency graph.

### Phase 7 — Research & Learning Engine

- **Scope:** full file list per the architecture freeze.
- **Dependencies:** real (or paper/demo) trade history produced by the
  completed chain through Phase 6, plus Risk Engine's stored rolling
  stats (Phase 5) for `performance_attribution.py` per the reuse
  contract locked in the architecture freeze §11/§13/§14.
- **Interfaces:** `research_engine.record_trade(decision_chain_snapshot,
  execution_report) -> None` (write path, called once per completed
  trade) and `research_engine.recommendations() ->
  Tuple[Recommendation, ...]` (the only read path anything outside
  this component is permitted — never a write path back into Strategy
  Engine's selector or Risk Engine's sizing, enforced structurally).
- **Test plan:** a structural-boundary test asserting no file under
  `phantom/research/` recomputes Sharpe/Sortino/expectancy itself
  (must import `phantom/risk`'s stored values only — this is the
  test the Phase 5 exit criteria promised); a structural test asserting
  no file under `phantom/research/` is ever imported by
  `phantom/strategy/` or `phantom/risk/` (one-directional data flow,
  enforcing "advisory only, never modifies live trading").
- **Exit criteria:** both structural tests green; at least one
  simulated weekly review produced end to end from fixture trade
  history.

### Phase 8 — System Reliability Engine (full extension)

- **Scope:** deepen `broker_connectivity.py`, `latency_monitor.py`,
  `auto_recovery.py` now that every component in the live chain
  exists to monitor.
- **Dependencies:** every prior phase (this component watches all of
  them; it depends on their existence, not their internals).
- **Interfaces:** unchanged public surface from Phase 3c
  (`kill_switch.trip`, `is_halted`); internally, `latency_monitor.py`
  now measures the full command round trip (Strategy idea ->
  Compliance approval -> `submit_command` -> PhantomBridgeEA's
  `ExecutionReport`) rather than only Phase 1's own bridge latency.
- **Test plan:** end-to-end latency measurement test against the full
  fixture chain built through Phase 7; auto-recovery scenario tests
  for each named recoverable failure mode identified across the
  bridge's own troubleshooting guide
  (`docs/mt5_validation/06_troubleshooting_guide.md`) that has a
  defined recovery action (e.g. reconnect after a bridge outage
  shorter than fail-closed timeout).
- **Exit criteria:** full-chain latency dashboarded; at least one
  auto-recovery scenario demonstrated against a simulated fault.

## 6. Standing processes (not one-time phases)

- **Validation is continuous, not a phase that ends.** Every future
  change to a Strategy Engine playbook, a Risk Engine parameter, or a
  Compliance Engine rule set must pass through Phase 4b's harness
  before it is proposed for the live path — this repeats forever, per
  the architecture freeze's own rationale for why Validation exists.
- **System Reliability Engine's monitoring is continuous** from Phase
  3c onward, deepening at Phase 8, never "finished."
- **Research & Learning Engine's reviews are continuous** (weekly/
  monthly) from Phase 7 onward.

## 6.1 Architecture Hardening amendments (post-Red-Team-Audit)

This roadmap is amended as follows — see `PHANTOM_ARCHITECTURE_HARDENING.md`
for the full rationale; this section only states the build-order
deltas.

- **New: Phase 1R — Bridge Concurrency Remediation (blocked on separate
  approval).** Closes Red Team Audit Finding 5.1. Adds locking to
  `phantom/bridge/command_queue.py` and `connection_health.py` per
  `docs/specs/09_bridge_concurrency_hardening.md`. This is a fix to
  already-built, already-frozen Phase 1 code — it does not begin as
  part of this hardening pass, requires its own explicit authorization
  the same way any other change to `PhantomBridgeEA` would, and must
  pass the full existing 85-test Phase 1 regression suite unchanged
  afterward. It may happen at any point relative to Phase 2 onward, but
  must be complete before Phase 6's real (non-fixture) bridge
  integration testing.
- **New: Phase 2R — `phantom/runtime/runtime.py` skeleton, built
  incrementally.** Runtime's sequencing logic can be stubbed against
  Evidence Engine and Strategy Engine as soon as both exist (alongside
  Phase 4a), using mock Risk/Compliance/Bridge/Research/Reliability
  calls, and wired to each real component as it lands — Market
  Intelligence Engine's gate check (Phase 3b), Risk Engine's
  serialized `evaluate()` calls (Phase 5), Compliance Engine and the
  real `BridgeEngine.submit_command` integration (Phase 6), Research &
  Learning Engine's observer call (Phase 7), and Reliability's
  `is_halted()`/`record_cycle` (Phase 3c core, then Phase 8 extension).
  Runtime's own exit criteria (full sequencing test, determinism test,
  every rejection-propagation test) are only fully met once Phase 6 is
  done — this replaces Phase 6's prior exit criterion ("full chain
  proven end to end") with the equivalent, now-named criterion "Runtime
  module proven end to end," closing Red Team Audit Finding 2.1.
- **Phase 3c (System Reliability Engine core) scope addition:**
  `operator_auth.py` (authenticate/authorize/audit) is now part of this
  phase's core scope, not deferred — Compliance Engine's emergency
  lockout and Market Intelligence Engine's peg/policy block both depend
  on it existing before their own clear-paths can be tested (closes
  Finding 17.1).
- **Phase 5 (Risk Engine) exit criteria addition:** the pending-exposure
  reservation ledger and minimum-sample-size gate
  (`docs/specs/03_portfolio_statistical_risk_engine.md` §3/§6.1) are now
  part of Phase 5's own exit criteria, not a later addition — closes
  Findings 2.2 and 7.1 at the same phase they were always going to be
  built, rather than as a retrofit.
- **Phase 6 (Compliance Engine) scope addition:** the full ten-category
  `ComplianceRuleSet` (`docs/specs/05_prop_firm_compliance_engine.md`
  §"FTMO configuration model") replaces the original five-category
  scope — closes Findings 4.1, 11.1–11.4 at the same phase, not a
  retrofit.

## 7. Rule for adding anything not already named here

Per the lock's own instruction ("Do not add new engines, packages, or
layers unless explicitly approved"), any file, submodule, or shared
type not already named in `PHANTOM_FINAL_ARCHITECTURE.md` or this
roadmap requires the same explicit-approval step every prior addition
in this session has gone through — including the shared-module
constants/enums/value-objects/error-types §2 leaves open-ended ("as
needed"): a second component must have an actual, demonstrated need
before it's added, and it is added to `phantom/shared/` as a value
type only, never as logic.

## Stop condition

This is the complete implementation roadmap requested: build order,
dependencies, interfaces, and test plans for every phase. No
production code was written. No new engine, package, or layer was
introduced beyond what was already locked. Implementation of Phase 2
onward does not begin until the three gates in §0 are satisfied and a
separate, explicit go-ahead is given.
