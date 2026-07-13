# ADR-025 — Market Intelligence Engine

Status: **Accepted**

Owner: Software Architect (per the precedent set by `ADR-024`'s
Evidence Engine — a cross-cutting evaluation component, not a
playbook-orchestration one)

Accepted By: User direction, this session (explicit, full
specification: 12 responsibility categories — pair-specific news
intelligence, news classification, blackout rules, peg/policy events,
session intelligence, liquidity quality, market safety, pair safety,
trade readiness, explainability, architecture rules, performance — plus
a 9-category testing mandate) — the same in-session approving authority
already used to accept `ADR-020` through `ADR-024`.

Reviewed by: (post-hoc, this session) — checked against `ADR-006`
(Compliance Engine) and `ADR-016` (AI News Intelligence) before
acceptance; see §0.

Date: 2026-07-10

Depends on: `ADR-024-evidence-engine.md` (Accepted — this engine
consumes `EvidenceReport` as a read-only input and reuses
`titan_protocol.evidence_engine.session.analyze_session()` directly rather
than reimplementing session-boundary classification; it does not
depend on, import, or modify anything else in that package).

---

# 0. Relationship to existing architecture

Two real overlaps were checked before this ADR was accepted, following
the same duty of care `ADR-024` applied to the Scanner/Scoring Engine
overlap:

