# Technical Specification — Prop Firm Compliance Engine

Specification only. Cross-references `PHANTOM_FINAL_ARCHITECTURE.md`
and `PHANTOM_IMPLEMENTATION_ROADMAP.md` Phase 6.

## 1. Purpose

The single hard-gate authority for regulatory/prop-firm rules. Takes
Risk Engine's `SizingRecommendation` and either passes it through
unchanged, shrinks it, or rejects it outright — it may never enlarge
what Risk Engine proposed.

## 2. Responsibilities

- Enforce a **configurable** prop-firm rule set covering, at minimum,
  all ten rule categories in §"FTMO configuration model" below (expanded
  from the original five — Architecture Hardening, closes Red Team
  Audit Findings 4.1, 11.1, 11.2, 11.3, 11.4).
- Maintain emergency-lockout state once a hard limit is breached.
- Translate an approved `SizingRecommendation` into exactly the
  `phantom.bridge.models.TradeCommand`/`CommandKind` shape Phase 1's
  `BridgeEngine.submit_command` already accepts.
- Reject stale account-state input rather than evaluate against it
  (closes Finding 4.1 — see §12).

## 3. Public interfaces

```
compliance_engine.evaluate(sizing: SizingRecommendation, account: AccountState, now: Clock)
    -> Union[TradeCommand, ComplianceRejection]
compliance_engine.is_locked_out(now: Clock) -> bool
```

Unchanged from the prior specification — the expansion below is entirely
in rule-set configuration and internal rule files, not in this public
surface.

## 4. Inputs

- `SizingRecommendation` (Risk Engine).
- `AccountState` (balance/equity history, trade count, trading-day
  count, open-position holding duration) — sourced from PhantomBridgeEA's
  existing telemetry. **Must carry a `received_at` timestamp `evaluate()`
  checks against a configured staleness threshold** (`config.py`'s
  `max_account_state_age_seconds`, no default assumed here) — stale
  input produces a `ComplianceRejection`, never a pass-through on
  unknown account state (closes Finding 4.1).
- The current news/calendar/holiday facts needed by the news-trading-
  restriction rule (§"FTMO configuration model" item 7), read from
  Market Intelligence Engine's event classification — reused, not
  reimplemented (no duplicate news processing).
- Rule-set configuration (`config.py`) — pluggable per prop firm; **no
  prop firm's name or rule values are hardcoded anywhere in this
  engine's logic.** `ComplianceRuleSet` is a named, fully data-driven
  configuration instance (e.g. `"FTMO_Challenge"`, `"FTMO_Verification"`,
  `"MyForexFunds_X"`); the engine code contains no conditional branch
  keyed on a prop-firm name — only on the configured parameter values.

## 5. Outputs

`TradeCommand` (the exact shape `phantom/bridge/models.py` already
defines — `CommandKind`, symbol, volume, stop_loss, take_profit,
correlation_id, etc.) on approval, or `ComplianceRejection` (reason:
which rule was breached) on rejection. No third outcome exists.

## 6. Internal data models

| Model | Shape |
|---|---|
| `ComplianceRuleSet` | named rule set (e.g. `"FTMO_Challenge"`), carrying all ten parameter groups in §"FTMO configuration model" — purely data, no code branches on the name |
| `ComplianceDecision` | internal union of pass-through, shrink, or reject, with the specific rule and margin that drove it |
| `ComplianceRejection` | `(rule_name, reason, measured_value, limit_value)` — `rule_name` now spans all ten categories, not five |
| `EmergencyLockoutState` | active/inactive, trigger reason, triggered_at |

## 7. Decision authority

The sole hard-gate authority for regulatory/prop-firm rules. May only
shrink or reject a `SizingRecommendation`, never enlarge it — enforced
by `SizingRecommendation`'s own type constraints (§6 of the Risk Engine
spec) plus this component's own contract of never constructing a
`TradeCommand` with a volume greater than the input `SizingRecommendation.volume`.

