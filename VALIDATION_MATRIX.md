# Phantom Validation Matrix

**Status: Architecture phase complete. No test below has been written;
every stage's implementation status is NOT STARTED.**

This matrix consolidates the "Testing" and "Acceptance criteria"
sections already defined in each Accepted ADR. It does not invent new
requirements — every row cites the ADR section it is drawn from. A
stage is not complete until every required test in its row passes **and**
every exit-criterion in `IMPLEMENTATION_PLAN.md` §0 is also met.

---

## 1. Data Pipeline (`ADR-013`)

**Required tests** (§16): gap detection, gap repair (single-bar only,
`is_repaired` flag), duplicate removal, replay consistency, historical
consistency, normalization correctness, timestamp/timezone correctness,
multi-timeframe correctness, boundary/type-level test.

**Exit criteria** (§18): every market event normalized; every
downstream stage consumes one canonical model; replay deterministic;
historical loading deterministic; no trading authority.

**Status: NOT STARTED.**

---

## 2. Scanner (`ADR-002`, + Amendment 1)

**Required tests** (§15): identical-input → identical-output, no
score/decision fields exist, no mutable state affects output, each
structural computation occurs exactly once per scan (duplicate-
computation test), one test per failure mode (§9), structural/type-level
test, purity test, replay-determinism test, Amendment 1's structure-
consistency test and UNKNOWN-handling tests.

**Exit criteria** (§18): referentially transparent; testable in
isolation; facts only, never a decision-shaped field; fails closed on
every failure mode; no structural computation repeated per scan; passes
replay-determinism testing; every logged record carries `trace_id`; zero
playbook-specific logic; metrics export-only; no network egress/
credential access; exactly one authoritative source of market structure
(Amendment 1); qualitative structure confidence only (Amendment 1).

**Status: NOT STARTED.**

---

## 3. Strategy Engine (`ADR-003`)

**Required tests**: duplicate-strategy-ID handling, reasoning-metadata-
cannot-become-a-scoring-mechanism boundary test, plus the isolated-
unit/determinism/type-level test pattern established at Scanner.

**Exit criteria**: strategies confirm, never decide/size/execute;
Strategy Registry has no hard-coded playbook list; `CandidateTrade` is
structurally incapable of a score/decision/size field; conflict
handling never picks a winner (relocated to Scoring Engine).

**Status: NOT STARTED.**

---

## 4. Scoring Engine (`ADR-004`)

**Required tests**: never-discards test (one `ScoreResult` per
`CandidateTrade`), post-hoc ranking never feeds back into individual
scores, boundary/type-level test (no compliance/risk/execution field).

**Exit criteria**: composite score computed independently per
candidate; ranking is read-only and never discards; no compliance, risk,
or execution logic anywhere in this stage.

**Status: NOT STARTED.**

---

## 5. Risk Engine (`ADR-005`)

**Required tests** (§18): determinism test; regression test on
configuration version bump; fail-closed tests (missing account state,
uncalculable exposure, uncalculable correlation → zero risk); never-
exceeds-maximum test; minimum-of-constraints test; never-discards test;
boundary/type-level test.

**Exit criteria** (§20): deterministic risk decisions; never discards a
candidate; never awards risk above configured maximum under any input;
capital-preservation-first fail-closed behavior; never overrides
Compliance; immutable upstream inputs; complete traceability; no AI/
learning/self-adjusting risk without versioned configuration.

**Status: NOT STARTED.**

---

## 6. Compliance Engine (`ADR-006`)

**Required tests**: one test per fail-closed condition (missing account
state, unreachable broker, stale news feed, unevaluable drawdown, etc.,
per §15); kill-switch persistence-across-restart test; daily-lockout
auto-reset vs. kill-switch permanence distinction test; boundary/type-
level test.

**Exit criteria**: unconditional BLOCK on any unevaluable check
(all-must-pass); final, non-bypassable authority; kill-switch persists
across restarts and is human-clearable only; no duplicate news/exposure
computation with Risk Engine.

**Status: COMPLETE (Phase 1).** 94 Compliance Engine tests added
(`tests/phantom_pipeline/compliance_engine/`), covering every required
test above. Validation run:
- `python3 -m unittest discover -s tests/phantom_pipeline`: 518/518 pass.
- `python3 -m compileall phantom_pipeline tests`: clean.
- `python3 validate.py`: 13/13 pass.

---

## 7. Execution Validator (`ADR-007`)

**Required tests** (§12): unit tests; determinism/replay-determinism
tests; duplicate-prevention test; stale-trade rejection test; broker-
disconnect test; spread/slippage-drift tests; margin-failure test;
synchronization-failure test; trace-propagation test; boundary/type-
level test.

**Exit criteria** (§14): never changes any upstream decision; only
validates, never decides; binary verdict only; every rejection
deterministic and logged with reason/timestamp/`trace_id`/validation
stage; no hidden execution path/emergency override, enforced at the
permission level; idempotency state bounded and TTL-pruned.

**Status: COMPLETE (Phase 1).** 113 Execution Validator tests added
(`tests/phantom_pipeline/execution_validator/`), covering every required
test above. Validation run:
- `python3 -m unittest discover -s tests/phantom_pipeline`: 631/631 pass.
- `python3 -m compileall phantom_pipeline tests`: clean.
- `python3 validate.py`: 13/13 pass.

---

## 8. MT5 Bridge (`ADR-008`, + Amendment 1)

**Required tests** (§13, extended by Amendment 1): disconnect/reconnect
tests; duplicate submission/fill tests; heartbeat tests; synchronization
tests; broker rejection tests; timeout tests; replay tests; boundary/
type-level test; trace-propagation test; **Amendment 1:** position
adjustment/close translation tests, duplicate close/adjustment
prevention tests, synchronization-after-modification test.

