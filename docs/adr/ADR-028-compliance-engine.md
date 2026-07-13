# ADR-028 — Prop Firm Compliance Engine

Status: **Accepted**

Owner: Security Architect (per `.claude/agents/TEAM.md` RACI, the same
Accountable role named for `ADR-006`'s existing Compliance Engine —
this is the pipeline's final, non-bypassable authority before
execution, and design-time trust-boundary ownership belongs here)

Accepted By: User direction, this session (explicit, full
specification given in two parts: an initial "Daily Loss Safety
Buffer" requirement, followed by the complete mission, the 6 named
inputs, all rule categories, architecture rules, performance targets,
and a 10-category testing mandate) — the same in-session approving
authority already used to accept `ADR-024` through `ADR-027`.

Reviewed by: (post-hoc, this session) — checked against `ADR-006`
(Compliance Engine, `phantom_pipeline/`) before acceptance; see §0.

Date: 2026-07-10

Depends on: `ADR-024-evidence-engine.md` (Accepted, Amendment 1),
`ADR-025-market-intelligence-engine.md` (Accepted),
`ADR-026-strategy-engine.md` (Accepted),
`ADR-027-portfolio-statistical-risk-engine.md` (Accepted — this stage
necessarily imports `titan_protocol.risk_engine.models` for `RiskSnapshot` and
`PortfolioState`, and reuses `titan_protocol.risk_engine.exposure`'s pure
currency/exposure utilities rather than reimplementing them — see §4).

---

# 0. Relationship to existing architecture

**`ADR-006` Compliance Engine (`phantom_pipeline/`)** already exists as
a guard-based FTMO/prop-firm rule package (`guards.py`,
`ComplianceEngine`). Per the established `titan_protocol/` track precedent
(`ADR-024`–`ADR-027` §0, each disclosing the same class of overlap and
resolving it identically): **fresh, independent, no reuse.**
`titan_protocol/compliance_engine/` is built clean-room, mined for proven rule
shapes only, never importing `phantom_pipeline/compliance/` or sharing
its guard registry.

Unlike every prior `titan_protocol/` stage, this one **necessarily** imports
from another `titan_protocol/` package: `RiskSnapshot` and `PortfolioState`
are defined in `titan_protocol.risk_engine.models` and are two of this
engine's six named inputs (§2), so `titan_protocol.risk_engine` is an
unavoidable, explicitly-named upstream dependency — not a boundary
violation, since ADR-027 already established these as the read-only,
frozen public types of a stage this one sits immediately downstream of
per `ADR-001`'s pipeline order.

---

# Pipeline position

Per `ADR-001`, this is pipeline stage 6: **Market Data → Scanner →
Strategy Engine → Scoring Engine → Risk Engine → Compliance Engine →
Execution Validator → MT5 Bridge → Position Manager → Analytics.** Not
wired into any execution pipeline yet — no orchestrator exists in
`titan_protocol/` at this phase. Per the user's stated sequence, this is Phase
2E; Research & Learning Engine and Validation remain unimplemented and
out of scope here.

---

# 1. Mission

**The Compliance Engine is the final authority before execution.** It
answers exactly one question: "is a statistically-approved trade
allowed under operational and prop-firm rules?"

It never:

- Selects a strategy.
- Calculates evidence.
- Calculates statistical risk.
- Reads news providers directly.
- Executes trades.
- **Increases risk.**

It may only: **APPROVE**, **REDUCE**, or **REJECT** — never increase.

---

# 2. Inputs

Consume ONLY:

- `EvidenceSnapshot` (`ADR-024`, read-only) — `session.session` drives
  the session-restriction check; `report.score.composite` backs the
  "exceptionally high confidence" gate at elevated daily-loss bands.
- `MarketIntelligenceSnapshot` (`ADR-025`, read-only) — `pair_safety.news`
  (blackout), `pair_safety.peg_policy`, `pair_safety.market_safety`
  (holiday/maintenance/halt/closed), `pair_safety.liquidity` (spread)
  are read directly. **Never queries a news/data provider itself** —
  this snapshot is the only permitted channel to that information.
- `StrategySnapshot` (`ADR-026`, read-only) — `winning_strategy.qualification.score`
  backs the "highest-quality setups only" gate; `rejected` is a
  defensive consistency check (Risk Engine already requires a winning
  strategy to approve, so this should be unreachable, but is verified
  rather than assumed).
- `RiskSnapshot` (`ADR-027`, read-only) — `approved`,
  `approved_risk_r`, `recommended_position_size`, `confidence_tier` are
  this engine's *original recommendation*, which it may only reduce or
  reject.
