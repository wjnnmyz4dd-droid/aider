# Technical Specification — Validation (Offline Only)

Specification only. Cross-references `PHANTOM_FINAL_ARCHITECTURE.md`
and `PHANTOM_IMPLEMENTATION_ROADMAP.md` Phase 4b and §6 (standing
process).

## 1. Purpose

Provide the only path by which a proposed change to a Strategy Engine
playbook, a Risk Engine parameter, or a Compliance Engine rule set is
tested against history before it is ever proposed for the live path —
entirely offline, never invoked by or invoking the live decision chain.

## 2. Responsibilities

- Backtest a strategy/playbook against a historical range.
- Replay tick/bar history over a defined window.
- Run forward-test (paper) sessions.
- Generate performance reports.
- Compare strategies side by side.

## 3. Public interfaces

```
validation.backtest_engine.run(strategy_kind: StrategyKind, historical_range) -> BacktestResult
validation.replay_engine.replay(historical_window) -> ReplaySession
validation.forward_test.run(session_config) -> ForwardTestResult
validation.performance_reports.generate(result) -> PerformanceReport
validation.strategy_comparison.compare(results: Tuple[BacktestResult, ...]) -> ComparisonReport
```

`runner.py` is the CLI/entry point tying these together; it is not
itself a new public interface beyond what's listed.

## 4. Inputs

- Historical price data (independent of Evidence Engine's live
  `market_data_source.py` — Validation sources its own historical
  archive, since a backtest must be reproducible against a fixed,
  versioned dataset, not a live feed).
- The `models.py` types of every live component it evaluates against
  (Evidence Engine's `PairEvidence`, Strategy Engine's `TradeIdea`/
  `Playbook` interface, Risk Engine's `SizingRecommendation` shape) —
  imported for their data shapes only.
- Strategy/risk/compliance parameter sets under test.

## 5. Outputs

`BacktestResult`, `ReplaySession`, `ForwardTestResult`,
`PerformanceReport`, `ComparisonReport` — all offline artifacts, never
submitted anywhere live.

## 6. Internal data models

| Model | Shape |
|---|---|
| `BacktestResult` | strategy kind, historical range, trade log, aggregate performance stats |
| `ReplaySession` | historical window, replayed evidence/idea stream |
| `ForwardTestResult` | paper-session trade log and performance stats |
| `ComparisonReport` | side-by-side `BacktestResult` set with relative rankings |

Deliberately reuses each live component's own `models.py` types for
inputs/outputs rather than inventing parallel ones (per the
architecture freeze's file-list note) — a `BacktestResult`'s trade log
entries are the same `TradeIdea`/`SizingRecommendation` shapes the live
chain uses, just never submitted to `phantom.bridge`.

## 7. Decision authority

None over live trading, and none over historical data either beyond
what it's explicitly asked to replay/backtest — Validation does not
decide which strategy change gets promoted to live; it only produces
the evidence a human decision-maker (per the Charter's own
never-guess/ask-before-changing-execution-logic philosophy) uses to
decide.

## 8. Dependencies

Evidence Engine's `models.py` (Phase 3a) and Strategy Engine's
playbook interface (Phase 4a), consumed as each playbook lands — not
strictly sequenced after Phase 4a completes; the harness should exist
before all five playbooks are done so each is backtestable the moment
it's written.

## 9. Explicit non-responsibilities

- **Never imports any live component's `engine.py`/orchestrator module,
  and never imports `phantom/runtime/` at all** (Architecture Hardening
  — restated explicitly per this task's structural rules) — only
  `models.py` types, so the offline/online boundary is structurally
  checkable (mirrors Phase 1's own `test_structural_boundary.py`
  pattern).
- Never submits a command to PhantomBridgeEA, or to any live component
  at all.
- Never runs against a live/streaming data feed — its price history is
  a fixed, versioned historical archive, chosen specifically so a
  backtest run today and rerun next year against the same declared
  range produces the same result.
- Never auto-promotes a backtested change into the live Strategy
  Engine/Risk Engine/Compliance Engine configuration — that is always
  a separate, explicit, human-approved step outside this component.

## 10. Test plan

- Structural-boundary test: no file under `phantom/validation/` imports
  any live component's orchestrator module, and no file under
  `phantom/validation/` imports `phantom/runtime/` (grep-based, added
  by this hardening task's explicit structural rule) — only `models.py`
  types.
- Known-outcome regression test: a fixture historical window with a
  hand-verified expected `BacktestResult`, so a future change to
  `backtest_engine.py` itself is caught if it silently changes
  behavior.
- Determinism test: the same strategy/parameter set against the same
  declared historical range produces byte-identical results across
  repeated runs.
- Comparison test: `strategy_comparison.compare()` ranks a fixture set
  of `BacktestResult`s in the expected order for a hand-verified
  fixture.

## 11. Performance requirements

Not on any live-system critical path — no real-time latency
requirement. Backtest/replay runtime should scale predictably with the
declared historical range's length; document actual runtime
characteristics once implemented rather than assume them here.

## 12. Failure modes

| Failure | Expected behavior |
|---|---|
| Historical data archive incomplete for the requested range | Explicit error naming the missing sub-range — never silently interpolate or skip gaps in a way that changes the reported result without disclosure. |
| A strategy/parameter set under test throws during backtest | Caught, logged, and reported as a failed backtest run for that configuration — does not crash a `strategy_comparison.compare()` run across multiple configurations. |

## 13. Security considerations

Offline, no external network surface, no live credentials. Historical
data archive access should be read-only from this component's
perspective (it consumes history, it never writes back into whatever
system maintains the archive).

## 14. Logging requirements

Logs each backtest/replay/forward-test run's parameters and outcome
for reproducibility (so a later question "what exactly did we test
last month" can be answered from the log, not just memory). No
`metrics.py` counters in the same live-system-observability sense as
the other components — this is offline batch tooling, not a live
service — but a run history/audit log is still required.

**Authority restatement (Architecture Hardening):** Validation holds
**no live authority of any kind** — offline only, never imported by and
never importing any live component's orchestrator or `phantom/runtime/`
(see the system-wide authority matrix in
`PHANTOM_ARCHITECTURE_HARDENING.md`).
