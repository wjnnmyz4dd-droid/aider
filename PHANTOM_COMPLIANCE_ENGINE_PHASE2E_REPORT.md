# Phantom Prop Firm Compliance Engine — Phase 2E Implementation Report

**Status:** Complete. Bridge, Evidence Engine, Market Intelligence
Engine, Strategy Engine, and Risk Engine remain frozen and byte-for-byte
untouched this phase. Research & Learning Engine and Validation are
explicitly **not** started, per this phase's own scope.

Authority: `docs/adr/ADR-028-compliance-engine.md` (Accepted, this
session — first drafted as Proposed after only the Daily Loss Safety
Buffer requirement was given, then rewritten to Accepted once the full
spec arrived). Scope: `phantom/compliance_engine/` — a new, independent
package, built fresh with no reuse of `phantom_pipeline/compliance/`.

---

## 0. This phase's design decisions (documented, not silently invented)

Two-part specification: the Daily Loss Safety Buffer arrived first (no
Phase 2E kickoff yet), so it was recorded as ADR-028 **Proposed** and
implementation was withheld per CLAUDE.md §1.10 until the full mission
arrived. Once it did, three real gaps needed resolving before any code
was written — each documented in ADR-028 rather than guessed silently:

1. **`AccountState` (new type).** None of the six named inputs
   (`EvidenceSnapshot`, `MarketIntelligenceSnapshot`, `StrategySnapshot`,
   `RiskSnapshot`, `PortfolioState`, `AccountState`) actually define
   `AccountState`'s shape — it's named as an input but its fields were
   left to this implementation. Modeled exactly like `ADR-027`'s
   `PortfolioState`/`TradeHistory` precedent: pre-aggregated facts only
   (balances, consecutive-loss count, trading-day count, today's trade
   count, pending-order count, consistency-rule aggregates, lock/
   emergency-stop state), never raw trade history.
2. **Compliance lock/emergency stop are caller-owned, not engine-
   internal.** Unlike Risk Engine's `ReservationLedger` (which solves a
   same-process concurrent-approval race), a compliance lock must
   survive across calls and process restarts — genuinely operational
   state. `ComplianceEngine.evaluate()` holds **no mutable state at
   all**; it reads `AccountState.compliance_lock` and emits an advisory
   `lock_recommendation` the caller persists into the *next*
   `AccountState`. This also satisfies the task's own "pure
   deterministic logic" rule literally: a stateless function is
   trivially thread-safe.
3. **"Required Stop Loss" scope note.** No upstream snapshot carries an
   order-level stop-loss price (that belongs to the not-yet-built
   Execution Validator, next in the `ADR-001` pipeline). This engine
   checks the only stop-loss-adjacent fact available: `RiskSnapshot`
   sizes exclusively in R-multiples, which by construction presupposes
   a defined stop-loss distance.
4. **The Consistency Rule** (no single day's profit may exceed a
   configured share of total profit) is evaluated from two
   pre-aggregated `AccountState` fields (`best_single_day_profit_pct`,
   `cumulative_profit_pct`) rather than `TradeHistory`, since
   `TradeHistory` is not among this engine's six named inputs and
   re-deriving day-by-day P&L here would itself be a duplicate
   calculation.

Full reasoning in ADR-028 §0/§3.

---

## 1. Folder structure

```
phantom/compliance_engine/
    __init__.py
    models.py               AccountState, ComplianceLockState, ComplianceDecision,
                           ComplianceRuleProfile, GraduatedBand, AuditEntry,
                           ComplianceSnapshot, LockRecommendation, etc.
    config.py                ComplianceEngineConfig -- every threshold/band named
    bands.py                 shared graduated-band evaluator (daily loss/drawdown/
                           profit protection all reuse one function, not three)
    daily_loss.py            graduated Daily Loss Protection curve
    drawdown.py              graduated Total Drawdown Protection curve
    profit_protection.py     optional Daily Profit Protection curve
    consecutive_loss.py      Consecutive Loss Protection
    rule_profile.py          weekend holding, required stop loss, max trades/day,
                           consistency rule, disabled pairs, informational-only checks
    position_limits.py       position/exposure limits (reuses phantom.risk_engine.exposure)
    market_conditions.py     session restriction + news/peg/market-safety checks
    lock.py                  pure compliance-lock/emergency-stop helpers (caller-owned)
    compliance_score.py      the 0-100 operational health score (informational only)
    explainability.py        ComplianceSnapshot assembly + audit trail
    engine.py                ComplianceEngine.evaluate()/evaluate_batch() (pure, stateless)
    logging_sink.py, metrics.py

tests/phantom/compliance_engine/
    _fixtures.py, test_daily_loss.py, test_drawdown.py, test_profit_protection.py,
    test_consecutive_loss.py, test_rule_profile.py, test_position_limits.py,
    test_market_conditions.py, test_lock.py, test_compliance_score.py,
    test_engine.py, test_boundary.py, test_concurrency.py, test_stress.py,
    test_regression.py, test_architecture.py, test_determinism.py,
    test_explainability.py, test_failure_mode.py, test_ftmo_profile.py

docs/adr/ADR-028-compliance-engine.md
```

