# Phantom vNext — Final Pre-Implementation Red Team Audit

No code was written or modified to produce this document. No new
package or engine is proposed. The architecture and its 8 component
specs, plus the already-built Phase 1 code
(`phantom/bridge/`, `mt5/PhantomBridgeEA.mq5`), are treated as frozen
inputs under adversarial review.

**Panel:** Quantitative Trading Architect, Institutional FX Trader,
MQL5 Architect, Prop Firm Risk Manager, Software Architect, Security
Engineer, Performance Engineer, QA/Test Engineer. Findings below are
organized by the 20 requested categories; each names the lens(es) that
surfaced it. Every finding is grounded in a specific document/file cited
inline — nothing below is invented for volume. Where a category
produced no defensible new finding beyond what's already documented
elsewhere in this thread, that is stated plainly rather than padded.

---

## 1. Duplicate responsibilities

**Finding 1.1 — No explicit rule against playbooks re-deriving regime
state.** *(Software Architect, Quant Architect)* — Severity: **Medium**

`docs/specs/02_strategy_engine.md` has every playbook consume
`PairEvidence` (which already carries `Regime`), but nothing in the
`Playbook` interface spec *forbids* a playbook implementation from
independently re-deriving "is this trending/ranging" from raw price
data instead of trusting `evidence.regime` — the exact duplicate-logic
failure mode the lock's "no duplicate calculations" rule targets. This
is a documentation gap, not a design flaw: the intent is clearly that
playbooks trust Evidence Engine, but intent isn't yet a stated,
checkable rule.
**Smallest fix:** add one sentence to `Playbook`'s interface spec:
"`confirm()` must use `evidence.regime`/`evidence.findings` as its only
market-condition inputs; it must never recompute regime or structure
independently." Add a structural-boundary test asserting no file under
`phantom/strategy/playbooks/` imports `phantom/evidence/regime.py` or
`market_structure.py` directly (only `phantom/evidence`'s public
`PairEvidence` type via the function that already delivers it).

No other duplicate-responsibility finding survived scrutiny — the
score/quality boundary (Evidence's regime vs. Intelligence's session/
liquidity/spread quality) and the Research-vs-Risk statistics boundary
were already named and resolved in
`PHANTOM_FINAL_ARCHITECTURE.md` §13 and this audit found nothing to add
to either.

## 2. Missing responsibilities

**Finding 2.1 — No component owns the end-to-end decision-loop
orchestration.** *(Software Architect, Quant Architect)* — Severity:
**Critical**

Every one of the 8 approved components exposes a clean function
(`evidence_engine.get_pair_evidence`, `strategy_engine.evaluate`,
`risk_engine.evaluate`, `compliance_engine.evaluate`, `submit_command`,
`research_engine.record_trade`), but **no approved component is
specified as the thing that calls them in sequence, each cycle, for
every enabled pair.** `docs/specs/06_research_learning_engine.md` §4
even says `record_trade`'s snapshot is "assembled by whatever
orchestrates the live chain" without ever naming what that is. This is
a real, load-bearing gap: without an owner, the cycle-driving loop
either doesn't get built, or gets built as an unreviewed side effect of
whichever component's implementer notices the hole first — precisely
the kind of undocumented authority the lock's own rules exist to
prevent.
**Why it matters:** this loop is where "evaluate all pairs, gate on
Intelligence, gate on Reliability's halt, size via Risk, gate via
Compliance, submit, record" actually happens. Left unowned, it is the
single most likely place a future implementer quietly adds real
decision logic outside any of the 8 audited components.
**Smallest fix:** do **not** add a ninth engine. Assign this
responsibility to System Reliability Engine's existing
`reliability_engine.py` (it already watches every component and holds
the kill switch, so driving the cycle and checking its own
`is_halted()` first is a natural, minimal extension of scope already
granted to it) — or, if that is rejected as scope creep for Reliability,
a thin top-level `phantom/runtime.py` module containing *only*
sequencing calls into the 8 components' already-public functions, with
an explicit rule that it may contain zero decision logic of its own
(enforced by the same "no decision-shaped function names" structural
test already used elsewhere). Either resolution is a documentation
addition to an existing component's spec, not a new package.

