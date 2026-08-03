# Technical Specification — Research & Learning Engine

Specification only. Cross-references `PHANTOM_FINAL_ARCHITECTURE.md`
and `PHANTOM_IMPLEMENTATION_ROADMAP.md` Phase 7. Advisory only; never
modifies live trading.

## 1. Purpose

Build and query a durable record of every completed trade's full
decision chain, to explain, review, and rank performance after the
fact — producing recommendations for a human, never a write path back
into the live decision chain.

## 2. Responsibilities

- Record every completed trade's full decision-chain snapshot (Evidence,
  Strategy, Intelligence, Risk, Compliance states at decision time) and
  PhantomBridgeEA's actual execution outcome.
- Provide RAG-based retrieval over trade memory for natural-language
  queries.
- Discover recurring patterns across trade memory.
- Attribute performance to strategy/pair/session, reading Risk Engine's
  stored rolling statistics rather than recomputing them.
- Generate a human-readable explanation for every trade.
- Produce weekly and monthly institutional-style reviews and a
  strategy ranking.
- Emit improvement recommendations — read-only outputs, never applied
  automatically.

## 3. Public interfaces

```
research_engine.record_trade(decision_chain_snapshot: DecisionChainSnapshot,
                              execution_report: ExecutionReport) -> None
research_engine.explain_trade(trade_id) -> TradeExplanation
research_engine.query(natural_language_question: str) -> RagResponse
research_engine.weekly_review(week_of: date) -> ReviewReport
research_engine.monthly_review(month_of: date) -> ReviewReport
research_engine.recommendations() -> Tuple[Recommendation, ...]
```

`record_trade` is the only write path; every other function is
read-only.

**Revision (Architecture Hardening — closes Red Team Audit Findings
2.1 and 12.1):** `record_trade` is now called by
`phantom/runtime/runtime.py` for **every** pair whose cycle reached
Strategy Engine, whether it proceeded to a submitted `TradeCommand` or
stopped at the entry gate, a Risk veto, a Compliance rejection, or a
Bridge-layer `ErrorCode` (`docs/specs/00_runtime_orchestrator.md` §5
step 7) — "observer" means this component records the outcome of every
decision the Runtime made, not only successful executions.
`decision_chain_snapshot` now always carries a `stage_reached`/`outcome`
pair using each stopping stage's own existing type (`EntryGateDecision`,
`RiskVeto`, `ComplianceRejection`, or `phantom.bridge.models.ErrorCode`)
— no new rejection taxonomy is introduced.

**Reconciliation path (closes Red Team Audit Finding 2.3):** if the
primary `ExecutionReport` for a submitted command never arrives within
a configured timeout, `record_trade` may be invoked a second time for
the same trade using `phantom.bridge.engine.BridgeEngine`'s existing
`handle_trade_transaction` drift-detection data as the outcome source
instead — reusing the already-built `TradeTransactionReport` mirror
rather than leaving that trade permanently absent from memory.

## 4. Inputs

- `DecisionChainSnapshot`: the Evidence/Strategy/Intelligence/Risk/
  Compliance state at the moment a trade was decided, now assembled and
  passed in by `phantom/runtime/runtime.py` specifically (no longer an
  unnamed "whatever orchestrates the live chain") — this component
  still does not reach back into any live component itself to
  construct it.
- `ExecutionReport` (PhantomBridgeEA, via `phantom.bridge.models`), or
  a `TradeTransactionReport`-derived reconciliation outcome (see §3).
