# Session Edge — Phase 4C: Shadow Mode & Position Management Architecture

**Scope:** Shadow Mode (advisory observation) + a **frozen, design-only**
deterministic Position Management architecture. No advisory agent gains execution
authority. No execution behavior, trailing stops, or break-even logic is
implemented. Strategy engine, filesystem bridge, and MT5 adapter are unchanged.

## 1. Resolved review findings

- **Finding A (News verification scope).** Verification is now enforced **only
  for events inside the lockout window**. An unverified/tentative event days away
  no longer blocks advisory evaluation (it is ignored until it enters the window).
  Reason codes are now precise: an in-window unverified block reports
  `NEWS_SOURCE_UNVERIFIED` (not `NEWS_HIGH_IMPACT_BLOCK`). Bundle-level
  `verified=false` still fails closed. Regressions in `test_findings_4c.py`.
- **Finding D (Liquidity robustness).** `(context.get("market") or {})` replaces
  the crashing `.get("market", {})` idiom; the Liquidity agent now completes its
  live computation even when the market context is `None`/absent. Regressions in
  `test_findings_4c.py`.

## 2. Shadow Mode architecture

Shadow Mode runs the advisory agents **beside** the authoritative deterministic
strategy and records what they *would* have said. It is strictly informational:
it cannot modify the strategy, orders, stops, targets, bridge instructions, or
execution, and it never writes a bridge instruction. The deterministic strategy
decision is a **read-only input**.

```
market data → deterministic strategy (authoritative)
            → Market Intelligence → Liquidity → News & Compliance
            → Explainability → Memory → Shadow Report
```

`ShadowRunner.observe(request, bundle, strategy_decision, now)` calls the Phase-4B
`Orchestrator.run_advisory` (Risk/Critic/Coordinator authority remain inactive),
computes per-opportunity metrics, writes **one immutable `shadow_report` memory
record**, and returns a report with `shadow=true`, `informational_only=true`,
`is_order=false`. A memory-write failure is audited and never affects anything.

## 3. Shadow pipeline (properties)

- Strategy decision is copied into the report; the input object is never mutated.
- A deterministic strategy `NO_TRADE` keeps the advisory summary at `NO_TRADE`
  even when all agents are CLEAR (strategy remains authoritative).
- Any agent BLOCK (e.g. News high-impact, Liquidity trap) surfaces in the metrics
  and drives the advisory summary to `NO_TRADE` — advisory only, never an order.
- Deterministic: identical inputs produce identical metrics and report content.

## 4. Analytics design

`ShadowAnalytics(memory)` is read-only over stored `shadow_report` records (and,
when present, `execution_outcome` records). Per-opportunity metrics captured by
`shadow_metrics`:

strategy decision · MI/Liquidity/News assessments · advisory decision · agreement
score · full-agreement flag · conflicting agents · strategy-advisory agreement ·
confidence distribution (+min) · reason-code frequency · market regime · trend-
continuation context · liquidity observations (rating/sweep/trap/retest) · news
observations (rating/hits) · any-block · outcome reference (signal_id).

Aggregates (`summarize`): count, **historical agreement matrix**
(`strategy_candidate → advisory_decision` counts), regime distribution,
reason-code frequency, confidence-band distribution, mean agreement score.

Outcome linkage (`accuracy`): joins reports to `execution_outcome` by `signal_id`
and computes true/false positives/negatives and **advisory accuracy** — reporting
`outcomes_available=false` (zeros) until execution outcomes exist. None of this
alters live strategy behavior.

## 5. Agreement metrics

- **agreement_score** = share of live agents at the majority assessment (ties
  broken toward the more severe, fail-safe).
- **full_agreement** = all live agents share one assessment.
- **conflicting_agents** = agents off the majority.
- **strategy_advisory_agreement** = strategy `QUALIFIED`↔advisory `PROCEED`, or
  strategy `NO_TRADE`↔advisory `NO_TRADE`.

## 6. Position Management architecture (FROZEN; design only)

Deterministic throughout. AI agents may **recommend**; only a future
deterministic executor will act, and it must satisfy the invariants in §8. The
design is encoded as data + invariants in `forex_swing_orb/position/contract.py`
(no execution).

- **Initial Stop Loss.** Always the strategy-provided stop (`initial_stop_source
  = "strategy"`). PM never invents an initial stop.