**Finding 2.2 — No pending/in-flight exposure reservation between Risk
Engine's approval and confirmed execution.** *(Quant Architect, Prop
Firm Risk Manager)* — Severity: **High**

`docs/specs/03_portfolio_statistical_risk_engine.md` §4 sources
`PortfolioSnapshot` from PhantomBridgeEA's *confirmed* open positions.
If Strategy Engine's `evaluate_all` produces two ideas on correlated
pairs (e.g. EURUSD long and GBPUSD long) in the same cycle, and both
are evaluated by Risk Engine before either has an `ExecutionReport`,
each evaluation sees the *same* pre-trade portfolio snapshot — neither
sees the other's not-yet-confirmed exposure. Both can be independently
approved within correlation/heat limits that would be breached the
moment both actually fill.
**Why it matters:** this is exactly the "no duplicate portfolio
calculations" rule's blind spot — not a duplicate calculation, but a
*missing* one (no calculation accounts for proposed-but-unconfirmed
exposure at all).
**Smallest fix:** extend `phantom/risk/portfolio_heat.py` and
`correlation.py` (already-scoped files) to accept an additional,
in-memory "reserved exposure" ledger of ideas approved-but-not-yet-
confirmed-executed in the current cycle, cleared on `ExecutionReport`
arrival or command failure. This is a scope addition to two existing
files, not a new component.

**Finding 2.3 — No missing-execution-report reconciliation path into
trade memory.** *(QA/Test Engineer, Reliability)* — Severity: **Medium**

`docs/mt5_validation/06_troubleshooting_guide.md` already documents
that a `ReportExecutionResult` HTTP call can fail after a real trade
executed successfully on MT5 (a known Phase 1 limitation). Compounding
this: `docs/specs/06_research_learning_engine.md` §3's `record_trade`
takes a single `ExecutionReport` as its only execution-outcome input —
there is no specified fallback using the independent
`TradeTransactionReport` mirror (which *would* have seen the trade) to
backfill Research & Learning Engine's memory when the primary report is
lost.
**Smallest fix:** extend `record_trade`'s spec to note it may be
invoked from either the primary `ExecutionReport` path or a
reconciliation pass using `phantom.bridge.engine.BridgeEngine`'s
existing `handle_trade_transaction`/drift-detection data when no
matching `ExecutionReport` arrives within a configured timeout — reuse
of an existing mechanism, not a new one.

## 3. Circular dependencies

None found. The dependency graph in
`PHANTOM_IMPLEMENTATION_ROADMAP.md` §4 is acyclic as specified: Evidence
and Market Intelligence are leaves (beyond `shared/`), Strategy depends
on both, Risk depends on Strategy, Compliance depends on Risk, Research
depends on the completed chain read-only, Validation depends on
`models.py` types only. The one thing that *would* introduce a cycle —
Risk Engine reading Compliance Engine's headroom as a scaling input,
raised as an option in Finding 10.2 below — is correctly flagged there
as optional and requires care specifically because it would reverse an
edge in this graph; it is not adopted by default in this audit's
recommendations.

## 4. Hidden coupling

**Finding 4.1 — Compliance Engine's account-state freshness is
unbounded.** *(Prop Firm Risk Manager, Security Engineer)* — Severity:
**High**