- `PortfolioStatistics` (Risk Engine's `portfolio_stats()`, read-only).

## 5. Outputs

`TradeExplanation` (per trade), `RagResponse` (per query),
`ReviewReport` (weekly/monthly), `Recommendation` (read-only, advisory
only).

## 6. Internal data models

| Model | Shape |
|---|---|
| `TradeMemoryEntry` | trade id, decision-chain snapshot, execution report, outcome (P/L, duration), timestamp |
| `DecisionChainSnapshot` | the Evidence/Strategy/Intelligence/Risk/Compliance states that produced the trade |
| `AttributionResult` | performance broken down by strategy/pair/session, computed from `TradeMemoryEntry` history plus Risk Engine's stored stats |
| `TradeExplanation` | trade id, ordered narrative built mechanically from the stored decision-chain snapshot (why Evidence scored it, why Strategy selected it, why Intelligence allowed it, why Risk sized it, why Compliance approved it) |
| `Recommendation` | text + supporting evidence reference; carries no mechanism to apply itself |

## 7. Decision authority

None over live trading. This component may only ever be read from by
anything outside itself; it must never be imported by
`phantom/strategy/` or `phantom/risk/` (one-directional data flow,
structurally enforced — see §10). It is also never imported by
`phantom/runtime/` for anything other than the `record_trade`
observer call itself — Runtime does not consult this component's
`recommendations()`/`explain_trade()`/`query()` outputs as part of any
live decision.

**Authority restatement (Architecture Hardening):** Research & Learning
Engine holds **no decision authority of any kind** — pure observer/
advisory (see the system-wide authority matrix in
`PHANTOM_ARCHITECTURE_HARDENING.md`).

## 8. Dependencies

Trade history produced by the completed live chain, delivered via
`phantom/runtime/runtime.py`'s observer call, and Risk Engine's
`portfolio_stats()` (Phase 5) for `performance_attribution.py`'s reuse
contract.

## 9. Explicit non-responsibilities

- **Never modifies live trading** — no function in this component's
  public interface accepts a parameter that could feed back into
  Strategy Engine's selector or Risk Engine's sizing; `recommendations()`
  returns text/evidence only.
- Never recomputes Sharpe/Sortino/expectancy/VaR/CVaR/risk-of-ruin
  itself — reads Risk Engine's stored values via `portfolio_stats()`.
- Never re-executes, re-evaluates, or re-scores a trade after the
  fact — its records are historical, not corrective.
- Never uses RAG/generative techniques anywhere outside this
  component — this is the one and only AI/RAG surface in Phantom
  (enforces "no duplicate AI").

## 10. Test plan

- Structural-boundary test: no file under `phantom/research/`
  recomputes Sharpe/Sortino/expectancy (must import
  `phantom/risk`'s stored values only) — this is the test Phase 5's
  own exit criteria promised.
- Structural-boundary test: no file under `phantom/strategy/` or
  `phantom/risk/` imports anything from `phantom/research/` (one-
  directional flow, "advisory only, never modifies live trading").
- Unit tests for `trade_explainer.py` against fixture decision-chain
  snapshots, asserting the explanation names every stage's actual
  contributing values (not a generic template with no real content).
- Integration test producing a full simulated weekly review from
  fixture trade history end to end.
- **Every-outcome recording test** (closes Finding 2.1/12.1): a fixture
  cycle where the pair stops at each of the four possible stages
  (entry gate, Risk veto, Compliance rejection, Bridge `ErrorCode`)
  produces a `record_trade` call for every one, each carrying the
  correct originating stage's own type as the outcome — no stopped
  pair is silently unrecorded.
- **Reconciliation test** (closes Finding 2.3): a fixture where the
  primary `ExecutionReport` never arrives within the configured timeout
  is backfilled correctly from a fixture `TradeTransactionReport`.

## 11. Performance requirements

Not on the live decision-cycle's critical path — `record_trade` may be
asynchronous/batched relative to trade execution; review/report
generation has no real-time latency requirement (target: complete
within an operator-acceptable wait, e.g. under a few seconds for a
week's worth of trades, validated during implementation).

## 12. Failure modes

| Failure | Expected behavior |
|---|---|
| `record_trade` fails to persist | Logged as an error; must not block or delay the live trade it's recording (this component's own failure must never propagate back into the live chain — one-directional dependency, one-directional failure isolation). |
| RAG retrieval finds no relevant memory for a query | Returns an explicit "no matching history" response, never a fabricated answer. |

## 13. Security considerations

Trade memory may contain account-identifying details; access to
`query()`/review outputs should be scoped to authorized operators, not
exposed on any external surface in this phase (no live provider/API
integration is in scope here). RAG retrieval must operate only over
this system's own recorded trade memory — never over external,
untrusted content that could be used to prompt-inject a recommendation.

## 14. Logging requirements

`logging_sink.py` logs every `record_trade` call and every
`recommendations()`/review generation. `metrics.py` tracks memory size
growth, query latency, and recommendation counts by category.
