# Phantom Runtime Orchestrator — Phase 3A Deliverables Report

**Status:** Complete. Runtime Orchestrator, Configuration Management,
Trading Profiles, and Runtime Wiring implemented per
`docs/adr/ADR-031-runtime-orchestrator.md` (Accepted). Per the task's
own "STOP" instruction, **commercial features, licensing, cloud
services are not started**, and no existing engine was redesigned.

---

## 0. A mid-phase architecture amendment

Building the Bridge-handoff step surfaced a real gap: no engine in the
five-engine pipeline (Evidence, Market Intelligence, Strategy, Risk,
Compliance) produces a trade direction, yet `TradeCommand` requires
one. Per explicit user architecture decision, `docs/adr/ADR-026-
strategy-engine.md` Amendment 1 was drafted and accepted first: the
Strategy Engine is the sole owner of `TradeIntent` (BUY/SELL/NONE),
derived exclusively from each strategy's own already-computed
entry-thesis facts (CHOCH/BOS direction, trend classification,
confluence-zone support/resistance labels). This was committed
separately (`a071305`) before Runtime itself was built, since Runtime's
Bridge handoff depends on it. See that commit and
`PHANTOM_RUNTIME_ORCHESTRATOR_PHASE3A_REPORT.md`'s own history for the
full rationale; it is not restated here.

## 1. Design decisions

1. **`docs/specs/00_runtime_orchestrator.md` is ideas-only, not
   authority.** Its pipeline shape and method names predate every
   engine actually built this session (`ADR-024`-`ADR-030`). ADR-031
   supersedes it, reusing its ideas (fail-closed halt handling, per-pair
   isolation, a `CycleReport` concept, "no decision-shaped name" as the
   structural test) against the real six-engine pipeline's real
   interfaces.
2. **Watchdog integration is a fresh module, never `phantom_pipeline.
   watchdog`.** Every `phantom/` package built this session enforces
   "zero import of `phantom_pipeline`" as an architecture invariant;
   importing the existing Watchdog would have been the first exception.
   `phantom/runtime/watchdog_integration.py` mirrors `ADR-011`'s
   vocabulary (timeout kinds, component/kind shape) without importing
   it.
3. **`TradeCommand.stop_loss`/`take_profit` are `None` this phase** --
   no engine currently computes an absolute price level (Risk Engine
   expresses risk in R-multiples/lot size only), and
   `phantom.bridge.validation.check_stop_loss_take_profit` already
   accepts `None` for both. Disclosed as a scope boundary, not a defect.
4. **`TradeCommand.volume` is arithmetic, not a decision:** an
   already-computed lot size scaled by an already-computed reduction
   percentage (`ComplianceSnapshot.reduction_pct`). Runtime chooses
   neither value.