`docs/specs/05_prop_firm_compliance_engine.md` §4 takes `AccountState`
"sourced from PhantomBridgeEA's existing telemetry" but never states a
maximum acceptable age for that state before `evaluate()` must refuse
to approve rather than act on stale drawdown/equity data. This is a
hidden temporal coupling to the bridge's own heartbeat cadence
(`HeartbeatIntervalSeconds`, default 5s) that nothing in the Compliance
spec makes explicit or enforces.
**Smallest fix:** add an explicit staleness threshold to
`docs/specs/05...`'s §4/§12 (e.g., reject with a named
`ComplianceRejection` reason if `AccountState.received_at` is older
than a configured bound) — the same fail-closed pattern
`FailClosedTimeoutSeconds` already establishes in Phase 1, applied
consistently one layer up. Documentation-only change.

**Finding 4.2 — Evidence Engine parameter changes silently reshape
every playbook with no procedural gate.** *(Software Architect)* —
Severity: **Low**

Already structurally acknowledged (`PHANTOM_IMPLEMENTATION_ROADMAP.md`
§6: Validation is a standing gate for exactly this kind of change), but
nothing *enforces* that an Evidence Engine config change actually goes
through Validation before shipping — it is a process expectation, not a
checked one.
**Smallest fix:** a lightweight CHANGELOG/PR-checklist requirement
(process control), not a code or architecture change.

## 5. Race conditions

**Finding 5.1 — `phantom/bridge/command_queue.py` has no locking under
a multi-threaded HTTP server.** *(Software Architect, Performance
Engineer, QA/Test Engineer)* — Severity: **Critical** (already-built
code)

Verified directly: `phantom/bridge/server.py` serves every request via
`http.server.ThreadingHTTPServer` (line 313), which spawns one thread
per connection. `CommandQueue` (`phantom/bridge/command_queue.py`) has
**zero synchronization** — `_commands`, `_pending_order`,
`_delivered_ids`, `_executed_ids`, and `_results` are plain
dict/list/set attributes mutated directly by `enqueue`, `poll`, and
`record_result`, with no `threading.Lock` anywhere in the file (or in
`engine.py`/`connection_health.py` — confirmed by grep, zero matches).
Concretely: a `GET /bridge/commands/poll` call (mutates
`_pending_order`/`_delivered_ids`) and a `POST
/bridge/execution/report` call (mutates `_executed_ids`/`_results`)
arriving on two different EA-driven requests at nearly the same moment
run on two different threads against the same unlocked dicts/sets.
CPython's GIL makes individual bytecode ops atomic but not the
multi-statement sequences here — `all_results()`'s
`tuple(self._results.values())` can race a concurrent `record_result()`
insert into the same dict from another thread, which is a documented
CPython hazard (`RuntimeError: dictionary changed size during
iteration` / `set changed size during iteration`) even under the GIL.
**Why it matters:** this is already-built Phase 1 code that will be
exercised the moment real MT5 traffic starts — not a future
component's hypothetical gap.
**Smallest fix:** add one `threading.Lock` (or `RLock`) to
`CommandQueue`, held around each public method's body. This is the
smallest possible fix for a real, already-shipped defect — flagged
here per this task's audit mandate; no code was changed to produce this
report, and any actual fix requires a separate, explicitly authorized
change to already-frozen Phase 1 code.

**Finding 5.2 — Same class of risk applies to every future component's
concurrency model, unaddressed by any of the 8 specs.** *(Performance
Engineer)* — Severity: **Medium**

None of `docs/specs/01`–`08` state whether their orchestrator
(`evidence_engine.py`, `risk_engine.py`, etc.) is expected to be called
from a single-threaded loop or must be internally thread-safe.
**Smallest fix:** add one sentence to each spec's §11 (Performance
requirements): "single-threaded caller assumed; this component is not
required to be internally thread-safe unless a future spec revision
says otherwise" — removes the ambiguity cheaply, consistent with
Finding 2.1's recommendation that one orchestrator drives the loop
serially.

## 6. Failure modes

Per-component failure-mode tables in `docs/specs/01`–`08` §12 are
individually sound (each names a real failure and a fail-closed
response). The one gap the panel found beyond what's already documented
is **Finding 2.3** above (missing-report reconciliation); nothing else
survived scrutiny as a genuinely new failure mode not already covered.