## 2. File list

17 production files (1,219 lines), 21 test files including fixtures
(1,600 lines), 1 ADR (drafted, then revised to Accepted), 1 report.
`phantom/bridge/`, `phantom/evidence_engine/`, `phantom/market_intelligence/`,
`phantom/strategy_engine/`, `phantom/risk_engine/`, `phantom_pipeline/`,
and `scripts/check_architecture.py` are byte-for-byte unchanged this
phase — confirmed via `git status`.

## 3. Interfaces

```python
ComplianceEngine(config, metrics=None)
    .evaluate(pair, evidence: EvidenceSnapshot, market_intelligence: MarketIntelligenceSnapshot,
              strategy: StrategySnapshot, risk: RiskSnapshot, portfolio_state: PortfolioState,
              account_state: AccountState, now=None) -> ComplianceSnapshot
    .evaluate_batch(pairs: Dict[str, Tuple[..., RiskSnapshot]], portfolio_state, account_state, now=None)
        -> Tuple[ComplianceSnapshot, ...]

evaluate_graduated_bands(pct, bands, evidence_score=None, strategy_score=None) -> BandEvaluation
evaluate_daily_loss_protection / evaluate_drawdown_protection / evaluate_profit_protection(...)
consecutive_loss_pause_triggered(account, config) -> bool
check_pair_disabled / check_weekend_restriction / check_required_stop_loss /
    check_max_trades_per_day / check_consistency_rule(...)
check_position_limits(pair, candidate_risk_r, portfolio_state, account, profile)
    -> Tuple[Optional[ComplianceRuleId], ExposureSummary]
check_session_restriction / check_market_safety / check_news_blackout /
    check_peg_policy / check_max_spread(...)
is_locked / apply_daily_reset / apply_operator_unlock / trigger_lock(account, ...) -> AccountState
compute_compliance_score(account, profile, config) -> float
build_compliance_snapshot(...) -> ComplianceSnapshot
```

No method anywhere accepts or returns a trade direction, a strategy
choice, or an executed order — verified by `test_architecture.py`.

## 4. Data models

`ComplianceDecision` (`APPROVE`/`REDUCE`/`REJECT`), `ComplianceRuleId`
(29 named rules), `GraduatedBand` (one type shared by all three
graduated curves), `ComplianceRuleProfile` (a fully generic,
config-driven prop-firm rule bundle — 18 named thresholds, never
hard-coded to a specific firm), `ComplianceLockState`,
`LockRecommendation`, `AccountState` (caller-supplied, pre-aggregated
operational facts only), `AuditEntry`, `ComplianceSnapshot` (decision,
approved/original size, reduction %, reason, triggered rules, warnings,
audit entry, compliance score, lock recommendation, ready-for-bridge —
no execution, ever). All frozen dataclasses.

## 5. Dependency graph

```
phantom.evidence_engine.models.EvidenceSnapshot            <- read-only, engine.py, market_conditions.py
phantom.market_intelligence.models.MarketIntelligenceSnapshot <- read-only, engine.py, market_conditions.py
phantom.strategy_engine.models.StrategySnapshot            <- read-only, engine.py
phantom.risk_engine.models.RiskSnapshot/PortfolioState      <- read-only, engine.py, rule_profile.py, position_limits.py
phantom.risk_engine.exposure.compute_exposure_summary/split_currency_pair <- reused directly by position_limits.py
                                                               (no second exposure implementation)

models.py, config.py       <- everything else in this package
bands.py                    <- daily_loss.py, drawdown.py, profit_protection.py
lock.py, compliance_score.py, explainability.py  <- engine.py
engine.py                   <- __init__.py (only)
```

No cycles. Nothing imports `phantom_pipeline` or `phantom.bridge`
(AST-verified); the only upstream imports are the four named engines'
`.models`/`.exposure` (this is the first `phantom/` stage to
necessarily depend on another `phantom/` stage, since `RiskSnapshot`
and `PortfolioState` are Risk Engine's own types — disclosed in ADR-028
§0). `random` is not imported anywhere in this package (AST-verified) —
this engine has no Monte Carlo component; every decision is a pure
function of its six inputs.

## 6. Testing report

- New suite: **116/116 pass** across 21 files, covering all 10
  mandated categories (unit, boundary, concurrency, stress, regression,
  architecture, determinism, explainability, failure mode, FTMO
  profile).