5. **Default `TradingProfile.allowed_pairs` is the union of every
   strategy's own approved-pair universe** (`StrategyEngineConfig`'s
   single source of truth), not an independently-invented list --
   avoiding exactly the "a profile claims eligibility a strategy
   doesn't grant" gap SS11's own validation exists to catch (a bug
   caught by this phase's own test suite before being fixed).
6. **`ended_at`/`started_at` both equal the single caller-supplied
   `now`, never a fresh `datetime.now()` read** -- an early draft bug:
   mixing wall-clock reads with the caller's `Clock` would have broken
   the ADR's own determinism requirement. `duration_ms`/`stage_timings`
   remain real `time.monotonic()` telemetry, explicitly excluded from
   the determinism comparison (they are operational metrics, not
   decisions).

## 2. Folder structure

```
phantom/runtime/
    __init__.py
    models.py              TradingWindow, TradingProfile, RuntimeContext,
                            CycleStage/Outcome, RuntimeAuditRecord, CycleReport,
                            ConfigValidationIssue/Result, WatchdogTimeoutKind/Signal
    config.py               RuntimeConfig (magic number, slippage, timeouts)
    profiles.py             6 named Trading Profile factories
    validation.py           Startup configuration validation (ADR-031 SS11)
    bridge_handoff.py       TradeCommand construction (arithmetic only)
    watchdog_integration.py Fresh timeout-detection + restart allow-list
    engine.py               RuntimeOrchestrator.run_cycle_for_pair()/run_cycle()
    logging_sink.py, metrics.py

tests/phantom/runtime/
    _fixtures.py
    test_runtime.py           (Runtime)
    test_integration.py       (Integration -- real engines, no stubs)
    test_configuration.py     (Configuration)
    test_concurrency.py       (Concurrency)
    test_stress.py            (Stress)
    test_failover.py          (Failover)
    test_recovery.py          (Recovery -- Watchdog integration)
    test_performance.py       (Performance -- 28 pairs sub-250ms)
    test_architecture.py      (Architecture)
    test_regression.py        (Regression -- determinism)
```

## 3. File list

10 production files, 1,041 lines. 12 test files, 970 lines. 43 tests.

## 4. Interfaces

- `RuntimeOrchestrator(config, evidence_engine, market_intelligence_engine, strategy_engine, risk_engine, compliance_engine, bridge_submit=None, metrics=None)`
- `.run_cycle_for_pair(pair, bars, events, current_spread, average_spread, market_safety_inputs, portfolio_state, trade_history, account_state, profile, now, cycle_id) -> RuntimeAuditRecord`
- `.run_cycle(pairs, profile, inputs, now, cycle_id) -> CycleReport`
- `validate_profile(profile, strategy_config, compliance_config) -> ConfigValidationResult`
- `detect_timeouts(stage_timings, total_duration_ms, config) -> Tuple[WatchdogSignal, ...]`, `is_approved_for_restart(component) -> bool`

## 5. Dependency graph

`runtime` -> `evidence_engine.engine/models`, `market_intelligence.engine/models/config`, `strategy_engine.engine/models/config`, `risk_engine.engine/models/config`, `compliance_engine.engine/models/config`, `bridge.models` (types only -- no `BridgeEngine` construction; the caller injects a bound `submit_command`). Zero import of `phantom_pipeline` or `phantom.validation_engine`.

## 6. Configuration schema

`TradingProfile`: `profile_id`, `version`, `created_at`, `modified_at`, `author`, `description`, `trading_window` (`TradingWindow`), `allowed_pairs`, `allowed_strategies`, `session_rules`, `news_policy` (`MarketIntelligenceConfig`), `risk_profile` (`RiskEngineConfig`), `compliance_rule_profile_name`.

## 7. Runtime sequence (per pair, per cycle)

```
trading-window check -> Evidence -> [session-rules check] -> Market Intelligence
    -> Strategy -> [rejected? stop] -> Risk -> [not approved? stop]
    -> Compliance -> [REJECT? stop] -> Bridge (if ready_for_bridge) -> RuntimeAuditRecord
```

## 8. Testing report

43 new tests across the task's own 10 categories. Full repo suite:
**2,426/2,426 passing** (up from 2,383 after the ADR-026 amendment,
2,368 before it). `scripts/check_architecture.py`: PASS (unaffected).

## 9. Performance

28-pair cycle (stub engines, representative of Runtime's own
sequencing overhead): well under the 250ms budget in the test suite.

## 10. Architecture verification

- No decision-shaped vocabulary (select_strategy/calculate_risk/
  make_compliance_decision/override_engine/generate_signal) anywhere in
  package source.
- No import of `phantom_pipeline` or `phantom.validation_engine`.
- Only the five permitted upstream `phantom/` packages plus
  `phantom.bridge.models` (types only) imported.
- `RuntimeOrchestrator` exposes no `select`/`score`/`decide`/`approve`/
  `reject`/`override` method.
- Compliance Engine and Bridge are never in the Watchdog restart
  allow-list (structural test, not a runtime check).

## 11. Confirmation

`git status --short` on `phantom/bridge`, `phantom/evidence_engine`,
`phantom/market_intelligence`, `phantom/risk_engine`,
`phantom/compliance_engine`, `phantom/research_engine`,
`phantom/validation_engine`, their test directories,
`scripts/check_architecture.py`, and `phantom_pipeline/` shows **zero
changes** in this diff (the Strategy Engine amendment was committed
separately, `a071305`, before this report). Validation Engine was never
imported and never participates in live execution.

## Recommendation

Ship as-is. Per the task's own instruction, commercial features,
licensing, and cloud services are out of scope; no existing engine was
redesigned. Awaiting approval before further phases.