## 7. Statistical weaknesses

**Finding 7.1 — No minimum-sample-size gate before a rolling statistic
is trusted for sizing.** *(Quant Architect)* — Severity: **High**

`docs/specs/03_portfolio_statistical_risk_engine.md` specifies unit
tests for Sharpe/Sortino/expectancy "against fixed-seed inputs," but no
minimum trade-count threshold below which these statistics are
considered too noisy to drive a `SizingRecommendation`. A system with
5 historical trades computing a "Sharpe ratio" is manufacturing false
precision.
**Smallest fix:** add a minimum-*n* gate to `risk_engine.py`'s spec:
below the configured threshold, force the "Minimal allocation" tier
regardless of what the raw statistic says, rather than trusting an
undersampled estimate. Parameter addition to an existing file.

**Finding 7.2 — Correlation basis (returns vs. price levels) is
unspecified.** *(Quant Architect)* — Severity: **Medium**

`correlation.py`'s responsibility is stated as "correlation matrix
across open + candidate positions" without saying whether it operates
on return series or raw price levels — a real, easy-to-get-wrong
distinction (price-level correlation between two trending pairs is
close to meaningless; return correlation is the standard, meaningful
measure).
**Smallest fix:** one sentence in the spec: "computed on return series,
not raw price levels."

**Finding 7.3 — Rolling statistics are not regime-segmented.** *(Quant
Architect)* — Severity: **Medium**

A strategy's true trending-regime Sharpe can be materially diluted by
ranging-regime trades inside the same rolling window, even though
Evidence Engine already classifies regime per evaluation. Not adopted
as a requirement here (would expand `sharpe_sortino.py`'s scope
non-trivially) — flagged as a documented, deferred enhancement rather
than forced into this freeze, per the instruction to prefer minimal
changes.

## 8. Strategy weaknesses

**Finding 8.1 — No documented playbook priority/tie-break rule.**
*(Institutional FX Trader, Quant Architect)* — Severity: **High**

`docs/specs/02_strategy_engine.md` states "at most one playbook fires
per pair per cycle" but never says which wins if more than one
playbook's conditions are simultaneously satisfiable. Two concrete,
realistic cases: (a) a range near a session transition can satisfy both
Session Breakout's post-breakout-retest condition and Range Reversal's
boundary-rejection condition; (b) in a strong uptrend, a Liquidity
Sweep's counter-trend reversal thesis and Trend Continuation's
pullback-long thesis can both fire on the same bar for the same pair in
opposite directions. Relying on `registry.py`'s auto-discovery
iteration order (directory-scan order is not a documented, stable
contract) to silently decide the winner is not an acceptable
tie-breaking mechanism.
**Smallest fix:** add an explicit, documented priority order (or an
explicit "structurally-conflicting playbooks must be mutually
exclusive by construction" rule) to `selector.py`'s spec. Documentation
addition, no new component.

## 9. Market Intelligence weaknesses

**Finding 9.1 — Entry-gate scope for existing-position management is
undefined.** *(Institutional FX Trader, Prop Firm Risk Manager)** —
Severity: **Medium**

`get_entry_gate` is explicitly scoped to *new* entries. Nothing states
whether MODIFY_SL/MODIFY_TP/CLOSE on an already-open position should
also be restricted (or deliberately exempted) during a high-impact
blackout — a real decision with real consequences (e.g., widened
spreads during NFP make a stop modification itself risky), left
implicit rather than made and recorded.
**Smallest fix:** one explicit sentence in
`docs/specs/04_market_intelligence_engine.md`: the gate governs new
entries only; management commands are deliberately exempted, consistent
with PhantomBridgeEA's own close-only-mode precedent (never blocks
closing). A recorded decision, not a code change.