**1. `ADR-006` Compliance Engine (Accepted, implemented in
`phantom_pipeline/compliance_engine/`).** Its §8–§11 already specify
news restrictions (blackout windows around high-impact events),
session restrictions, weekend/holiday restrictions, and spread
validation — categories this task also names (News Intelligence,
Session Intelligence, Market Safety, Liquidity Quality). The
distinction this ADR draws, per the task's own explicit instruction
("Never duplicate Compliance Engine responsibilities") and its own
repeated framing ("advisory only," "does NOT approve trades," "Trade
Readiness ... does NOT approve trades"):

- **`ADR-006`'s Compliance Engine has actual, binary, non-bypassable
  blocking authority** over a real `RiskDecision` inside
  `phantom_pipeline`'s wired pipeline. It remains the **only**
  authority that can prevent a real trade.
- **This engine has zero pipeline wiring and zero blocking authority.**
  Per §11 below, its only interface is: consume an `EvidenceReport` (and
  externally-supplied news/liquidity/market-safety facts) in, produce a
  `MarketIntelligenceSnapshot` out. Nothing downstream reads that
  snapshot in this phase — there is no consumer, so by construction
  nothing is actually blocked by anything this engine computes. A
  `blackout_active` field on its output is a **label describing its own
  snapshot**, not a gate on any other system, exactly as `TradeReadiness`
  is explicitly "advisory only."
- This mirrors `titan_protocol/bridge/`'s relationship to
  `phantom_pipeline/ea_bridge/` (`ADR-023`) and `titan_protocol/evidence_engine/`'s
  relationship to `phantom_pipeline/scanner`+`scoring_engine` (`ADR-024`
  §0): a second, independent, advisory-only implementation track under
  `titan_protocol/`, built fresh, never wired to or reusing
  `phantom_pipeline/compliance_engine/`'s actual authority or code.

**2. `ADR-016` AI News Intelligence Layer (Accepted, not yet
implemented).** That ADR is explicitly LLM-based, narrative,
human/Analytics-facing, and explicitly states it is never an automated
input to Compliance Engine's guard. This engine is the opposite shape:
deterministic, rule-based, structured (`NewsEvent`/`PairNewsIntelligence`),
and consumed by nothing yet — no overlap in mechanism or consumer, only
a shared subject-matter (news). No conflict.

**Resolution:** this is a fresh, independent, advisory-only package —
`titan_protocol/market_intelligence/` — with no reuse of and no wiring into
`phantom_pipeline/compliance_engine/` or `ADR-016`'s layer. The one
exception (permitted, not a duplication): it calls
`titan_protocol.evidence_engine.session.analyze_session()` directly for
session-boundary classification, rather than re-deriving those hour
boundaries a second time, per the task's own "never duplicate Evidence
Engine responsibilities" instruction — importing and reusing the exact
function is the way to satisfy that, not avoiding session classification
altogether.

---

# Pipeline position

**Not wired into any execution pipeline** — same posture as the
Evidence Engine (`ADR-024`). Per the user's own stated future sequence:
Evidence Engine → Strategy Engine → Portfolio Statistical Risk Engine →
**Market Intelligence Engine** → Prop Firm Compliance Engine → Research
& Learning Engine → Validation. This ADR defines only the Market
Intelligence Engine; nothing consumes its output yet.

---

# 1. Mission

**The Market Intelligence Engine answers exactly one question: "Are
external market conditions safe and suitable for evaluating this pair
right now?"**

It never answers: should we buy, should we sell, what size, which
strategy, is this FTMO-compliant, should we execute. It produces a
deterministic, explainable, bounded `MarketIntelligenceSnapshot` per
pair — nothing more.

---

# Hard Rules

1. **No trade decision anywhere in this package.** No `BUY`/`SELL`, no
   position size, no strategy selection, no order — verified by a
   structural test, same discipline as `ADR-024` Hard Rule 1.
2. **Pair-specific, never global.** Every enabled pair gets its own
   independent `PairSafety`/`TradeReadiness` — no shared, cross-pair
   aggregate score.
3. **Peg/policy events have no fixed timeout.** Once activated, a
   pair's peg/policy status stays active until an explicit `clear()`
   call — never auto-expires on a timer, never inferred from elapsed
   time.
4. **Absolute blockers are hard-zeroed, not blended.** An active
   peg/policy event, broker maintenance, a trading halt, or a closed
   market forces `PairSafety`/`TradeReadiness` to `0`, never a
   proportionally-reduced blend with other factors — these are
   categorical, not gradations.
5. **Deterministic, thread-safe, fail-closed.** Same inputs, same
   output. If a required input is missing/untrustworthy, the engine
   fails closed (returns a snapshot describing itself as untrustworthy/
   blocked), never silently defaults to "safe."
6. **Zero authority, zero wiring.** This package imports nothing from
   `phantom_pipeline/`, `titan_protocol/bridge/`, or any strategy/risk/
   compliance code. It consumes `EvidenceReport` (`ADR-024`) read-only
   and its own directly-supplied news/liquidity/market-safety inputs;
   it produces `MarketIntelligenceSnapshot` and nothing else.

---

# 2. Architecture

```
titan_protocol/market_intelligence/
    models.py              NewsImpact, NewsCategory, NewsEvent,
                           PegPolicyEventType, PegPolicyStatus,
                           PairNewsIntelligence, SessionIntelligence,
                           LiquidityIntelligence, MarketSafetyStatus,
                           MarketSafetyInputs, PairSafety, TradeReadiness,
                           MarketIntelligenceExplanation,
                           MarketIntelligenceSnapshot
    config.py              MarketIntelligenceConfig -- every threshold
                           and weight named; embeds an
                           EvidenceEngineConfig instance for session-
                           boundary reuse only
    news.py                pair-currency extraction, event filtering,
                           blackout window computation, news score
    peg_policy.py           PegPolicyRegistry -- explicit activate/clear,
                           no auto-timeout (mirrors the Bridge's
                           EmergencyStopState pattern, not its code)
    session_intelligence.py reuses evidence_engine.session.analyze_session(),
                           applies MI-specific preference weighting
    liquidity_intelligence.py spread-ratio-based liquidity scoring
    market_safety.py        holiday/early-close/weekend/maintenance/
                           halt/closure scoring
    scoring.py              PairSafety + TradeReadiness composites
    explainability.py       MarketIntelligenceExplanation assembly
    engine.py               MarketIntelligenceEngine.evaluate()/
                           evaluate_batch(), bounded news-feed cache
    logging_sink.py, metrics.py, __init__.py
```

No file here imports `phantom_pipeline/` or `titan_protocol/bridge/`. No file
in `titan_protocol/evidence_engine/` is modified.

---

# 3. Testing (mandatory before Accepted → Done)

Per the user's 9-category mandate: unit, integration, boundary,
concurrency, determinism, caching, failure-mode, architecture,
regression.

---

# Success Criteria

- Every pair's safety/readiness computed independently — no shared
  global score.
- Peg/policy events never auto-clear; only an explicit `clear()` call
  resets them.
- Absolute blockers (peg/policy, maintenance, halt, closure) always
  force score `0`, verified by dedicated tests, never bypassed by a
  weighted blend.
- `scripts/check_architecture.py`-equivalent dedicated test confirms no
  import from `phantom_pipeline/` or `titan_protocol/bridge/`, and confirms the
  one permitted import (`titan_protocol.evidence_engine.session`).
- No trade is ever placed, sized, or approved by this package.