**Exit criteria** (§15): no trade reaches MT5 without `ExecutionDecision`
APPROVE; no duplicate execution at either idempotency layer; no hidden
execution path; no trading logic; deterministic translation; full
traceability; **Amendment 1:** `PositionAdjustmentRequest`/
`PositionCloseRequest` accepted only from Position Manager, transported
without being decided upon.

**Status: NOT STARTED.**

---

## 9. Position Manager (`ADR-009`)

**Required tests** (§14): reconnect recovery test; duplicate fill
handling test; partial close test; trailing stop test; break-even test;
synchronization recovery test; time-exit test; emergency-close test;
replay compatibility test; boundary/type-level test.

**Exit criteria** (§17): position lifecycle fully defined; synchronization
recovery defined; no upstream authority duplicated; no execution
authority duplicated (all broker communication routes through MT5
Bridge); no risk authority duplicated.

**Status: NOT STARTED.**

---

## 10. Analytics & Decision Provenance (`ADR-010`)

**Required tests** (§12): replay tests; decision reconstruction test;
trace integrity test; schema validation test; data completeness test;
missing-event detection test.

**Exit criteria** (§14): every trade fully reconstructable; every
decision traceable; replay deterministic (contingent on completeness/
immutability); research supported one-way, read-only; no live decision
authority.

**Status: NOT STARTED.**

---

## 11. Watchdog & Recovery (`ADR-011`)

**Required tests** (§14): crash recovery test; heartbeat recovery test;
dependency failure test; network partition test; database outage test;
MT5 disconnect test (observing side); repeated restart protection test;
alert generation test; false-positive suppression test; boundary/
type-level test.

**Exit criteria** (§17): every component has health monitoring; every
recovery action is deterministic (as policy); no trading authority
exists; recovery sequencing documented (bounded attempts, backoff,
freeze-and-escalate); `SystemHealth` fully defined.

**Status: NOT STARTED.** *(Known limitation carried from acceptance:
heartbeat coverage is strongest for MT5 Bridge; other components rely on
operational liveness proxies — not a blocker, tracked for future
per-stage heartbeat amendments.)*

---

## 12. Dashboard & Observability (`ADR-012`)

**Required tests** (§10): view consistency test; metric consistency
test; trace consistency test; read-only verification test; permission
verification test.

**Exit criteria** (§12): every major component observable; every health
state visible; every alert visible (display-only); every trade
traceable; no operational authority.

**Status: NOT STARTED.**

---

## 13. Portfolio Manager (`ADR-017`)

**Required tests** (§15): correlation correctness test; allocation
reproducibility test; portfolio determinism test; budget correctness
test; exposure correctness test; diversification correctness test;
multi-account correctness test; boundary/type-level test; **no-feedback-
loop test** (asserts no code path lets `CapitalBudget`/
`PortfolioRecommendation` reach Risk Engine's or Compliance Engine's
live decision path).

**Exit criteria** (§17): portfolio allocation deterministic; correlation
reproducible; exposure reproducible; budget calculations reproducible;
no live trading authority.

**Status: NOT STARTED.**

---

## 14. Replay & Certification Engine (`ADR-018`)

**Required tests** (§14): replay determinism test; historical
consistency test; regression reproducibility test; certification
reproducibility test; evidence completeness test; boundary/type-level
test.

**Exit criteria** (§16): every certification reproducible; every replay
deterministic; every promotion human-approved; no production authority.

**Status: NOT STARTED.** *(Depends on Data Pipeline's shadow-trading
`MarketSnapshot` grant, `ADR-013` Amendment 1 — already Accepted and
satisfied.)*

---

## 15. AI News Intelligence (`ADR-016`)

**Required tests** (§9, referenced): type-level test (no BUY/SELL/
APPROVE/BLOCK/score/lot-size/SL-TP/execution-instruction field, and no
field that could function as one under a different name); data-plane
isolation test (never shares Compliance Engine's live MT5 Calendar
connection).

**Exit criteria**: advisory-only, human-and-Analytics-facing; zero
authority over any trade/score/size/execution decision; own dedicated
feed, never the compliance-critical live feed.

**Status: NOT STARTED.** *(Its own dedicated data feed requires `ADR-015`
§12's four-step approval before implementation.)*

---

## 16. Self-Evolving Research Agent (`ADR-019`)

**Required tests** (§8): type-level test (nine allowed output types,
none capable of a forbidden field); isolation test (zero live pipeline
access); promotion-chain test (every hypothesis terminates in a
`HumanReviewRequest`, never a direct code change).

**Exit criteria** (§10): fully isolated from the live pipeline; every
output advisory only; self-evolution scoped strictly to its own research
methodology, never touching governance, ADRs, or permissions (`ADR-014`
§13); promotion only through Replay & Certification (`ADR-018`) + Human
Review + normal engineering process.

**Status: NOT STARTED.** *(Its own dedicated feed/LLM dependency, if
any, requires `ADR-015` §12's four-step approval before implementation.)*

---

## 17. Cross-cutting / non-stage requirements

- **Multi-Agent Governance (`ADR-014`) §12 testing**: permission
  verification, boundary verification, authority verification, audit
  completeness, trace completeness, human-approval-enforcement test (a
  git-history audit that every ADR acceptance traces to a distinct,
  human-initiated commit). **Status: NOT STARTED** — this is a
  process/audit check, not a code deliverable, and can be exercised
  against this session's own git history at any time.
- **External Data Sources & API Governance (`ADR-015`) §11 testing**:
  mock providers for every live-pipeline service; replay testing;
  failure simulation per §6/§8; timeout simulation; API contract tests;
  regression tests on adapter changes. **Status: NOT STARTED.**