**Finding 9.2 — Broker-server-time DST handling is unaddressed.**
*(MQL5 Architect, Institutional FX Trader)* — Severity: **High**

Session-quality weighting (London/New York preference) and blackout
windows are time-based, but no spec states which clock they run on. MT5
broker servers commonly run on a fixed offset (e.g. UTC+2/+3, or EET)
that follows the *broker's* DST convention, not the trader's local time
or naive UTC — a well-known, concrete source of real bugs (session
windows silently shifting by an hour twice a year).
**Smallest fix:** add one explicit requirement to
`economic_calendar.py`/`session_quality.py`'s spec: all time-based
logic operates on broker server time (obtainable from PhantomBridgeEA's
own telemetry), not system local time, with the broker's own DST
convention, never the trader's.

**Finding 9.3 — Peg/policy-block clearance has no audit-logging
requirement, unlike the analogous Compliance lockout.** *(Security
Engineer)* — Severity: **Low**

`docs/specs/04...`'s peg/policy handling says a block is "held until
explicitly cleared... by an operator action" but its §14 logging
requirements don't explicitly require logging who/when cleared it, the
way Compliance Engine's emergency lockout does.
**Smallest fix:** one sentence added to §14 for parity. See also
Finding 17.1 (operator authentication, cross-cutting).

## 10. Risk weaknesses

**Finding 10.1 — See Finding 2.2** (pending-exposure reservation) —
this is fundamentally a risk-calculation completeness gap, cross-filed
under Missing Responsibilities because the fix is an addition, not a
correction, to an existing calculation.

**Finding 10.2 — Risk Engine's statistical view and Compliance
Engine's hard-limit view can diverge sharply with no cross-awareness.**
*(Prop Firm Risk Manager, Quant Architect)* — Severity: **Low**

A low risk-of-ruin/drawdown-probability estimate can lead Risk Engine
to recommend a large size that Compliance Engine then chops down hard
at the edge of a daily-loss limit — architecturally correct (Compliance
always wins, never enlarges) but computationally wasteful (a full
Monte Carlo run producing a recommendation immediately overridden).
**Not recommended as a required fix**: making Risk Engine aware of
Compliance Engine's headroom would reverse a dependency-graph edge
(§3) and needs to stay read-only and optional if ever adopted.
Documented here as an accepted, low-severity architectural tension
rather than forced into scope now.

## 11. FTMO compliance gaps

**Finding 11.1 — Prop-firm-specific news-trading restrictions are not
modeled as a Compliance Engine rule.** *(Prop Firm Risk Manager)* —
Severity: **High**

`docs/specs/04_market_intelligence_engine.md`'s news blackout is a
general, risk-advisory-flavored gate. Real FTMO-style programs often
have a *specific, contractual* news-trading restriction (e.g., no new
or held trades within a fixed window of designated high-impact
releases) whose violation is an account-termination matter — a
*compliance* fact, not merely a risk-quality signal. Nothing in
`docs/specs/05_prop_firm_compliance_engine.md`'s rule list (daily
drawdown, total drawdown, trading-day rules, position limits, daily
trade limits, emergency lockout) captures this as its own hard rule.
**Why it matters:** if the two are conflated, a future tuning of Market
Intelligence's *general* blackout width for risk-quality reasons could
silently loosen what is actually a *contractual* restriction, with
account-termination consequences.
**Smallest fix:** add a `news_trading_restriction.py`-equivalent rule
to Compliance Engine's existing file list, which *consults* Market
Intelligence's already-built event classification as its data source
(reuse, no duplicate news processing) but enforces its own,
independently configured window as a hard compliance rule with its own
rejection reason and audit trail.

**Finding 11.2 — Weekend/overnight holding restriction not addressed.**
*(Prop Firm Risk Manager)* — Severity: **Medium**

Some prop-firm account types prohibit holding positions over the
weekend. Not present in Compliance Engine's rule list.
**Smallest fix:** add `weekend_holding_rule.py` to the existing
Compliance Engine file list (a new file inside an already-approved
package, not a new component) — evaluates existing open positions
against the account's configured rule set ahead of market close.