- `PortfolioState` (`ADR-027` type, read-only) — reused directly, not
  redefined; feeds this engine's own, independently-configured position/
  exposure limits via `titan_protocol.risk_engine.exposure.compute_exposure_summary`
  (the same pure utility Risk Engine itself uses — calling it a second
  time with Compliance's own thresholds is not a duplicate
  calculation, since the fact being read, `PortfolioState`, was
  computed once by neither engine and supplied by the caller; Amendment
  precedent: ADR-024 Hard Rule 9, "one computation per fact," is about
  not deriving the same *fact* twice, not about forbidding two stages
  from applying their own distinct thresholds to one shared fact).
- `AccountState` (**new type, this ADR** — §3) — every operational fact
  needed to evaluate the rules in §5 that no upstream snapshot carries
  (account/peak balances, consecutive-loss count, trading-day count,
  today's trade count, pending-order count, consistency-rule
  aggregates, and the compliance lock/emergency-stop state). Modeled
  exactly like `ADR-027`'s `PortfolioState`/`TradeHistory` precedent:
  a plain, caller-supplied snapshot, never fetched by this engine.

Never communicates directly with: MT5, Bridge, Trading Economics, Forex
Factory. AST-verified (`test_architecture.py`), the same pattern every
prior `titan_protocol/` stage established for its own forbidden imports.

---

# 3. `AccountState` — design decision

None of the six inputs the user named give this engine the operational
account facts several of the required rules need (daily/total
drawdown %, consecutive losses, trading-day count, today's trade
count, the FTMO-style consistency rule's daily-profit-vs-total-profit
ratio, or the compliance lock/emergency-stop state). Rather than invent
a seventh input type or silently expand `PortfolioState` (which is
Risk Engine's type, not this engine's to redefine), this ADR defines
`AccountState` in `titan_protocol/compliance_engine/models.py` — exactly the
same move `ADR-027` made for `PortfolioState`/`TradeHistory` when its
own named inputs didn't cover everything its rules required.

`AccountState` carries only **pre-aggregated facts**, never raw
history — consistent with "consume snapshots only" everywhere else
this session. In particular, the FTMO-style consistency rule (no
single day may account for more than a configured share of total
profit) is evaluated from two pre-aggregated fields
(`best_single_day_profit_pct`, `cumulative_profit_pct`) rather than
from a trade-by-trade history, since `TradeHistory` (`ADR-027`) is not
among this engine's six named inputs and re-deriving day-by-day P&L
here would be exactly the kind of duplicate calculation Hard Rule 8
forbids.

**Compliance lock and emergency stop are caller-owned state, not
engine-internal state.** `AccountState.compliance_lock` carries the
*current* lock status into an `evaluate()` call; `ComplianceSnapshot`'s
output carries a `lock_recommendation` (§7) the caller is responsible
for persisting into the *next* `AccountState` it supplies. This is a
deliberate departure from `ADR-027`'s `ReservationLedger` pattern:
Risk Engine's ledger solves a same-process concurrent-approval race
(multiple threads must never together exceed one exposure limit within
one running engine), whereas a compliance lock must survive across
calls, across engine instances, and in a full system across process
restarts — genuinely operational state, not an in-memory concurrency
primitive. Keeping `ComplianceEngine.evaluate()` a pure function of its
six inputs (no engine-held mutable state at all) also satisfies this
task's own explicit architecture rule, "pure deterministic logic,"
literally: a stateless function is trivially thread-safe, with no
lock of its own required.

---

# 4. Hard Rules

1. **Compliance may only APPROVE, REDUCE, or REJECT — never increase**
   position size, risk, exposure, or leverage above `RiskSnapshot`'s
   own recommendation. Enforced structurally: every reduction path
   takes the `min()` of the original and every applicable multiplier;
   nothing in this package ever multiplies by more than `1.0`.
2. **Never overrides Evidence, Strategy, or Statistical Risk.** This
   engine reads `EvidenceSnapshot.report.score.composite`,
   `StrategySnapshot.winning_strategy.qualification.score`, and every
   `RiskSnapshot` field exactly as computed upstream — never
   recomputed, never second-guessed (Hard Rule 8 below).