- **Phase model (forward-only).** `INITIAL → BREAKEVEN → LOCKED → TRAILING →
  CLOSED`; any phase may go to `CLOSED`; transitions never go backward
  (`phase_transition_is_legal`).
- **Deterministic trailing.** `TrailMethod.STRUCTURE` (trail behind confirmed
  structure — strategy swing points are **consumed**, not recomputed).
  `TrailMethod.ATR` is a documented future option (`atr_period`, `atr_multiple`).
- **Partial profit (optional).** `partial_enabled` (default off),
  `partial_fraction`, `partial_at_r`.
- **Maximum trade duration.** `max_duration_bars` (0 = disabled) → deterministic
  `PM_MAX_DURATION_EXIT`.
- **Weekend policy.** `WeekendPolicy.FLATTEN` (default) or `HOLD`
  (`PM_WEEKEND_FLAT` / `PM_WEEKEND_HOLD`).
- **Manual intervention.** `ManualPolicy.ADOPT_AND_AUDIT` (detect a manual broker
  change, adopt broker truth, audit) or `RECONCILE_REQUIRED`
  (`PM_MANUAL_DETECTED`).
- **Broker synchronization.** State carries `broker_synced`; a mismatch →
  `PM_BROKER_DESYNC`, fail closed.
- **Restart recovery.** State is rebuilt from `RECOVERY_SOURCES_OF_TRUTH =
  (mt5_terminal, filesystem_bridge, pm_audit_log)` — **never in-memory only**
  (`PM_RECOVERED_FROM_BROKER` / `PM_RECONCILIATION_REQUIRED`).
- **Audit.** Every stop movement/decision emits a deterministic PM reason code
  (see §9) via the reused bridge audit contract.

State schema (`REQUIRED_STATE_FIELDS`): signal_id, ticket, symbol, direction,
entry, initial_stop, current_stop, take_profit, phase, opened_timestamp,
last_update_timestamp, bars_open, partials_done, manual_flag, broker_synced.

## 7. Break-even architecture

At `breakeven_trigger_r` (default +1R) the phase advances `INITIAL → BREAKEVEN`
and the stop is documented to move to `entry ± breakeven_buffer_pips`
(`PM_BREAKEVEN_TRIGGERED` → `PM_BREAKEVEN_SET`). The buffer keeps the stop just
beyond entry to absorb spread. The break-even move must satisfy the never-widen
invariant (a break-even stop is strictly toward profit vs the initial stop). The
arithmetic is documented here and deferred to implementation — no break-even
computation ships in this phase.

## 8. Trailing Stop architecture + safety invariants

The future implementation shall: set the initial SL (from strategy) → move to
break-even → lock in profit (`profit_lock_r`, default +1.5R) → trail **only in the
direction of profit**, **never widen risk**, **never loosen a stop** → recover
correctly after restart by rebuilding stop state from **MT5 + bridge** → audit
every stop movement with a deterministic reason code. **No AI agent may move a
stop.**

These are encoded now as pure, tested invariants (the safety contract a future
executor must satisfy):

- `stop_move_is_legal(direction, old, new)` — LONG stops may only rise, SHORT
  stops may only fall; equal (hold) allowed.
- `risk_not_increased(direction, entry, old, new)` — a move never increases
  distance-to-entry on the loss side.
- `phase_transition_is_legal(from, to)` — forward-only lifecycle.

The trailing/break-even **algorithms themselves are not implemented** (no
`compute_next_stop`/`next_stop`/`trail_stop`/`move_to_breakeven`) — verified by
test.

## 9. Audit additions

- Shadow: `shadow/REPORT` (with strategy decision + agreement score) and
  `shadow/ERROR` (`SHADOW_MEM_FAILED`) via the reused bridge audit contract.
- Position Management (design registry, `PMReason`): `PM_INITIAL_SL_SET`,
  `PM_BREAKEVEN_TRIGGERED`, `PM_BREAKEVEN_SET`, `PM_PROFIT_LOCKED`,
  `PM_TRAIL_ADVANCED`, `PM_TRAIL_HELD`, `PM_STOP_REJECTED_WIDEN`,
  `PM_MAX_DURATION_EXIT`, `PM_WEEKEND_FLAT`, `PM_WEEKEND_HOLD`, `PM_PARTIAL_TAKEN`,
  `PM_MANUAL_DETECTED`, `PM_BROKER_DESYNC`, `PM_RECOVERED_FROM_BROKER`,
  `PM_RECONCILIATION_REQUIRED`.

