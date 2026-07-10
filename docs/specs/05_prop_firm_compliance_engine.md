# Technical Specification — Prop Firm Compliance Engine

Specification only. Cross-references `PHANTOM_FINAL_ARCHITECTURE.md`
and `PHANTOM_IMPLEMENTATION_ROADMAP.md` Phase 6.

## 1. Purpose

The single hard-gate authority for regulatory/prop-firm rules. Takes
Risk Engine's `SizingRecommendation` and either passes it through
unchanged, shrinks it, or rejects it outright — it may never enlarge
what Risk Engine proposed.

## 2. Responsibilities

- Enforce FTMO-style rule sets: daily loss limit, overall drawdown
  limit, minimum trading-day rules, maximum concurrent position count,
  maximum daily trade count.
- Maintain emergency-lockout state once a hard limit is breached.
- Translate an approved `SizingRecommendation` into exactly the
  `phantom.bridge.models.TradeCommand`/`CommandKind` shape Phase 1's
  `BridgeEngine.submit_command` already accepts.

## 3. Public interfaces

```
compliance_engine.evaluate(sizing: SizingRecommendation, account: AccountState, now: Clock)
    -> Union[TradeCommand, ComplianceRejection]
compliance_engine.is_locked_out(now: Clock) -> bool
```

## 4. Inputs

- `SizingRecommendation` (Risk Engine).
- `AccountState` (balance/equity history, trade count, trading-day
  count) — sourced from PhantomBridgeEA's existing telemetry.
- Rule-set configuration (`config.py`) — pluggable per prop firm; FTMO
  is the named, configured default, not a hardcoded assumption baked
  into the engine itself (a second prop firm's rules are additive
  configuration, never a second compliance engine).

## 5. Outputs

`TradeCommand` (the exact shape `phantom/bridge/models.py` already
defines — `CommandKind`, symbol, volume, stop_loss, take_profit,
correlation_id, etc.) on approval, or `ComplianceRejection` (reason:
which rule was breached) on rejection. No third outcome exists.

## 6. Internal data models

| Model | Shape |
|---|---|
| `ComplianceRuleSet` | named rule set (e.g. "FTMO"), with daily-loss/total-drawdown/trading-day/position-limit/trade-limit parameters |
| `ComplianceDecision` | internal union of pass-through, shrink, or reject, with the specific rule and margin that drove it |
| `ComplianceRejection` | `(rule_name, reason, measured_value, limit_value)` |
| `EmergencyLockoutState` | active/inactive, trigger reason, triggered_at |

## 7. Decision authority

The sole hard-gate authority for regulatory/prop-firm rules. May only
shrink or reject a `SizingRecommendation`, never enlarge it — enforced
by `SizingRecommendation`'s own type constraints (§6 of the Risk Engine
spec) plus this component's own contract of never constructing a
`TradeCommand` with a volume greater than the input `SizingRecommendation.volume`.

## 8. Dependencies

Portfolio Statistical Risk Engine (Phase 5), PhantomBridgeEA (Phase 1,
account-state telemetry and the `TradeCommand` shape it consumes).

## 9. Explicit non-responsibilities

- Never computes statistical risk (Monte Carlo, VaR, Sharpe, etc.) —
  consumes Risk Engine's output only.
- Never selects a strategy or evaluates market/news conditions.
- Never talks to MT5 directly — its only output is a `TradeCommand`
  value handed to the existing `BridgeEngine.submit_command`; it holds
  no broker connection of its own (one execution authority, per the
  lock).
- Never enlarges a `SizingRecommendation`'s volume under any
  circumstance, including a rule that would otherwise seem to permit
  more risk — this engine only ever removes risk, never adds it.

## 10. Test plan

- Unit tests per rule (`daily_drawdown.py`, `total_drawdown.py`,
  `trading_day_rules.py`, `position_limits.py`, `daily_trade_limits.py`,
  `emergency_lockout.py`) against fixture account histories, including
  exact-boundary cases (exactly at the limit, one unit over, one unit
  under).
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
| Account-state telemetry stale/unavailable | Fail closed: `ComplianceRejection` with a named reason, never a pass-through on unknown account state. |
| Rule-set configuration missing/invalid for the active account | Fail closed at startup (refuse to evaluate at all) rather than falling back to a default/implicit rule set. |

## 13. Security considerations

In-process library, no external network surface. Rule-set
configuration is read-only at evaluation time; any operator action to
clear an emergency lockout must be logged with who/when (see §14).

## 14. Logging requirements

`logging_sink.py` logs every `evaluate()` call's inputs/outputs
including rejections with the specific rule and measured value, and
every emergency-lockout state transition with its trigger reason and
(if cleared) who/when cleared it. `metrics.py` tracks rejection counts
by rule, lockout duration, and approaching-limit warnings (e.g.
"80% of daily loss limit used") for observability before a hard
breach.