3. **Fail closed on unknown compliance state.** `portfolio_state` and
   `account_state` are *required* parameters (not `Optional`, unlike
   `ADR-027`'s permissive-default `PortfolioState`/`TradeHistory`) —
   there is no "assume favorable and warn" path this late in the
   pipeline. Any rule whose supporting `AccountState` field is `None`
   (e.g. no consistency-rule data yet available) is treated as **not
   yet applicable** (skipped, never as "passed") rather than blocking
   or silently passing — see `rule_profile.py`.
4. **No duplicate calculations.** Evidence, strategy, risk, and market-
   intelligence facts are read from the four upstream snapshots exactly
   as computed — never recomputed. Position/currency exposure math
   reuses `titan_protocol.risk_engine.exposure`'s existing pure functions
   rather than a second implementation (§2).
5. **No MT5 or Bridge communication**, direct or indirect.
6. **Pure deterministic logic, thread safe.** No mutable state held by
   `ComplianceEngine` itself (§3); every computation is a pure function
   of its six inputs plus `now`.
7. **Every decision is fully explainable** — approvals, reductions, and
   rejections alike carry a reason, the triggered rule(s), the
   original recommendation, and the final recommendation (§7).
8. **The Compliance Score (§6) never gates a decision.** It is a
   derived, informational 0–100 operational-health metric for
   dashboards/monitoring only; the rule-based APPROVE/REDUCE/REJECT
   decision is computed independently and is authoritative.
9. **Never hard-code a specific prop firm's rules.** `ComplianceRuleProfile`
   (§5.5) is a fully generic, config-driven bundle of named thresholds;
   the shipped default is documented as an illustrative example, not a
   literal "FTMO" profile.

---

# 5. Rule categories

## 5.1 Daily Loss Protection (graduated safety curve)

Configurable bands against `daily_loss_pct` (derived from
`AccountState.daily_starting_balance`/`account_balance`, never
supplied pre-computed — this is this engine's own first computation of
that percentage, not a duplicate of anything upstream):

| Band (task's own example, 5% daily limit) | Behavior |
|---|---|
| 0–50% of limit | Normal operation |
| 50–70% | Reduce maximum position size |
| 70–80% | Significant reduction; new trades require exceptionally-high confidence (`EvidenceSnapshot.report.score.composite ≥ config.exceptional_confidence_min_evidence_score`), else reject |
| 80–90% | Only the highest-quality setups considered (`StrategySnapshot` qualification score ≥ `config.highest_quality_min_strategy_score`), else reject; additional reduction applied |
| ≥ 90% | Reject all new positions; existing positions continue to be managed; compliance lock recommended until next trading day |

## 5.2 Total Drawdown Protection

Same graduated-curve shape as 5.1, applied to
`(peak_balance - account_balance) / peak_balance`, with its own
configurable bands and a hard reject at the configured
`max_total_drawdown_pct`. Never trades into the hard limit — the last
configured band always rejects, it never merely reduces to a nonzero
size at the boundary.

## 5.3 Daily Profit Protection (optional, enabled by default)

Graduated bands against `daily_profit_pct` (task's own example: +2%,
+3%, +4%) that reduce risk and, per `config.profit_protection_stops_new_positions`,
optionally reject new positions once triggered — protecting gains
without ever *increasing* size.

## 5.4 Consecutive Loss Protection

`AccountState.consecutive_losses ≥ config.consecutive_loss_pause_threshold`
(default 3) → reject new entries until the caller's reset event clears
the counter in the next `AccountState` it supplies (this engine never
tracks the counter itself — §3).

## 5.5 Configurable Rule Profile (generic, never hard-coded to one firm)

`ComplianceRuleProfile` bundles every named threshold from the task:
maximum daily loss, maximum total loss, profit target (informational —
never blocks a trade), minimum trading days (informational),
maximum open positions, maximum trades per day, weekend holding
allowed, required stop loss, maximum spread, news-restriction enabled,
approved trading sessions, and the consistency-rule ratio (§3). Every
field is named and configurable; the shipped default is documented as
an illustrative example profile.

**"Required Stop Loss" scope note:** none of the four upstream
snapshots carry an order-level stop-loss price — that is an execution-
mechanics fact that belongs to the not-yet-built Execution Validator
(`ADR-007`'s slot, next in the `ADR-001` pipeline). This engine checks
the only stop-loss-adjacent fact available to it: `RiskSnapshot`
sizes exclusively in R-multiples, which by construction presupposes a
defined stop-loss distance (`recommended_position_size.final_r > 0`).
Verifying an actual attached stop-loss order remains Execution
Validator's responsibility and is out of scope here — documented rather
than silently mis-implemented.

## 5.6 Session Restrictions

Default approved sessions: London, London/NY Overlap, Early New York
(matching `EvidenceSnapshot.session.session`, an existing
`SessionName` value — no new enum). Reject new entries outside the
approved set.

## 5.7 News / Peg / Market-Safety Restrictions

Read directly and only from `MarketIntelligenceSnapshot.pair_safety`:
`news.blackout_active`, `peg_policy.active`, `market_safety.is_holiday`/
`broker_maintenance`/`trading_halted`/`market_closed`. Never queries
News/Trading Economics/Forex Factory itself.

## 5.8 Position Limits

Maximum open positions, maximum positions per pair, maximum currency
exposure, maximum symbol exposure, maximum pending orders (from
`AccountState.pending_orders_count`), maximum simultaneous risk —
computed from `PortfolioState` via `titan_protocol.risk_engine.exposure`'s
existing pure functions plus this engine's own, independently
configured thresholds (distinct from Risk Engine's own limits, which
represent a different authority's risk-management posture, not a
prop-firm's operational cap — see §2).

## 5.9 Trade Validation (the full reject checklist)

Stop-loss missing (§5.5), spread too high, pair disabled (config list),
session closed, news blackout, compliance lock active, daily limit
exceeded, drawdown exceeded, weekend restriction (derived from `now`'s
day-of-week/hour against a configured cutoff — no new input needed).

## 5.10 Emergency Protection

Compliance Lock and Emergency Stop are read from `AccountState` (§3);
`lock.py` provides pure helpers (`apply_daily_reset`,
`apply_operator_unlock`) the caller uses to construct the *next*
`AccountState` — this engine issues a `lock_recommendation`, it never
mutates lock state itself. Audit Trail is every `ComplianceSnapshot`'s
`audit_entry` field (§7).

## 5.11 Compliance Score (0–100, informational only)

Not a trading score. Reflects how close the account is to violating
its configured limits (100 = full headroom, 0 = locked) — purely for
dashboard/monitoring, computed independently of and never substituting
for the rule-based decision (Hard Rule 8).

---

# 6. Reduction combination

Every applicable graduated-curve multiplier (5.1–5.3) is collected;
the final multiplier is `min()` of all of them (the same "smallest
method always wins" discipline `ADR-027` established for its own
sizing methods) — never a compounding product, avoiding surprise
stacking. `final_approved_risk_r = original_risk_r * min(multipliers)`,
never exceeding `original_risk_r`. If any multiplier `< 1.0` was
applied and the trade is not rejected, decision = `REDUCE`; if no
multiplier applies, decision = `APPROVE`.

---

# 7. Output — `ComplianceSnapshot`

`decision` (`APPROVE`/`REDUCE`/`REJECT`), `approved_size_r`,
`original_size_r`, `reduction_pct`, `reason`, `triggered_rules`,
`warnings`, `audit_entry` (decision, triggered rule(s), original/final
size, timestamp), `compliance_score`, `lock_recommendation`,
`ready_for_bridge` (`True` only when `decision != REJECT` and
`approved_size_r > 0`). No execution, no direction, ever.

---

# 8. Architecture

```
titan_protocol/compliance_engine/
    __init__.py
    models.py              AccountState, ComplianceLockState, ComplianceDecision,
                          ComplianceRuleProfile, AuditEntry, ComplianceSnapshot, etc.
    config.py               ComplianceEngineConfig -- every threshold named
    daily_loss.py            graduated daily-loss-protection curve
    drawdown.py              graduated total-drawdown curve
    profit_protection.py     optional daily-profit-protection curve
    consecutive_loss.py      consecutive-loss pause logic
    rule_profile.py          the configurable FTMO-style rule checks
    position_limits.py       position/exposure limits (reuses risk_engine.exposure)
    market_conditions.py     session/news/peg/market-safety checks
    lock.py                  pure compliance-lock/emergency-stop state helpers
    compliance_score.py      the 0-100 operational health score
    explainability.py        ComplianceSnapshot assembly + audit trail
    engine.py                ComplianceEngine.evaluate()/evaluate_batch() (pure, stateless)
    logging_sink.py, metrics.py

tests/titan_protocol/compliance_engine/
    _fixtures.py, test_daily_loss.py, test_drawdown.py, test_profit_protection.py,
    test_consecutive_loss.py, test_rule_profile.py, test_position_limits.py,
    test_market_conditions.py, test_lock.py, test_compliance_score.py,
    test_engine.py, test_boundary.py, test_concurrency.py, test_stress.py,
    test_regression.py, test_architecture.py, test_determinism.py,
    test_explainability.py, test_failure_mode.py, test_ftmo_profile.py

docs/adr/ADR-028-compliance-engine.md
```

---

# 9. Testing mandate

Unit, boundary, concurrency, stress, regression, architecture,
determinism, explainability, failure mode, FTMO-profile — 10
categories, exactly as specified.

# 10. Performance

28+ Forex pairs, concurrent evaluation, thread safe (trivially, via
statelessness), deterministic, no duplicate statistical/exposure
calculations across a batch call.