## 10. Tests

- `agents/tests/test_findings_4c.py` — Finding A (in-window scope, precision,
  in-window still blocks, verified still blocks) and Finding D (market None/absent
  robustness) regressions.
- `agents/tests/test_shadow_4c.py` — shadow pipeline informational-only, no
  strategy mutation, strategy authoritative, agreement/disagreement, news-block
  recording, analytics aggregation + accuracy (with/without outcomes), no bridge
  writes, no execution/networking in source, determinism.
- `position/tests/test_position_architecture.py` — frozen config/schema,
  break-even architecture, trailing invariants (trail-only-toward-profit,
  never-widen, unknown-direction illegal), forward-only phase lifecycle,
  weekend/manual/duration design, restart recovery source-of-truth order,
  no-execution/no-networking, and no stop-computation function present.

## Deviations

None. No new third-party dependency. No production (strategy/bridge/EA) change.

---

# Phase 4C-R — Frozen Deterministic Specifications

Phase 4C-R closes the acceptance-review gaps. All of the following are frozen in
`forex_swing_orb/position/contract.py` (+ pure math in `position/spec.py`) and
validated by `position/tests/`. Design-only: no execution, no broker/bridge call,
no AI stop authority.

## F1 — Stop-update precedence (frozen)

`STOP_UPDATE_PRECEDENCE` (highest first):
1. broker_reconciliation 2. manual_intervention 3. emergency_kill_switch
4. position_closed 5. weekend_policy 6. max_duration
7. protective_stop_integrity 8. break_even 9. profit_lock 10. structure_trail
11. no_action.

Invariant (`PRECEDENCE_INVARIANT`): *"No lower-priority rule may weaken a
higher-priority protective action; on any evaluation the highest-priority
applicable rule decides, and a stop may only move in a protective (never-widen,
never-loosen) direction."* Helpers: `precedence_rank`, `precedence_dominates`.

## F2 — Break-even (frozen math, `spec.py`)

- Immutable risk `R = |entry - initial_stop|`; `initial_risk()` returns `None`
  (fail closed) on zero, negative, non-finite, or wrong-sided risk.
- Trigger operator is **`>=`** toward profit (equality triggers).
  Long trigger = `entry + trigger_r*R`; short = `entry - trigger_r*R`.
- Break-even stop = `entry ± (breakeven_buffer_pips + commission_pips)*pip`
  (buffer nets past spread/commission). Always toward profit vs the initial stop
  (never widens).
- Invalid entry/stop or `R=None` → `None` (fail closed). R is fixed at entry and
  never redefined by later stop moves (state keeps `initial_stop`).

## F2 — Profit lock (frozen)

- Trigger `>=` at `entry ± profit_lock_r*R` (default +1.5R).
- Locked stop = `entry ± profit_lock_retain_r*R` (default +0.5R), symmetric L/S.
- Anti-oscillation: forward-only phase + a move requires strict improvement
  (`is_stop_improvement`, ≥ `min_trail_improvement_pips`); equality → hold. Uses
  the immutable R only.

## F2 — Structure trailing (frozen)

- Eligible structure = a **confirmed strategy swing** (higher-low for long,
  lower-high for short); confirmation is **inherited from the strategy pivot_k**
  (`reuse_strategy_swings=True`) — pivots are **never recomputed** here.
- Candidate = `swing ∓ trail_offset_pips*pip`; `None` when no valid structure
  (executor holds → `PM_TRAIL_PENDING`/`PM_TRAIL_NO_IMPROVEMENT`).
- Minimum improvement `min_trail_improvement_pips`; equal/worse → hold.
- Stale structure (`> stale_structure_max_bars`) → `PM_DATA_STALE`, hold.
- Broker minimum stop distance enforced (`respects_broker_min_stop`).
- No future bars (no bar access; consumes confirmed swings only).
- Evaluation cadence: **once per closed bar** (`ON_CLOSED_BAR`).
- Restart: rebuilt from broker + bridge (never in-memory only).
- Direction rule: long `new_stop > current`, short `new_stop < current`; equal =
  no modification (`stop_move_is_legal`).

