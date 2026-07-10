# ADR-024 — Evidence Engine

Status: **Accepted**

**Amendment 1 (2026-07-10):** expands the engine's output with a new,
additive `EvidenceSnapshot` type carrying the raw structural/liquidity/
candlestick facts already computed internally (previously discarded
after being folded into `ComponentScore`s) plus a new
`SupportResistanceContext` (Previous Day/Week/Month High/Low, Session
High/Low, Psychological Levels, Confluence Score, Break Quality Score,
False Break Probability — concepts this engine never computed before).
Triggered by Phase 2C (Strategy Engine): that phase's own spec requires
consuming raw structural/liquidity/candlestick facts and several S/R
concepts Evidence Engine didn't expose, while simultaneously forbidding
both modifying Evidence Engine and building a second, duplicate analyzer
inside Strategy Engine. Put to the user directly; the explicit answer,
given twice, was **"expand the EvidenceSnapshot, not create a second
analyzer"** — the same resolution `ADR-002` Amendment 1 already
established as this project's precedent for exactly this situation
("resolved as an amendment to this ADR rather than a new pipeline
stage... to avoid creating a second authority over facts this ADR
already owns"). **This supersedes the "Do NOT modify Evidence Engine"
line in the Phase 2C prompt** — the user's direct clarification is a
more specific, later instruction than that prompt's blanket prerequisite,
per normal instruction precedence. Purely additive: `EvidenceReport`,
`evaluate()`, and every existing type/field/test are byte-for-byte
unchanged — verified by re-running the full pre-amendment test suite
unmodified. Additions appear in §2, §3 (new Hard Rule 9), and Testing,
each marked "Amendment 1."

**Amendment 2 (2026-07-10, same trigger):** while implementing the
"BOS + Fair Value Gap" strategy, Strategy Engine needs Fair Value Gap
(FVG) detection -- a 3-candle price-imbalance concept this engine never
computed, and (per Amendment 1's same resolution) not something
Strategy Engine may derive itself from raw bars, since its declared
inputs are the two snapshots only, never raw bars. Resolved identically
to Amendment 1, under the same explicit user direction ("expand the
EvidenceSnapshot, not create a second analyzer") already given for this
exact class of gap: adds `detect_fair_value_gaps()` to `structure.py`
and a new `fair_value_gaps` field on `EvidenceSnapshot` (not on
`MarketStructureResult`, which stays byte-for-byte unchanged) computed
from the same single analysis pass. Purely additive; the full
pre-amendment-2 suite passes unmodified.

Owner: Software Architect (per `.claude/agents/TEAM.md`'s precedent for
cross-cutting evaluation components — same accountable role as
ADR-002/ADR-004)

Accepted By: User direction, this session (explicit, full specification:
7 responsibility categories — market structure, liquidity, candlestick
intelligence, trend, volatility, session awareness, indicator framework
— plus scoring/ranking/explainability requirements, architecture rules,
performance targets, and an 8-category testing mandate) — the same
in-session approving authority already used to accept `ADR-020` through
`ADR-023`.

Reviewed by: (post-hoc, this session) — confirmed against
`ADR-001`'s "no duplicate scoring" rule and `ADR-002` Amendment 1's
precedent before acceptance; see §0 below.

Date: 2026-07-10

Depends on: none. This ADR deliberately does not depend on
`ADR-001-single-authority-architecture.md` or any of its per-stage
successors (`ADR-002` onward) — see §0.

---

# 0. Relationship to the existing `phantom_pipeline/` pipeline

This is the decision this ADR exists to record, made explicitly with the
user before any code was written (three direct questions, three direct
answers):

1. **Location:** `phantom/evidence_engine/` — a new, independent package
   alongside `phantom/bridge/`, not `phantom_pipeline/evidence_engine/`.
2. **Relationship to `ADR-002-scanner.md` (Accepted, implemented in
   `phantom_pipeline/scanner/`) and `ADR-004-scoring-engine.md`
   (Accepted, implemented in `phantom_pipeline/scoring_engine/`):**
   fully fresh, clean-room implementation. **No code, module, or class is
   ported or imported from `phantom_pipeline/`.** This mirrors the
   relationship `phantom/bridge/` already has to
   `phantom_pipeline/ea_bridge/` (ADR-023) — a second, independent
   implementation track under `phantom/`, built and hardened
   turn-by-turn this session, deliberately not reusing the
   `phantom_pipeline/` codebase.
3. **ADR gate:** this document — drafted and marked Accepted in the same
   session as the implementation, per the established precedent of
   `ADR-020` through `ADR-023`, satisfying the Phantom Protocol's rule
   that no pipeline-stage implementation begins without an Accepted ADR
   for that stage (CLAUDE.md §1.10).

**This is a real scope overlap, acknowledged, not hidden:** `ADR-002`
Scanner already computes market structure (BOS/CHOCH/swing/S-R),
liquidity concepts, and session detection; `ADR-004` Scoring Engine
already computes a weighted, explainable composite score with
reason/weight/confidence per component, plus ranking. `ADR-002`
Amendment 1 explicitly rejected building a *separate* pipeline stage for
overlapping market-structure scope, to avoid a second authority over the
same facts — this ADR takes the opposite resolution, per explicit user
direction, because `Evidence Engine` is not extending `phantom_pipeline/`'s
single authority; it is part of a **separate, independent track**
(`phantom/`) that does not participate in `phantom_pipeline/`'s pipeline
at all. There is exactly one authority for each fact **within each
track**; the two tracks are not wired together by this ADR, and nothing
in `phantom/evidence_engine/` calls, imports, or is called by anything in
`phantom_pipeline/`.

---

# Pipeline position

**The Evidence Engine is not wired into any execution pipeline. It is a
standalone measurement/scoring component with no consumer yet.** Per the
user's own stated ordering (given at Bridge-freeze time), the intended
future sequence for this track is:

Evidence Engine → Strategy Engine → Portfolio Statistical Risk Engine →
Market Intelligence Engine → Prop Firm Compliance Engine → Research &
Learning Engine → Validation

Each of those later stages is out of scope here and requires its own
Accepted ADR before implementation, per CLAUDE.md §1.10. This ADR defines
only the Evidence Engine.

---

# 1. Mission

**The Evidence Engine answers exactly one question: "How strong is the
observable market evidence for a given pair, right now?"**

It **never** answers: should we buy, should we sell, what size, is this
compliant, is a news event blocking this, should we execute. It produces
a deterministic, explainable, bounded score (0–100) per pair from
independently-computed evidence components — nothing more.

---

# Hard Rules

1. **No trade decision anywhere in this package.** No `BUY`/`SELL`
   enum, no position size, no stop loss / take profit, no order,
   anywhere in `phantom/evidence_engine/`. A structural test enforces
   this (see Testing).
2. **No duplicate scoring.** Every one of the seven component scores
   (structure, liquidity, candlestick, trend, volatility, session,
   indicator) is computed from independent inputs; no signal is counted
   twice within a single Evidence Score.
3. **No hidden calculations.** Every component score carries a `reason`
   (human-readable), a `weight` (its contribution to the composite), and
   a `confidence` (0–1). The composite `EvidenceScore` is a fully
   reproducible weighted function of its components — nothing computed
   off-band.
4. **No randomness, no ML, no AI.** Every function in this package is a
   pure, deterministic transform of its Bar/OHLC input. Same input bars
   always produce the same `EvidenceReport`, byte-for-byte comparable
   field by field.
5. **No news, no risk, no compliance, no execution.** This package
   imports nothing from `risk_engine`, `compliance_engine`,
   `execution_validator`, `mt5_bridge`, `position_manager`, or any
   `phantom_pipeline/` package. It has no network calls, no file I/O
   beyond its own logging sink.
6. **One responsibility only.** Given a symbol's recent bars, produce an
   `EvidenceReport`. Given several pairs' reports, rank them by score.
   That is the entire public surface.
7. **Indicator framework is an interface only in this phase.** `EMA`,
   `RSI`, `ADX`, `MACD`, `Stochastic`, `Bollinger`, `Volume`, `VWAP` are
   named as future indicators this framework must support, but none are
   implemented as concrete indicators in Phase 2A — only the `Indicator`
   ABC, a registry, and a caching layer are built now.
8. **Thread safety without duplicate work.** Evaluating N pairs
   concurrently must not corrupt shared state and must not recompute the
   same indicator twice for the same symbol/bar-set/parameters within one
   evaluation cycle (caching, keyed by content, not by wall-clock time).
9. **(Amendment 1) Additive only, one computation per fact.**
   `EvidenceSnapshot` carries the *exact same* structure/liquidity/
   candlestick results `evaluate()` already computes internally for the
   `EvidenceReport` — `evaluate_snapshot()` never runs
   `analyze_market_structure`/`analyze_liquidity`/`recognize_patterns`
   a second time for the same bars; it computes once and populates both
   the existing `EvidenceReport` and the new raw fields from that one
   pass. The new `support_resistance.py` module is new logic (nothing
   in `structure.py` computed Previous Day/Week/Month High/Low, Session
   High/Low, Psychological Levels, Confluence, Break Quality, or False
   Break Probability before this amendment) — not a duplicate of
   anything pre-existing.

---

# 2. Architecture

```
phantom/evidence_engine/
    models.py          Bar, SwingPoint, StructureEvent, LiquidityPool,
                        LiquiditySweep, CandlestickMatch, TrendState,
                        VolatilityState, SessionState, IndicatorResult,
                        ComponentScore, EvidenceScore, EvidenceReport,
                        PairRanking
    config.py           EvidenceEngineConfig -- every threshold/weight
                        named, no magic numbers
    structure.py         swings, BOS, CHOCH (internal/external), trend
                        leg detection, support/resistance levels
    liquidity.py         equal highs/lows, liquidity pools, sweeps, stop
                        hunts, liquidity-trap filter, displacement
    candlesticks.py       1/2/3-candle pattern recognition with quality/
                        context/confidence
    trend.py            trending-up/down/range/compression/expansion/
                        reversal classification
    volatility.py        ATR, expansion/compression, volatility score
    session.py          London/overlap/early-NY/late-NY/Asian + quality
    indicators.py         Indicator ABC + registry + cache (interface
                        only -- no concrete indicators yet)
    scoring.py          per-component ComponentScore -> composite
                        EvidenceScore (0-100)
    ranking.py           rank enabled pairs by EvidenceScore
    explainability.py    EvidenceReport assembly (strengths/weaknesses/
                        confidence narrative)
    engine.py            EvidenceEngine.evaluate()/evaluate_batch() --
                        orchestrates the above, thread-safe, caches
                        indicator results per (symbol, bar signature)
    logging_sink.py       structured logging (same conventions as
                        phantom/bridge/logging_sink.py)
    metrics.py           counters/gauges (same conventions as
                        phantom/bridge/metrics.py)
    __init__.py          public exports
```

No file here imports anything from `phantom_pipeline/`. No file in
`phantom_pipeline/` is modified by this ADR.

**(Amendment 1) New/changed files:**

```
    models.py            + EvidenceSnapshot, SupportResistanceContext,
                        PsychologicalLevel, ConfluenceZone (additive --
                        every pre-existing type/field unchanged)
    support_resistance.py  (new) Previous Day/Week/Month High/Low,
                        Session High/Low, Psychological Levels,
                        Confluence Score, Break Quality Score, False
                        Break Probability
    engine.py            + EvidenceEngine.evaluate_snapshot() (new
                        method; evaluate() itself is untouched)
```

---

# 3. Testing (mandatory before Accepted → Done)

Per the user's 8-category mandate: unit, property, boundary, performance
(28+ pairs simultaneously), determinism (same input → same output, run
twice), explainability (every score traces to a reason), regression, and
architecture (no forbidden imports, no trade-decision types, no
randomness).

**(Amendment 1):** the full pre-amendment suite (110 tests) must pass
unmodified, proving zero regression, plus new tests for
`support_resistance.py` and `evaluate_snapshot()` covering the same 8
categories.

---

# Success Criteria

- Evidence Score is bounded [0, 100] for all valid inputs, for every
  pair, always.
- Every `ComponentScore` and the composite `EvidenceScore` carries a
  `reason`, `weight`, and `confidence`.
- Two calls with identical input bars produce identical
  `EvidenceReport`s (determinism test).
- 28+ pairs evaluated in one `evaluate_batch()` call with no duplicate
  indicator computation and no shared-state corruption under concurrent
  use.
- `scripts/check_architecture.py` (extended for this package) confirms
  no import from any `phantom_pipeline/` package and no import of
  trade-decision vocabulary (`BUY`/`SELL`/order/position-size types).
- No trade is ever placed, sized, or approved by this package — it is
  physically incapable of it (no such method exists in its public
  surface).