**Authority restatement (Architecture Hardening):** Prop Firm
Compliance Engine holds **rules authority only** (see the system-wide
authority matrix in `PHANTOM_ARCHITECTURE_HARDENING.md`) — approve,
reduce, or reject; never increase risk, never compute statistics,
never select a strategy.

## 8. Dependencies

Portfolio Statistical Risk Engine (Phase 5), PhantomBridgeEA (Phase 1,
account-state telemetry and the `TradeCommand` shape it consumes),
Market Intelligence Engine (read-only, for the news-trading-restriction
rule's event classification data).

## FTMO configuration model (Architecture Hardening — expansion)

`ComplianceRuleSet` is a data-only configuration object supporting, at
minimum, these ten parameter groups. Every one is optional per
configured rule set (a prop firm without a consistency rule simply
omits it); the engine's code path for each is identical regardless of
which prop firm's values are loaded — **do not hard-code FTMO**:

| # | Rule | File | Parameters |
|---|---|---|---|
| 1 | Daily loss | `daily_drawdown.py` | max daily loss (% and/or absolute) |
| 2 | Overall drawdown | `total_drawdown.py` | max total drawdown (% and/or absolute) |
| 3 | Max positions | `position_limits.py` | max concurrent open positions |
| 4 | Max trades/day | `daily_trade_limits.py` | max trades per trading day |
| 5 | Stop loss required | `stop_loss_required.py` (new file, closes Finding 11.4) | boolean; if true, reject any `SizingRecommendation`/resulting command with no stop-loss level set |
| 6 | Weekend holding | `weekend_holding_rule.py` (new file, closes Finding 11.2) | boolean (allowed/not allowed); if not allowed, positions must be flat ahead of the configured market-close boundary |
| 7 | News restrictions | `news_trading_restriction.py` (new file, closes Finding 11.1) | pre/post window widths around designated event classes, read from Market Intelligence Engine's classification (§4) — a *contractual* restriction, independently configured from and enforced separately atop Market Intelligence's own general-purpose news blackout |
| 8 | Consistency rules | folded into `daily_drawdown.py` (closes Finding 11.3; three similar lines before a new file, per Minimal Change Engineer) | max % of total profit attributable to a single trading day |
| 9 | Profit target tracking | folded into `daily_drawdown.py`'s existing daily-P&L bookkeeping (closes Finding 11.3) | optional target amount/percentage per account phase (challenge/verification/funded); tracked and reported, not itself a rejection reason unless a specific rule set says reaching it changes trading permissions |
| 10 | Trading day tracking | `trading_day_rules.py` | minimum required trading days, and this rule set's own definition of what counts as one (consulting Market Intelligence Engine's session/holiday authority per §6.1 of its spec, never an independently computed calendar) |

**Rule:** Compliance may **approve, reduce, or reject** a
`SizingRecommendation`. It may **never increase** the risk implied by
what Risk Engine already computed — this applies uniformly across all
ten rule categories, including any future one added the same
explicitly-approved way these were.

## 9. Explicit non-responsibilities

- Never computes statistical risk (Monte Carlo, VaR, Sharpe, etc.) —
  consumes Risk Engine's output only.
- Never selects a strategy.
- Never independently classifies news events or computes session/
  holiday state — reuses Market Intelligence Engine's classification
  (§4) rather than reimplementing it (no duplicate news processing).
- Never talks to MT5 directly — its only output is a `TradeCommand`
  value handed to the existing `BridgeEngine.submit_command`; it holds
  no broker connection of its own (one execution authority, per the
  lock).
- Never enlarges a `SizingRecommendation`'s volume under any
  circumstance, including a rule that would otherwise seem to permit
  more risk — this engine only ever removes risk, never adds it. This
  applies to all ten rule categories uniformly.
- Never hard-codes a specific prop firm's name or parameter values in
  its rule logic — every rule reads its thresholds from the active
  `ComplianceRuleSet` configuration only.

## 10. Test plan