## F3 — Reason-code registry (complete, normalized)

`PMReason.REQUIRED` = the 20: PM_INITIAL, PM_BREAKEVEN_PENDING,
PM_BREAKEVEN_TRIGGERED, PM_BREAKEVEN_SET, PM_PROFIT_LOCK_TRIGGERED,
PM_PROFIT_LOCK_SET, PM_TRAIL_PENDING, PM_TRAIL_ADVANCED, PM_TRAIL_NO_IMPROVEMENT,
PM_STOP_WIDEN_REJECTED, PM_STOP_LOOSEN_REJECTED, PM_BROKER_CONSTRAINT,
PM_RECONCILIATION_REQUIRED, PM_MANUAL_CHANGE_ADOPTED, PM_MANUAL_CHANGE_REJECTED,
PM_POSITION_CLOSED, PM_DATA_STALE, PM_DATA_INSUFFICIENT, PM_WEEKEND_EXIT,
PM_MAX_DURATION_EXIT. Supporting extras: PM_KILL_SWITCH, PM_PARTIAL_CLOSED,
PM_RECOVERED_FROM_BROKER, PM_MANUAL_DETECTED, PM_NO_ACTION.

## F4 — Audit schema (frozen)

`AUDIT_RECORD_FIELDS` (one record per stop evaluation/movement): signal_id,
ticket, symbol, direction, phase, entry_price, initial_stop,
immutable_initial_R, previous_stop, proposed_stop, applied_stop, trigger_price,
market_reference, structure_reference, reason_code, broker_result,
evaluation_timestamp, reconciliation_status, manual_status, restart_source.
`build_audit_record` (deterministic; unspecified fields → null) +
`validate_audit_record`.

## F5 — Manual intervention (frozen)

`classify_manual_change(direction, expected_stop, observed_stop,
position_present)` → deterministic `(ManualAction, PMReason)`:
- no broker position → CLOSE / `PM_POSITION_CLOSED`
- SL removed (`observed=None`) → ESCALATE / `PM_STOP_LOOSEN_REJECTED`
- tighter (toward profit) → ADOPT / `PM_MANUAL_CHANGE_ADOPTED`
- looser (widens risk) → REJECT / `PM_MANUAL_CHANGE_REJECTED`
- no change → NONE. Symmetric long/short; never violates never-widen/never-loosen.
Manual partial close → reconcile volume (`PM_PARTIAL_CLOSED`); TP modification is
outside PM stop scope (audit only); ticket/symbol mismatch → fail closed
(`PM_RECONCILIATION_REQUIRED`).

## F6 — Reconciliation matrix (frozen)

`RECONCILIATION_MATRIX` rows `(case, source_of_truth, result, reason_code, audit,
retry_allowed)` for: broker_stop_differs, bridge_missing, audit_missing,
conflicting_audit, no_broker_position, terminal_disconnected, duplicate_ticket,
crash_during_stop_modification, unknown_broker_outcome, stale_local_state.
Every row: `audit=True`, `retry_allowed=False` — **the executor never blindly
resends a stop modification**; uncertain outcomes (crash / unknown) verify broker
truth first (`..._never_blind_resend`, `PM_RECONCILIATION_REQUIRED`).
`reconciliation_rule(case)` looks up the frozen row.

## Weekend / max-duration (frozen)

Cutoff is a **fixed UTC** instant (`weekend_cutoff_dow=Fri`,
`weekend_cutoff_hour_utc=20`) — DST-immune by construction; FLATTEN/HOLD
deterministic; `max_duration_bars` (0=disabled) uses the monotonic
`opened_timestamp`/`bars_open` reference. Weekend and max-duration both sit above
break-even/lock/trail in the precedence order, so a protective exit is never
weakened by a management rule.

## 4C-R tests

`position/tests/test_position_spec_4cr.py` (45 assertions across precedence,
break-even/profit-lock/trailing math incl. exact `>=` boundaries and zero/
negative/non-finite risk fail-closed, long/short symmetry, reason-code registry
completeness, audit schema, manual policy, reconciliation matrix) plus the
updated `test_position_architecture.py`. No execution tests.

**Disposition:** READY FOR POSITION MANAGEMENT IMPLEMENTATION.