**Finding 11.3 — No profit-target / consistency-rule tracking.** *(Prop
Firm Risk Manager)* — Severity: **Medium**

Challenge/verification-phase profit targets and (for account types that
have one) the "no single day's profit exceeds X% of total profit"
consistency rule are absent from the Compliance Engine spec.
**Smallest fix:** extend `config.py`'s `ComplianceRuleSet` to carry
these as optional, per-account-type parameters, and add
`profit_target_tracking.py`/fold consistency-rule checking into
`daily_drawdown.py`'s existing daily-P&L bookkeeping (three similar
lines before a new file, per the Minimal Change Engineer rule — this
one is small enough to fold in rather than add a file).

**Finding 11.4 — No explicit "stop-loss required on every trade"
enforcement.** *(Prop Firm Risk Manager)* — Severity: **Medium**

Several FTMO-style rule sets mandate a stop-loss on every position.
Nothing in Compliance Engine's spec explicitly rejects a
`SizingRecommendation`/resulting `TradeCommand` with no stop-loss set,
even though Strategy Engine's playbooks always compute one in practice.
**Smallest fix:** add an explicit check to `compliance_engine.py`'s
spec: reject if the rule set requires a stop-loss and the command has
none — a one-line rule addition to an existing file's responsibility,
defense-in-depth against a future playbook that omits one.

## 12. Execution risks

**Finding 12.1 — No spec addresses `submit_command`'s own possible
rejection.** *(Software Architect, MQL5 Architect)* — Severity: **High**