- Unit tests per rule (`daily_drawdown.py`, `total_drawdown.py`,
  `trading_day_rules.py`, `position_limits.py`, `daily_trade_limits.py`,
  `emergency_lockout.py`, `stop_loss_required.py`,
  `weekend_holding_rule.py`, `news_trading_restriction.py`) against
  fixture account histories, including exact-boundary cases (exactly at
  the limit, one unit over, one unit under).
- **Multi-prop-firm configuration test** (closes the "do not hard-code
  FTMO" requirement): two different `ComplianceRuleSet` configurations
  (different parameter values, same engine code) produce different,
  independently-correct outcomes from the identical fixture input —
  proving no rule-set-name-specific branching exists anywhere in the
  engine.
- **Stop-loss-required test** (closes Finding 11.4): a fixture
  `SizingRecommendation`/command with no stop-loss level is rejected
  when the active rule set requires one, approved when it doesn't.
- **Weekend-holding test** (closes Finding 11.2): fixture open positions
  ahead of the configured market-close boundary are flagged/rejected
  per the active rule set's weekend-holding parameter.
- **News-trading-restriction test** (closes Finding 11.1): a fixture
  high-impact event window (from Market Intelligence Engine's fixture
  classification) produces a rejection distinct from, and independently
  configured from, Market Intelligence's own general blackout — proving
  the two are separately tunable, not the same mechanism wearing two
  names.
- **Consistency-rule and profit-target tests** (close Finding 11.3): a
  fixture day whose profit exceeds the configured single-day percentage
  of total profit is flagged per the consistency rule; profit-target
  tracking reports progress toward a configured target without
  rejecting trades unless the active rule set specifically says to.
- **Account-state freshness test** (closes Finding 4.1): an
  `AccountState` older than the configured threshold produces a
  `ComplianceRejection`, never a pass-through.
- Never-enlarges test: for every fixture `SizingRecommendation`, the
  resulting `TradeCommand`'s volume (if any) is `<=` the input's
  volume, across the full fixture matrix.
- End-to-end integration test: a Compliance-approved `TradeCommand`
  submitted into a real (test) `phantom.bridge.BridgeEngine` instance
  queues correctly — proving compatibility with the already-built
  Phase 1 code, not just an isolated fixture.
- Emergency-lockout test: once triggered, every subsequent `evaluate()`
  call returns `ComplianceRejection` regardless of the input
  `SizingRecommendation`, until explicitly cleared.

## 11. Performance requirements

`evaluate()` is a pure rule-check against already-loaded account
state; must be effectively instantaneous (no I/O in the hot path) —
target sub-millisecond, validated during implementation.

## 12. Failure modes

| Failure | Expected behavior |
|---|---|
| Account-state telemetry stale/unavailable (older than `max_account_state_age_seconds`) | Fail closed: `ComplianceRejection` with a named reason, never a pass-through on unknown account state (closes Finding 4.1). |
| Rule-set configuration missing/invalid for the active account | Fail closed at startup (refuse to evaluate at all) rather than falling back to a default/implicit rule set. |
| Market Intelligence Engine unreachable for the news-trading-restriction rule | Fail closed: treat as if the restriction window is active rather than assuming no restriction applies. |

## 13. Security considerations

In-process library, no external network surface. Rule-set
configuration is read-only at evaluation time; any operator action to
clear an emergency lockout must be authenticated and authorized through
the shared operator-authorization model
(`docs/specs/07_system_reliability_engine.md` §"Operator
authentication") — this component no longer defines its own ad hoc
notion of "operator" (closes Red Team Audit Finding 17.1).

## 14. Logging requirements

`logging_sink.py` logs every `evaluate()` call's inputs/outputs
including rejections with the specific rule (across all ten
categories) and measured value, every emergency-lockout state
transition with its trigger reason and (if cleared) the authenticated
operator identity and timestamp from the shared authorization model,
and every account-state-staleness rejection. `metrics.py` tracks
rejection counts by rule, lockout duration, and approaching-limit
warnings (e.g. "80% of daily loss limit used") for observability before
a hard breach.
