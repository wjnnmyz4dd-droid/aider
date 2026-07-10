# ADR-031 — Runtime Orchestrator, Configuration Management, Trading Profiles

Status: Accepted

Acceptance Date: 2026-07-10

Accepted By: Software Architect / Phantom Engineering Council (full
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
  **It is not imported.** Every `phantom/` package built this session
  (`ADR-024` through `ADR-030`) enforces, via its own architecture
  test, "zero import of `phantom_pipeline`" — importing
  `phantom_pipeline.watchdog` here would be the first exception to a
  rule this session has applied without exception six times running,
  and would make a reference-only tree (`ADR-001`'s own resolution: `
  phantom_pipeline` is "mined for proven ... mechanisms," never a
  running authority) into a live dependency of the pipeline that
  resolution built. Instead, `phantom/runtime/watchdog_integration.py`
  is a **fresh, minimal module mirroring `ADR-011`'s vocabulary**
  (component/kind/timeout-detection shape) without importing it. A
  future ADR could formally bridge the two trees; not assumed here.
- **No legacy runtime orchestrator exists in `phantom/`.** Designed
  from first principles for the six engines this session built,
  reusing their already-accepted, real public interfaces — never a
  second implementation of anything they already compute.

---

# Pipeline position

**The Runtime Orchestrator is the live coordinator — the first
component in this session's `phantom/` build that is actually wired
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
`phantom/runtime/` contains a decision-shaped name, and every
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
`phantom.validation_engine`.

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
   (`phantom.bridge.models`) and call a caller-supplied
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
  and lot size only) — `phantom.bridge.validation.
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

`phantom/runtime/watchdog_integration.py` (fresh module, §0) detects
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

- ✓ No decision-shaped name anywhere in `phantom/runtime/` (§2, AST test).
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