`docs/specs/05_prop_firm_compliance_engine.md` produces a
`TradeCommand` and states it's submitted through the existing
`BridgeEngine.submit_command`. But `submit_command`
(`phantom/bridge/engine.py`, via `CommandQueue.enqueue`) can itself
return `DUPLICATE_CORRELATION_ID`, `BRIDGE_NOT_READY`, or
`EMERGENCY_STOP_ACTIVE` — and nothing in any of the 8 specs, nor the
still-unowned orchestration loop (Finding 2.1), states what happens to
a `TradeIdea` whose Compliance-approved `TradeCommand` is then rejected
at the bridge layer. Silently dropping it is a real, unaddressed
possibility as specified today.
**Smallest fix:** extend whichever component ends up owning the
orchestration loop (Finding 2.1's fix) to feed `submit_command`'s
rejection back through the same `ComplianceRejection`-shaped reporting
path already defined — reuse of an existing type, not a new one.

## 13. MT5-specific issues

**Finding 13.1 — Netting vs. hedging account mode is unaddressed in the
new components.** *(MQL5 Architect, Quant Architect)* — Severity:
**Medium-High**

`docs/research/mt5-standard-library-research.md` §4 already researched
that hedging accounts can hold multiple tickets per symbol+direction,
unlike netting's single aggregate position. None of Risk Engine's
`exposure.py`/`correlation.py`/`portfolio_heat.py` or Compliance
Engine's `position_limits.py` specs state how they aggregate exposure
under hedging mode (per-ticket vs. per-symbol).
**Smallest fix:** one sentence in each affected file's spec: exposure/
position-count aggregation must handle both accounting modes
explicitly, using PhantomBridgeEA's reported `ACCOUNT_MARGIN_MODE`
(already available per the MT5 research) to select behavior.

**Finding 13.2 — `SYMBOL_TRADE_FREEZE_LEVEL` and explicit filling-mode
negotiation remain open from the prior research, not yet actioned.**
*(MQL5 Architect)* — Severity: **Medium** (already known, restated for
completeness, not a new finding)

Already documented in
`docs/research/mt5-standard-library-research.md` §7 as a candidate for
a future, separately-approved hardening pass to `mt5/PhantomBridgeEA.mq5`.
No change to that status from this audit.

## 14. Performance bottlenecks

**Finding 14.1 — Monte Carlo simulation cost is not bounded relative to
decision-cycle budget.** *(Performance Engineer)* — Severity: **Medium**

`docs/specs/03...`'s §11 targets the same decision-cycle budget as
Strategy Engine, but Monte Carlo simulation (potentially thousands of
iterations) runs synchronously per `TradeIdea`, per pair, per cycle,
with no caching/incremental-recompute strategy specified for when only
one new idea is added to an otherwise-unchanged portfolio.
**Smallest fix:** add a scope note to `monte_carlo.py`'s
responsibility: portfolio-level simulation state may be cached and
incrementally updated rather than recomputed from scratch per idea,
recomputed fully only when the portfolio itself changes materially.

## 15. Memory issues

**Finding 15.1 — No retention/pruning policy for trade memory or
candle history.** *(Performance Engineer, Reliability)* — Severity:
**Medium**

`trade_memory.py` (Research & Learning Engine) and
`market_data_source.py` (Evidence Engine) both describe unbounded
accumulation with no stated retention window or archival policy.
**Smallest fix:** add a configurable retention/archive-then-prune
requirement to both files' specs — a parameter, not a new component.

## 16. Scalability problems

**Finding 16.1 — No stated parallelization contract for per-pair
evaluation.** *(Performance Engineer)* — Severity: **Low**

`evaluate_all`/`get_all_pair_evidence`/`get_pair_intelligence` all
iterate the enabled-pair list with no explicit statement that per-pair
evaluation has no shared mutable state and is therefore safely
parallelizable if the pair list grows.
**Smallest fix:** one sentence per spec's §11 stating this as an
explicit non-functional property.

## 17. Security concerns

**Finding 17.1 — No component owns operator authentication for
clearing a halt.** *(Security Engineer)* — Severity: **High**

Three separate mechanisms across three components reference "an
operator clears it": Compliance Engine's emergency lockout, Market
Intelligence's peg/policy block, and System Reliability Engine's kill
switch. None of the 8 specs define who "operator" is, how they
authenticate, or how that authorization is checked — each component
would otherwise invent its own ad hoc notion, which is itself a form of
duplicate (and inconsistent) authority.
**Smallest fix:** consolidate this into System Reliability Engine's
existing scope (it already owns cross-cutting monitoring/logging) as
one explicit operator-authorization concern the other two components'
clear-paths call into, rather than three independent mechanisms. A
spec addition to an existing component, not a new one.

## 18. Logging gaps

**Finding 18.1 — No stated redaction/retention policy for
account-identifying data in logs.** *(Security Engineer, Reliability)*
— Severity: **Medium**

`AccountState`/`ComplianceRejection`/etc. carry balance/equity/account-
login data; no spec states a redaction or retention policy for this in
`logging_sink.py` output across any component.
**Smallest fix:** one policy statement added to System Reliability
Engine's `logging.py` spec (the shared underlying sink every
component's own `logging_sink.py` writes through) — enforced once,
centrally, rather than per component.

## 19. Recovery gaps

**Finding 19.1 — "No restart logic yet" is the single most consequential
deferred item, by design.** *(Reliability, Institutional FX Trader)* —
Severity: **High** (declared scope, not a surprise defect)

`docs/specs/07_system_reliability_engine.md` explicitly defers
`auto_recovery.py`'s implementation to Phase 8. This is a documented,
deliberate limitation, not an oversight — but it is worth stating
plainly in this audit that until Phase 8 lands, a PhantomBridgeEA
disconnect or a live component crash has **no automated recovery path**
at all, only detection. This materially affects the institutional- and
production-readiness scores below and should weigh in any go-live
decision that predates Phase 8.

## 20. Testing gaps

**Finding 20.1 — No specified multi-component simultaneous-failure
integration test.** *(QA/Test Engineer)* — Severity: **Medium**

`PHANTOM_IMPLEMENTATION_ROADMAP.md` Phase 6's exit criteria proves the
full chain end-to-end against fixture data for the happy path and
single-component failure modes (each spec's own §12 table), but no
phase specifies a test where two components degrade simultaneously
(e.g., Market Intelligence *and* Risk Engine both unreachable at once)
to confirm fail-closed behavior composes correctly across the whole
chain rather than just per-component.
**Smallest fix:** extend Phase 6's existing end-to-end test plan (not a
new phase) to include at least one dual-degradation fixture scenario.

---

## Overall scores

| Score | Value | Rationale |
|---|---|---|
| **1. Overall architecture score** | **79/100** | Sound separation of authority, explicit non-duplication contracts, and extensive test-plan discipline, offset by one Critical (unowned orchestration loop), one Critical already-built defect (command queue race), and several High findings that must close before Phase 2. |
| **2. Maintainability score** | **88/100** | Single-responsibility files, auto-discovery registries, structural-boundary tests throughout — the design pattern that already served Phase 1 well is applied consistently across all 8 new specs. |
| **3. Reliability score** | **63/100** | Held down specifically by Finding 5.1 (real race condition in already-built code), Finding 2.1 (no orchestration owner), and Finding 19.1 (no recovery automation yet, by design). |
| **4. Institutional readiness score** | **68/100** | Held down by Finding 9.2 (DST/session-time handling), Finding 13.1 (netting/hedging gap), Finding 2.2 (pending-exposure reservation), and Finding 17.1 (no operator-authentication model). |
| **5. FTMO readiness score** | **60/100** | The weakest score, driven by Findings 11.1–11.4: prop-firm-specific news restriction, weekend-holding rule, profit-target/consistency-rule tracking, and stop-loss-required enforcement are all currently absent from Compliance Engine's rule list. |
| **6. Production readiness score** | **52/100** | Phase 1's own real-MetaEditor-compile and real-MT5-demo-validation gate is still unmet (confirmed again before this audit) — everything above it is unproven against a real broker/terminal, and that alone caps this score regardless of how sound the design above it is. |

## Top five remaining risks

1. **No component owns the end-to-end decision-loop orchestration**
   (Finding 2.1) — the single largest structural gap; left unresolved,
   it is where undocumented decision logic is most likely to leak in
   during implementation.
2. **`phantom/bridge/command_queue.py` has no thread-safety under
   `ThreadingHTTPServer`** (Finding 5.1) — a real, already-shipped
   defect in Phase 1's own built code, not a future risk.
3. **No pending-exposure reservation across ideas approved in the same
   cycle** (Finding 2.2) — correlated pairs can each be individually
   approved into a joint limit breach.
4. **FTMO-specific rules (news restriction, weekend holding,
   profit-target/consistency, stop-loss-required) are not modeled as
   Compliance Engine rules** (Findings 11.1–11.4) — the exact category
   of gap whose failure mode is account termination, not a statistical
   loss.
5. **Phase 1's real-world validation gate remains unmet** (Finding
   under Production readiness) — no amount of specification quality
   above it substitutes for an actual MetaEditor compile and MT5 demo
   run, which still haven't happened.

## Final recommendation

**Approve with minor changes.**

None of the findings above require abandoning the 9-component
structure, adding a new engine, or redrawing an authority boundary —
every fix is a scope addition to an already-approved component's spec,
a parameter, a documentation clarification, or (in exactly one case,
Finding 5.1) a locking fix to already-built code. That is what "minor"
means here: minor in *architectural* scope, not minor in *urgency* —
Findings 2.1, 5.1, 2.2, 7.1, 8.1, 4.1, 9.2, 11.1–11.4, 12.1, and 17.1
are all rated High or Critical and should be resolved (as spec
revisions, not implementation) before Phase 2 begins, alongside the
still-outstanding Phase 1 real-MT5 gate.