- Unit/boundary: every graduated-curve band boundary (exactly at 50%,
  70%, 80%, 90% of the daily-loss limit; the drawdown curve's hard
  floor), the confidence/quality gates at the 70-80%/80-90% bands
  (verified both passing and failing), zero-balance edge cases.
- Concurrency: 64 threads racing the same pair produce byte-identical
  results (trivially, since the engine holds zero mutable state); 10
  distinct pairs across 10 threads, 10 calls each, zero errors.
- Stress: a 28-pair `evaluate_batch()` completes in **~0.8ms total
  (~0.03ms/pair)** — the fastest engine built this session, since
  statelessness means no lock contention and no per-call allocation of
  engine-held state.
- Regression: two fixed known-good anchors, including the exact 75%-
  daily-loss/low-evidence-score scenario worked through during
  development (must reject, not merely reduce).
- Architecture: no forbidden direction/execution/strategy-selection
  vocabulary, no `phantom_pipeline`/`phantom.bridge` import, only the
  four permitted upstream packages imported, no `random`/ML import
  anywhere, `ComplianceEngine.__init__` assigns exactly `self.config`
  and `self.metrics` and nothing else (AST-verified statelessness), no
  reservation/lock-ledger-shaped public method, and every shipped
  default `GraduatedBand.multiplier <= 1.0` (structural proof this
  engine can never be configured, even by default, to increase risk).
- Determinism: repeated calls, two independent engine instances, and
  `evaluate_batch()` vs. individual calls all produce byte-identical
  `ComplianceSnapshot`s.
- Explainability: every approve/reduce/reject path carries a non-empty
  reason, a populated audit entry, and a compliance score.
- Failure mode: emergency stop and compliance lock both override even a
  perfectly healthy account; missing consistency-rule data is neither a
  pass nor a violation (a rule not yet applicable); `portfolio_state`/
  `account_state` are mandatory parameters, not optional-with-default,
  so a caller genuinely cannot construct an "unknown state" call.
- FTMO-profile-style: a custom illustrative profile (never hard-coded)
  demonstrates that swapping the active profile alone changes the
  approve/reject outcome for an identical trade — proof the rule set is
  real configuration, not a hidden branch.
- Full repository suite: **2,252/2,252 pass**. `compileall` clean.
  `scripts/check_architecture.py` (scoped to `phantom_pipeline/`):
  PASS, unaffected.

## 7. Performance

`evaluate_batch()` across the task's own 28-pair Forex universe:
**~0.8ms total, ~0.03ms/pair** — statelessness means no reservation
lock, no Monte Carlo, and no per-call mutable-state bookkeeping, making
this the cheapest engine of the five built this session.

## 8. Coverage

All 17 production modules have at least one direct test file; every
public function/method in the interface list (§3) is exercised,
including the reject cascade's fixed ordering (emergency stop →
compliance lock → Risk Engine authority → market conditions →
operational/behavioral gates → graduated reduction curves).

## 9. Architecture verification

- No forbidden direction/execution/strategy-selection vocabulary bound
  anywhere in the package (AST-based, scoped to what this engine must
  never do).
- No import of `phantom_pipeline` or `phantom.bridge`; only
  `phantom.evidence_engine`, `phantom.market_intelligence`,
  `phantom.strategy_engine`, and `phantom.risk_engine` are imported
  upstream (the last of these disclosed as this session's first
  necessary `phantom/`-to-`phantom/` dependency, ADR-028 §0).
- No ML-library import; no `random` import at all (this engine has no
  simulation component).
- `ComplianceEngine` holds no mutable state beyond `config`/`metrics`
  (AST-verified) — pure, trivially thread-safe.
- Every shipped default graduated-band multiplier is `<= 1.0` —
  structurally provable this engine can never increase risk.
- `scripts/check_architecture.py` (scoped to `phantom_pipeline/`):
  PASS, unaffected.
- `phantom/bridge/`, `phantom/evidence_engine/`,
  `phantom/market_intelligence/`, `phantom/strategy_engine/`, and
  `phantom/risk_engine/` are untouched, confirmed via `git status`.

---

## Recommendation

Ship as-is. The reject-cascade ordering is fixed and deterministic, the
graduated daily-loss/drawdown/profit-protection curves share one
implementation (not three), the confidence/quality gates at elevated
loss bands are real (verified both passing and failing), position/
exposure limits reuse Risk Engine's own pure functions rather than
duplicating them, and the rule profile is genuinely swappable
configuration, never a hard-coded firm's rules. Research & Learning
Engine and Validation remain out of scope for this phase, per the
original task's own boundaries. Awaiting direction on what's next.
