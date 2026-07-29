# ADR-031 — Runtime Orchestrator, Configuration Management, Trading Profiles

Status: Accepted

Acceptance Date: 2026-07-10

Accepted By: Software Architect / Titan Protocol Engineering Council (full
spec supplied in one message, per the `ADR-029`/`ADR-030` "complete
spec accepted in one pass" precedent).

Owner: Software Architect (cross-cutting orchestration, the same
rationale `ADR-026` §0 already applied to itself)

Reviewed by: Minimal Change Engineer (mandatory — this ADR's Hard Rule
is entirely about NOT adding logic; that discipline is this role's own
charter), Test Results Analyzer (Consulted — owns the adjacent
`ADR-018` Replay & Certification Engine's determinism guarantees, which
this ADR's own determinism requirement mirrors)

Date: 2026-07-10

Depends on: `ADR-024` through `ADR-030` (all Accepted — every engine
this ADR sequences), `ADR-026` Amendment 1 (Accepted, same session —
`StrategySnapshot.trade_intent` is what makes a real Bridge handoff
possible; see §3), `ADR-011-watchdog-recovery.md` (Accepted,
`phantom_pipeline` lineage — disclosed overlap, not reused, §0)

---

# 0. Relationship to prior work (disclosure, not duplication)

- **`docs/specs/00_runtime_orchestrator.md`** is a pre-existing
  specification-only document for an *earlier*, superseded pipeline
  shape (`Evidence → Strategy → Market Intelligence gate → Risk →
  Compliance → Bridge`, with method names like `get_pair_evidence`,
  `get_entry_gate`, `submit_command` that predate every engine actually
  built this session). Its **ideas** are reused — one orchestration
  point, fail-closed halt handling, per-pair isolation, a `CycleReport`
  concept, "no decision-shaped name" as the structural test — but its
  **literal interfaces are not**, since they don't match any engine
  this session actually built. This ADR supersedes it as the
  authoritative Runtime specification for the six engines built under
  `ADR-024`-`ADR-030`.
- **`ADR-011` Watchdog (Accepted, `phantom_pipeline` lineage)** already
  owns exactly the "detect engine/runtime/snapshot/bridge timeout,
  restart bounded infrastructure actions, never bypass Compliance"
  mission this ADR's own Watchdog-integration requirement describes.
  **It is not imported.** Every `titan_protocol/` package built this session
  (`ADR-024` through `ADR-030`) enforces, via its own architecture
  test, "zero import of `phantom_pipeline`" — importing
  `phantom_pipeline.watchdog` here would be the first exception to a
  rule this session has applied without exception six times running,
  and would make a reference-only tree (`ADR-001`'s own resolution: `
  phantom_pipeline` is "mined for proven ... mechanisms," never a
  running authority) into a live dependency of the pipeline that
  resolution built. Instead, `titan_protocol/runtime/watchdog_integration.py`
  is a **fresh, minimal module mirroring `ADR-011`'s vocabulary**
  (component/kind/timeout-detection shape) without importing it. A
  future ADR could formally bridge the two trees; not assumed here.
- **No legacy runtime orchestrator exists in `titan_protocol/`.** Designed
  from first principles for the six engines this session built,
  reusing their already-accepted, real public interfaces — never a
  second implementation of anything they already compute.

---

# Pipeline position

**The Runtime Orchestrator is the live coordinator — the first
component in this session's `titan_protocol/` build that is actually wired
end-to-end.** Trading Profiles and Configuration Management are its
supporting configuration surface; neither computes a trading decision.

---

# 1. Mission

**The Runtime Orchestrator is the ONLY live coordinator. It owns ZERO
trading logic. It executes the already-approved pipeline in the
correct order.**

---

# 2. Absolute Rule (Hard Rules)

Runtime MUST NEVER:

1. Generate signals.
2. Calculate evidence.
3. Calculate risk.
4. Make compliance decisions.
5. Override any engine.

It is an orchestrator only — verified structurally: no function in
`titan_protocol/runtime/` contains a decision-shaped name, and every
conditional branch in the sequencing module is an equality/membership
check against a value another engine's public interface already
returned (mirrors `docs/specs/00_runtime_orchestrator.md` §7's test
design, restated for the real six-engine pipeline).

---

# 3. Pipeline (exactly)

```
Evidence Engine
    -> Market Intelligence Engine
    -> Strategy Engine
    -> Portfolio Statistical Risk Engine
    -> Compliance Engine
    -> Bridge
```

Research & Learning Engine receives a **read-only copy** of each
cycle's outcome (never invoked synchronously inside the cycle — it
operates on aggregated history at its own cadence, `ADR-029` §1;
Runtime only appends a `ClosedTrade`-shaped record for it to consume
later, never calls `ResearchEngine.evaluate()` itself). **Validation
Engine never participates in live execution** — it has no runtime
handle at all; the sequencing module does not import
`titan_protocol.validation_engine`.

Per pair, per cycle, using each engine's real `evaluate()`/
`evaluate_snapshot()` signature (`ADR-024`-`ADR-028`, unchanged):

1. `EvidenceEngine.evaluate_snapshot(pair, bars, now) -> EvidenceSnapshot`
2. `MarketIntelligenceEngine.evaluate(pair, evidence.report, events, current_spread, average_spread, market_safety_inputs, now) -> MarketIntelligenceSnapshot`
3. `StrategyEngine.evaluate(pair, evidence, market_intelligence, now) -> StrategySnapshot`
   — carries `trade_intent` (`ADR-026` Amendment 1); Runtime never
   computes or infers one.
4. `RiskEngine.evaluate(pair, evidence, market_intelligence, strategy, portfolio_state, trade_history, now) -> RiskSnapshot`
5. `ComplianceEngine.evaluate(pair, evidence, market_intelligence, strategy, risk, portfolio_state, account_state, now) -> ComplianceSnapshot`
6. If `compliance.ready_for_bridge`: construct a `TradeCommand`
   (`titan_protocol.bridge.models`) and call a caller-supplied
   `bridge_submit(command, now) -> Optional[ErrorCode]` — **Runtime
   never constructs a `BridgeEngine` itself** (connection lifecycle is
   out of scope for an orchestrator; the caller wires in the bound
   `BridgeEngine.submit_command` method it already owns). If
   `compliance.decision is REJECT`, no `TradeCommand` is ever
   constructed.

**Any stage returning a rejection/no-qualification/veto stops that
pair's cycle immediately — no later stage is called** (mirrors
`docs/specs/00_runtime_orchestrator.md` §5's early-exit discipline,
restated for the real engines):

- `strategy.rejected` → cycle ends after Strategy; Risk/Compliance/
  Bridge never called for this pair this cycle.
- `not risk.approved` → cycle ends after Risk; Compliance/Bridge never
  called.
- `compliance.decision is REJECT` → cycle ends after Compliance;
  Bridge never called.
- A non-`None` `ErrorCode` from `bridge_submit` → recorded, cycle ends.

## `TradeCommand` construction (the one place arithmetic, not a
## decision, happens)

- `command_kind`: `CommandKind.BUY` if `strategy.trade_intent is
  TradeIntent.BUY`, `CommandKind.SELL` if `TradeIntent.SELL` — a
  direct restatement of `ADR-026` Amendment 1's field, never a new
  choice. (`TradeIntent.NONE` cannot reach this point: it only occurs
  when `strategy.rejected`, which already ended the cycle.)
- `volume`: `risk.recommended_position_size.lot_size * (1 -
  compliance.reduction_pct / 100)` — scaling an already-computed lot
  size by an already-computed reduction percentage (`ADR-028`'s own
  `ComplianceSnapshot.reduction_pct` field). This is unit conversion
  over two numbers two other engines already produced, not a new
  sizing decision — Runtime chooses neither the lot size nor the
  reduction ratio.
- `stop_loss` / `take_profit`: `None`. No engine in this pipeline
  currently computes an absolute stop-loss/take-profit *price* (Risk
  Engine's `PositionSizeRecommendation` expresses risk in R-multiples
  and lot size only) — `titan_protocol.bridge.validation.
  check_stop_loss_take_profit` already accepts `None` for both
  (verified: it only rejects a *non-None* value `<= 0`), so this is a
  valid, disclosed scope boundary, not an invented value. A future
  Position Manager stage (`ADR-001`'s own forward-declared, unbuilt
  stage) is the natural owner of absolute price levels if the Council
  wants them added.
- `correlation_id`: `f"{cycle_id}:{pair}"` — deterministic, derived
  from the cycle identifier Runtime itself assigns, never `uuid4()`/
  `random` (Performance §9's determinism requirement).
- `magic_number`, `max_slippage_points`: operator-configured constants
  (`RuntimeConfig`), never computed.

---

# 4. Trading Profiles

Config-only, per the task's own list: London Conservative, London
Aggressive, New York Conservative, New York Aggressive, London + NY,
Custom. Each profile controls Trading Window, Allowed Pairs, Allowed
Strategies, News Policy, Risk Profile, Session Rules, Compliance
Rules — **no duplicate logic**: "Risk Profile"/"Compliance Rules" are
references to an existing `RiskEngineConfig`/`ComplianceEngineConfig`
(or a named `rule_profile_name` already supported by `ADR-028`), never
a second risk/compliance implementation. "News Policy" is a reference
to `MarketIntelligenceConfig` fields already governing blackout
windows (`ADR-025`), never a third news filter.

---

# 5. Configuration Versioning

Every `TradingProfile` carries `profile_id`, `version`, `created_at`,
`modified_at`, `author`, `description` (immutable once constructed —
a new version is a new object, never a mutated field, mirroring every
other engine's config-is-a-frozen-dataclass discipline this session).

Every `RuntimeAuditRecord` (§8) carries `configuration_version`,
`profile_id`, and the **engine versions** already exposed by each
package (`EVIDENCE_ENGINE_VERSION`, `MARKET_INTELLIGENCE_ENGINE_VERSION`,
`STRATEGY_ENGINE_VERSION`, `RISK_ENGINE_VERSION`,
`COMPLIANCE_ENGINE_VERSION` — all already-exported constants, never
invented here).

---

# 6. `RuntimeContext` (immutable)

One per cycle, per pair, containing exactly: `EvidenceSnapshot`,
`MarketIntelligenceSnapshot`, `StrategySnapshot`, `RiskSnapshot`,
`ComplianceSnapshot`, `PortfolioState`, `AccountState`,
`TradingProfile`, `Clock` (the `now` used for this cycle),
`correlation_reservations` (the `Tuple[str, ...]` of Risk Engine's own
already-issued `reservation_id`s relevant to this cycle — reusing
`ADR-027`'s existing `ReservationLedger` mechanism, never a second
reservation system). Frozen dataclass; no engine mutates it — each
stage receives only the specific fields its own `evaluate()` signature
already required before this ADR existed.

---

# 7. Observability

Every cycle records: start, end, duration, decision, rejected stage
(if any), approved stage(s) reached, execution time per stage, reason.
No silent failures — every early exit (§3) is recorded with the exact
originating stage's own reason/rejection type, never a generic
"skipped."

---

# 8. Error handling — Fail Closed

| Condition | Behavior |
|---|---|
| Unknown engine state (an engine raises, or returns a type Runtime doesn't recognize) | Reject — that pair's cycle records a failure outcome; other pairs/cycles unaffected (per-pair isolation, mirrors `docs/specs/00_runtime_orchestrator.md` §12) |
| Missing snapshot (a required upstream snapshot is `None` where a stage's signature requires one) | Reject — never substituted with a default/placeholder snapshot |
| Invalid configuration | Reject at startup (§10) before any cycle runs; a profile that fails validation never reaches `run_cycle` |

Never continues on partial data — a `RuntimeAuditRecord` for a failed
cycle is still produced (Observability §7), but no `TradeCommand` is
ever constructed from an incomplete chain.

---

# 9. Watchdog integration

`titan_protocol/runtime/watchdog_integration.py` (fresh module, §0) detects
four timeout kinds — Engine, Runtime, Snapshot, Bridge — by comparing
each stage's recorded duration (§7) against `RuntimeConfig`'s
configured thresholds, and exposes a bounded, explicit
`APPROVED_RESTART_COMPONENTS` allow-list (Evidence/Market
Intelligence/Strategy/Risk engine instances only — **Compliance Engine
is never in this list, structurally enforced by a dedicated test**,
satisfying "never bypass Compliance" by construction rather than by
runtime check). Restarting a component means constructing a fresh
engine instance (every engine this session built is stateless/cheap to
reconstruct, `ADR-024`-`ADR-028`'s own statelessness guarantees) —
never a partial reset, never applied to Bridge or Compliance.

---

# 10. Performance

Target: 28 pairs, sub-250ms cycle, concurrent-safe, deterministic, no
duplicate calculations. Per-pair evaluation shares no mutable state
(mirrors `docs/specs/00_runtime_orchestrator.md` §11's own
parallelization allowance) — pairs may be evaluated concurrently
without changing this ADR's within-pair strict ordering (§3).

---

# 11. Configuration validation (startup)

Before any cycle runs: profiles valid (well-formed trading window,
non-empty allowed-pairs unless deliberately empty, allowed strategies
are real `StrategyId` values), strategy eligibility valid (every
allowed pair intersects that strategy's own `StrategyEngineConfig`
approved-pair set — a profile cannot claim eligibility a strategy
itself doesn't grant), pairs valid (recognized `BASEQUOTE` 6-character
format), sessions valid (session rules reference real `SessionName`
values), news configuration valid (blackout window minutes are
non-negative), risk configuration valid (`RiskEngineConfig` thresholds
positive where required), compliance configuration valid (the
profile's referenced `rule_profile_name` exists in
`ComplianceEngineConfig.rule_profiles`). An invalid profile is rejected
before trading — never silently coerced or partially applied.

---

# 12. Audit

Every cycle produces a `RuntimeAuditRecord`: cycle ID, profile,
evidence ID (the pair + `generated_at` this cycle's `EvidenceSnapshot`
was produced from), selected strategy (if any), risk decision,
compliance decision, bridge decision, timing, reasons — plus §5's
configuration/engine version fields.

---

# 13. Testing

Integration, Runtime, Configuration, Concurrency, Stress, Failover,
Recovery, Performance, Architecture, Regression — the task's own 10
categories.

---

# 14. Acceptance criteria

- ✓ No decision-shaped name anywhere in `titan_protocol/runtime/` (§2, AST test).
- ✓ Every early exit stops the cycle immediately, no later stage called (§3).
- ✓ `TradeCommand` construction uses only already-computed values;
  `stop_loss`/`take_profit` disclosed as `None` this phase (§3).
- ✓ Zero import of `phantom_pipeline` (§0, §9).
- ✓ Compliance Engine never appears in the Watchdog restart allow-list (§9).
- ✓ Fail-closed on unknown state/missing snapshot/invalid config (§8).
- ✓ Deterministic: identical inputs (including a fixed `Clock`)
  produce an identical `RuntimeAuditRecord` on every run.

Per `ADR-001` and `CLAUDE.md` §1.10, accepted above in the same single
pass `ADR-029`/`ADR-030` used, since the full spec arrived in one
message.

---

# Amendment 1 (2026-07-29, Status: **Proposed** — not yet Accepted) — ORB Cross-Pair Opportunity-Selection Pipeline Compatibility

**This amendment is Proposed only. It does not change ADR-031's own
overall Accepted status for §0–§14 above, none of which this amendment
alters in substance (see "Unchanged governance" below). It requires its
own independent governance review and Acceptance, per this repository's
established RPI/amendment precedent (`ADR-026` Amendment 1, `ADR-036`
Amendment 1), before it takes effect or authorizes anything.**

**Why this amendment exists:** `ADR-037-orb-cross-pair-session-
opportunity-selection.md` (Accepted, commit `527e6ba`) designed a
cross-pair ORB opportunity-selection architecture whose own governance
chain concluded that implementation cannot begin until "a future,
dedicated ADR-031 amendment... formalizing the corrected one-pass-
front-half/terminal-outcome/completeness/grouping/selection/winner-
only-back-half sequencing" is itself independently researched,
governed, and Accepted (ADR-037 §5, §17). A dedicated Research pass
(`docs/plans/adr-031-pipeline-amendment-research.md`, commit `489eb8a`)
traced ADR-031's current text and Runtime's actual source against
ADR-037's Accepted contract and found the incompatibility is not
confined to §3: §3, §6, §7, §8, §12, and §14 each require an addition;
§0, Pipeline position, §1, §2, §4, §5, §9, §10, §11, and §13 require
none. This amendment implements exactly that surface, independently
re-confirmed against source for this drafting pass (`run_cycle()`/
`run_cycle_for_pair()` in `titan_protocol/runtime/engine.py`; `CycleStage`/
`CycleOutcome`/`RuntimeAuditRecord` in `titan_protocol/runtime/models.py`;
`tests/titan_protocol/runtime/test_architecture.py`) — no discrepancy
between the Research and current source was found; nothing here departs
from the Research's own findings.

## 1. Unchanged governance (stated explicitly, not left implicit)

The following require **no textual change** and are **not reopened** by
this amendment:

- **§0** (relationship to prior work) — unaffected.
- **Pipeline position** — unaffected; the new engine this amendment
  authorizes is neither Runtime, Trading Profiles, nor Configuration
  Management, and computes no trading decision any of those three own.
- **§1** ("Runtime is the ONLY live coordinator. It owns ZERO trading
  logic.") — remains true under this amendment; see §2 below.
- **§2 Hard Rules — byte-for-byte unchanged.** Every Runtime
  responsibility this amendment authorizes (executing already-approved
  engines unmodified; collecting already-produced results; counting
  terminal outcomes against a frozen, configuration-derived expected
  value; grouping candidates by an already-produced identity value,
  never a re-derived one; releasing or terminating a candidate via an
  equality/membership check against the Opportunity Selection Engine's
  own returned result) reduces to execution, collection, counting,
  grouping, and comparison — never generation, calculation, ranking, or
  override, which is exactly what §2 already forbids. No new exception
  to Hard Rule 1–5 is created. The Opportunity Selection Engine, not
  Runtime, owns the winner decision, exactly as ADR-037 §4/§5 already
  establish and as this amendment's §2 (below) restates without
  weakening.
- **§4** (Trading Profiles, config-only) — unaffected; the enabled-
  opportunity-window configuration surface ADR-037 §8/§11 describes is
  its own, separate configuration concept, not a fourth risk/compliance/
  news implementation of the kind §4 already forbids duplicating.
- **§5** (Configuration Versioning) — unaffected; if the new engine
  publishes a version constant, it slots into the existing pattern
  without amendment.
- **§9** (Watchdog integration) — **not amended.** Whether the new
  engine is ever added to `APPROVED_RESTART_COMPONENTS` is left as an
  explicit future Plan-level question (see §7 below) — the evidence
  gathered for this amendment does not establish that §9's text itself
  requires a change, and none is made.
- **§10** (Performance: sub-250ms, concurrent-safe, deterministic, no
  duplicate calculations) — not contradicted, and arguably reinforced:
  this amendment's own "front half executes at most once per pair per
  cycle" requirement (§4 below) is precisely what "no duplicate
  calculations" already demands, and §10's existing allowance for
  concurrent per-pair evaluation is compatible with (not weakened by) a
  join/barrier point of the kind this amendment describes.
- **§11** (Configuration validation at startup) — not amended. `ADR-036`
  Amendment 1 already established `validate_profile()` as the open-
  ended, extensible architectural home for cross-component, deployment-
  profile-level fail-closed checks, citing this same §11 as precedent
  without §11 itself needing to enumerate every check. ADR-037's own
  enabled-sessions/Gate-A/Gate-B structural-readiness invariant (ADR-037
  §11) is another instance of that already-established pattern, not a
  new kind of clause this amendment must add to ADR-031.
- **§13** (Testing, 10 categories) — unaffected; new tests for the
  barrier logic populate existing categories (Concurrency, Failover,
  Recovery, Architecture, Regression) without renaming or adding a
  category.

## 2. Pipeline contract (amends §3)

**Every Runtime pair continues through its ordinary front-half
evaluation — Evidence → Market Intelligence → Strategy — exactly once
per Runtime cycle, using the same unmodified `evaluate()`/
`evaluate_snapshot()` signatures §3 already specifies.** This is
unchanged for every pair, including every pair that is not tracked for
cross-pair ORB completeness at all.

**The ORB completeness-tracking universe** is the frozen intersection
ADR-037 §7 defines: `StrategyEngineConfig`'s ORB-approved pairs (Gate A)
∩ the active `TradingProfile.allowed_pairs`. **This intersection is a
tracking subset used only to determine whether a given opportunity
window's scan is complete — it is not, and must not be described or
implemented as, the complete set of pairs Runtime evaluates each
cycle.** Every pair in `profile.allowed_pairs` keeps receiving its front
half exactly as today, whether or not it is a member of this
tracking subset.

After a pair's front-half result exists, Runtime classifies it using
only already-computed, already-produced fields (the winning strategy's
identity; the `range_start`/opportunity-window identity ADR-037 §4
requires Strategy Engine's own output to carry) — never re-deriving
qualification, opening-range "currently relevant" logic, or ranking:

- **Ordinary/non-participating results retain the existing, entirely
  unmodified path.** A pair whose winning strategy is not
  `OPENING_RANGE_BREAKOUT`, or whose ORB result's `range_start` does not
  correspond to a currently enabled opportunity window, or which had no
  formed range at all, proceeds immediately into Risk → Compliance →
  Bridge exactly as it does today — no waiting, no barrier
  participation, no added latency.
- **Legacy-strategy winners remain unmodified and are never held behind
  the ORB barrier**, regardless of how broad the ORB-approved pair list
  (Gate A) is. This is required for the ADR-036-governed coexistence
  period in which the five legacy strategies and ORB both remain
  registered (§6 below).
- **Enabled-window ORB candidates may pause after Strategy, before
  Risk.** Only a pair whose own front-half result is itself an
  enabled-window ORB candidate is ever held.
- **Runtime collects terminal front-half outcomes for the frozen
  tracking universe** (§3 of this amendment defines "terminal front-half
  outcome" precisely).
- **Completeness is evaluated per ADR-037's own contract** (§7, §5.D of
  ADR-037) — this amendment does not restate that contract's mechanics,
  only authorizes Runtime to perform the counting/comparison it
  requires.
- **Candidates are grouped by their already-produced `range_start`
  identity** — never by re-deriving which range is "currently
  relevant."
- **The Opportunity Selection Engine — a new, dedicated component
  outside `titan_protocol/runtime/`, per ADR-037 §4 — selects at most
  one winner per opportunity window.** Runtime does not perform this
  selection; it consults the engine and acts on its returned result via
  equality/membership check.
- **Only that selected winner may enter Risk, Compliance, and Bridge for
  that opportunity window.** Every other enabled-window ORB candidate
  that contributed to that window's barrier terminates before Risk.
- **An incomplete scan, or an Opportunity Selection Engine failure for a
  given opportunity window, results in zero ORB candidates from that
  window proceeding to Risk for that cycle.** There is never a fallback
  to unrestricted per-pair ORB execution.

**This amendment does not duplicate ADR-037's ranking policy,
persistence/store design, or session/anchor configuration schema.**
Those remain governed exclusively by ADR-037 (and, where still
unresolved, by ADR-037's own named future Plan/governance gates); this
amendment cross-references them rather than restating them.

## 3. Early-exit / completeness reconciliation (amends §3's early-exit discipline)

§3's four existing early-exit cases (`strategy.rejected`, `not
risk.approved`, `compliance.decision is REJECT`, a non-`None`
`bridge_submit` `ErrorCode`) remain entirely unchanged and apply to
every pair, tracked or not. This amendment adds — without altering any
of the four existing cases — a second, orthogonal axis that applies
only to pairs in the frozen ORB completeness-tracking universe:

1. **Normal per-pair termination** — §3's existing, unamended
   vocabulary. Unaffected by this amendment.
2. **ADR-037 completion tracking** — whether a tracked pair reached a
   **terminal front-half outcome** this cycle: Evidence, Market
   Intelligence, and Strategy have all been invoked for it and produced
   a final result, whether that result is an explicit ORB qualification,
   an explicit ORB rejection, or a legacy strategy winning instead of
   ORB. A tracked pair that exits early at Evidence, at a session-rule
   check, or at Market Intelligence (any of §3's existing early-exit
   points reached *before* Strategy Engine ever runs) has **not**
   reached a terminal front-half outcome, regardless of its membership
   in the tracking universe.
3. **Aggregate incomplete-scan failure** — the consequence, scoped to
   an *opportunity window* (potentially spanning many pairs), of even
   one tracked pair failing to reach a terminal front-half outcome this
   cycle: that window's barrier fails closed for that cycle (§4 above,
   §5 below).

**Concepts 2 and 3 are not the same as concept 1, and this amendment
does not conflate them.** A pair reaching an ordinary per-pair
termination (concept 1) simultaneously and independently either does or
does not count toward concept 2's completeness tracking, depending only
on whether Strategy Engine ever ran for it this cycle — not on which
specific early-exit case, if any, applied.

**This amendment does not invent a rule dynamically removing an
early-exiting tracked pair from the expected universe**, and does not
soften ADR-037's own fail-closed completeness rule in any way. The
frozen expected universe (§4 of ADR-037, unchanged) is computed once, at
cycle start, from static configuration alone, and held fixed for the
cycle regardless of what any individual pair's front half produces.

## 4. Cycle-scoped orchestration state (amends §6)

§6's `RuntimeContext` — "one per cycle, per pair, containing exactly"
the five snapshots plus portfolio/account/profile/clock/reservation
fields — **remains the correct and unchanged description for every
pair whose front-half result is not an enabled-window ORB candidate**,
which is the overwhelming majority of every cycle during the ADR-036-
governed coexistence period.

For the narrowly-scoped subset that *is* such a candidate, Runtime must
additionally maintain **cycle-scoped orchestration state** sufficient to:

- know the frozen expected universe for the cycle (§2 of this
  amendment; a static, configuration-derived value, not a snapshot);
- record which tracked pairs have reached a terminal front-half outcome
  this cycle, and which have not (§3 of this amendment);
- group enabled-window ORB candidates' already-produced results by
  their `range_start` identity;
- hold each such candidate pending the Opportunity Selection Engine's
  result long enough to release it into (or terminate it before) Risk,
  once that window's completeness and selection are both resolved.

**This amendment authorizes the existence of this state; it does not
design its data structures, storage, or lifetime** — that is
implementation/Plan-level work. **This amendment does not authorize
Runtime to persist, own, or make the Opportunity Selection Engine's
trading decision** — the winner decision itself remains that engine's
own, entirely separate, persisted contract (ADR-037 §9), which Runtime
only consults and acts on.

## 5. Observability (amends §7)

§7's existing requirement — every cycle records start/end/duration/
decision/rejected-stage/approved-stage(s)/timing/reason, "no silent
failures... never a generic 'skipped'" — is extended, not replaced, to
require that an operator/auditor can distinguish, at minimum:

- ordinary per-pair termination (§7's existing requirement, unchanged);
- a complete opportunity-window scan that produced no winner;
- an incomplete opportunity-window scan (§3 of this amendment's concept
  3);
- an Opportunity Selection Engine or barrier failure;
- a candidate released toward Risk because it was selected;
- a candidate terminated before Risk because it was not selected, or
  because its window's scan failed to complete.

**This amendment does not restate ADR-037's own, more detailed
observability signal list (ADR-037 §12)** — it requires only that these
six categories remain distinguishable in Runtime's own audit trail,
cross-referencing ADR-037 for the full signal catalogue.

**Watchdog integration is explicitly left undecided by this amendment.**
The Research underlying this amendment found no evidence compelling the
new engine's inclusion in `APPROVED_RESTART_COMPONENTS` (§9, unchanged
above) — whether to add it, and under what restart semantics, is left as
an explicit future Plan-level question, not decided or implied here.

## 6. Fail-closed behavior (amends §8)

§8's existing Fail-Closed table (unknown engine state, missing
snapshot, invalid configuration) is exhaustively per-pair-scoped and
remains fully valid, unamended, for every pair. This amendment adds one
new, aggregate-scoped invariant §8's existing rows do not cover:

> **If the ADR-037 completeness barrier, or the Opportunity Selection
> Engine itself, cannot produce a valid decision for a given
> opportunity window this cycle (an incomplete scan, an engine
> exception, a timeout, or a persisted-state failure per ADR-037's own
> contract), zero ORB candidates from that window may proceed into Risk
> for that cycle. No unrestricted fallback to independent per-pair ORB
> execution is permitted under any circumstance.**

This invariant is scoped to the affected opportunity window only —
unrelated pairs, unrelated windows, and every legacy-strategy pair
remain entirely unaffected, exactly as §8's existing "other
pairs/cycles unaffected" per-pair-isolation principle already
establishes for its own rows. This amendment references ADR-037 §9 for
the detailed selector/persisted-store failure semantics rather than
restating them.

## 7. Lifecycle vocabulary (amends §12; identifiers deferred)

§12's `RuntimeAuditRecord` fields (`outcome: CycleOutcome`,
`stage_reached: Optional[CycleStage]`) currently have no vocabulary for
two new, semantically distinct lifecycle states this amendment
requires to exist:

1. **A candidate waiting at the opportunity-selection barrier** —
   distinct from every existing terminal `CycleOutcome`, since the pair
   has neither been rejected nor yet reached a final disposition when
   this state applies.
2. **A candidate terminated because it was not selected, or because its
   window's scan failed to complete** — distinct from every existing
   rejection outcome (`NO_STRATEGY`, `RISK_REJECTED`,
   `COMPLIANCE_REJECTED`, etc.), since none of those five engines
   rejected the pair; it lost a cross-pair comparison, or its window's
   completeness requirement was not met.

**This amendment requires that ADR-031's governed vocabulary account
for these two concepts; it does not choose their exact enum member
names or values.** Whether these become new `CycleStage`/`CycleOutcome`
members, a new field, or another representation is Plan-level work,
deferred exactly as this amendment defers ADR-037's own ranking/tie/
session-policy decisions — naming them here would be inventing an
implementation detail this governance layer does not need to fix.

## 8. Determinism and acceptance criteria (amends §14)

§14's existing criteria are unchanged in substance and are extended
with the following, all independently re-derivable from ADR-037's own
Accepted contract and this amendment's own text above, none inventing
new ranking-determinism rules beyond what ADR-037 already, and
correctly, leaves unresolved:

- Deterministic orchestration remains required — identical inputs
  (including a fixed `Clock`) must continue to produce an identical set
  of `RuntimeAuditRecord`s on every run.
- **Pair iteration/assembly order must not affect the winner-selection
  outcome.** Whatever order Runtime assembles an opportunity window's
  candidate set in for the Opportunity Selection Engine, it must be a
  deterministic function of pair identity (e.g., the same sorted-by-
  symbol discipline `StrategyEngine.evaluate_batch()`/`RiskEngine.
  evaluate_batch()` already establish elsewhere in this codebase) — not
  wall-clock arrival order or any other non-deterministic sequencing.
- **Each pair's front half executes at most once per Runtime cycle** —
  never once per enabled opportunity window, regardless of how many
  windows are enabled.
- **Enabled-window count must not cause duplicated front-half
  evaluation** — one, two, or more enabled windows all reuse the same,
  single, already-computed front-half result set.
- **Legacy-strategy and other non-participating behavior remains
  behaviorally equivalent to the existing, pre-amendment pipeline** —
  same engine calls, same reservation lifecycle, same latency.
- **No non-winning ORB candidate reaches Risk.**
- **An incomplete opportunity-window scan fails closed** — no winner
  selected from a partial set, ever.
- **Runtime remains an orchestrator, never the selector** — the
  Opportunity Selection Engine, not Runtime, decides who wins; §2 of
  this amendment governs this and is not weakened by anything above.

## 9. Architecture-test consequence (disclosed, not performed)

`tests/titan_protocol/runtime/test_architecture.py::
test_only_permitted_upstream_packages_are_imported` currently
restricts `titan_protocol/runtime/`'s permitted `titan_protocol.*`
upstream imports to the six packages named in §3's pipeline diagram. A
future implementation of this amendment's architecture will
legitimately require adding the Opportunity Selection Engine's own
package to that allow-list, since Runtime must import it to consult the
engine as this amendment's §2/§4 describe.

**This is an authorized consequence of the new pipeline dependency this
amendment records — not a license to weaken the structural rule
generally.** Only the single, specific new upstream package this
amendment's own engine dependency requires may be added when
implementation is separately authorized; no other change to that test's
allow-list, or to any other structural-boundary test, is authorized by
this amendment. **No test is modified by this amendment itself.**

## 10. Coexistence with legacy strategies (explicit, binding)

This amendment does not imply that all pairs wait at the barrier, and
must not be implemented or read as implying it. During the ADR-036-
governed coexistence period (legacy retirement separately gated, not
authorized here):

- Legacy-strategy winners proceed normally, through the entirely
  unmodified path §2 of this amendment already states.
- Non-participating pairs (any pair not classified as an enabled-window
  ORB candidate) follow today's path, unchanged.
- Rejected pairs terminate normally, exactly as §3's existing four
  early-exit cases already govern.
- **Only ADR-037-enabled-window ORB candidates ever participate in the
  opportunity-selection barrier.** No other pair's cycle is held,
  delayed, or altered by this amendment's existence.

## 11. Scope and non-authorization

This amendment does **not** authorize, decide, or imply:

- Implementation of the Opportunity Selection Engine, or of any Runtime
  restructuring described above.
- Any ranking formula, ranking weights, or ranking inputs beyond what
  ADR-037 §6 already authorizes (none).
- Any tie-handling policy.
- The exact number of enabled opportunity windows, or their exact
  identities. **London and New York remain intended initial production-
  policy content only, never an architectural constant** — this
  amendment's own text names no session.
- Any exact production pair, opening-range anchor, or clock value.
- Gate A or Gate B activation.
- Any Risk/Compliance runner-up fallback policy (ADR-037 §10 already
  leaves this as a distinct, separate future decision, unaffected here).
- Legacy-strategy retirement, or any ADR-036 implementation sequencing.
- The ADR-035 Phase 5 anchor hour/minute validation follow-up — entirely
  untouched, unrelated, and unauthorized by this amendment.
- Watchdog restart-allow-list inclusion for the new engine (§5 above,
  left to a future Plan).
- Modification of `tests/titan_protocol/runtime/test_architecture.py`
  or any other test, now or as a consequence of this amendment's own
  Acceptance — only a future, separately-authorized implementation may
  make the single disclosed test change §9 above names.

## 12. Acceptance criteria for this amendment

- ✓ §2 Hard Rules text is unchanged; every new Runtime responsibility
  this amendment describes reduces to execution/collection/counting/
  grouping/equality-comparison, never generation, calculation, ranking,
  or override.
- ✓ Every pair continues to receive its front-half evaluation exactly
  once per cycle, whether or not it is ORB-completeness-tracked.
- ✓ The frozen `Gate A ∩ allowed_pairs` intersection is described only
  as a completeness-tracking subset, never as the complete set of pairs
  Runtime evaluates.
- ✓ Legacy-strategy and other non-participating pairs are explicitly,
  unambiguously exempt from any barrier participation or added latency.
- ✓ The normal-termination / completion-tracking / aggregate-
  incomplete-scan distinction (§3 above) is stated without conflating
  the three, and without inventing a dynamic-universe-shrinking rule.
- ✓ No test, enum, configuration value, or production gate is modified
  by this amendment.
- ✓ This amendment cross-references ADR-037 for ranking, persistence,
  session/anchor configuration, and detailed observability/failure
  specifics rather than restating them.
- ✓ This amendment remains **Proposed** and self-evidently does not
  mark itself Accepted.

---

*This amendment is Proposed. It requires its own independent governance
review before Acceptance. It does not authorize implementation of
ADR-037's architecture, any ranking/tie/session-production-policy
decision, Gate A/Gate B activation, or ADR-036 legacy-strategy
retirement. The ADR-035 Phase 5 anchor hour/minute validation follow-up
remains separately gated, unauthorized, and out of scope.*
