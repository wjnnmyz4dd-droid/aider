# Technical Specification — Strategy Engine

Specification only. Cross-references `PHANTOM_FINAL_ARCHITECTURE.md`
and `PHANTOM_IMPLEMENTATION_ROADMAP.md` Phase 4a.

## 1. Purpose

Decide which, if any, of the five approved confirmation playbooks
applies to a pair's current `PairEvidence`, and if one does, produce a
`TradeIdea` — never a sized or executed trade.

## 2. Responsibilities

- Maintain the playbook registry (auto-discovered, never hand-listed).
- Run every registered playbook against the pair's current
  `PairEvidence` and resolve to at most one `TradeIdea` per evaluation
  cycle per pair, using the tie-break order in §7.1 whenever more than
  one playbook's conditions are simultaneously satisfied.
- Attach the originating playbook's identity and the specific
  entry/exit/invalidation levels it computed to the `TradeIdea`.

**Revision (Architecture Hardening — closes Red Team Audit Finding
2.1's dependency on this component):** Strategy Engine no longer checks
`is_halted()` or `get_entry_gate()` itself. Both are now checked by
`phantom/runtime/runtime.py` (`docs/specs/00_runtime_orchestrator.md`
§5) — the halt check before *any* component is called for a cycle, and
the entry-gate check *after* Strategy Engine returns an idea, before
Risk Engine is called. This removes Strategy Engine's direct dependency
on Market Intelligence Engine and System Reliability Engine entirely
(see revised §8) and centralizes cross-cutting preconditions in the one
component whose job is sequencing.

## 3. Public interfaces

```
strategy_engine.evaluate(pair: Pair, now: Clock) -> Tuple[TradeIdea, ...]
strategy_engine.evaluate_all(now: Clock) -> Mapping[Pair, Tuple[TradeIdea, ...]]
```

**Revision (Architecture Hardening):** return type changed from
`Optional[TradeIdea]` to `Tuple[TradeIdea, ...]` (usually empty or
one-element, but may hold more than one when multiple playbooks
simultaneously qualify) — closes Red Team Audit Finding 8.1 by making
the "more than one playbook qualified" case an explicit, observable
output rather than something the registry's iteration order silently
resolved. Strategy Engine itself does **not** pick a winner among
multiple candidates — see the §4 note below.

Internal-only (not exposed outside this package):
`registry.applicable_playbooks(evidence: PairEvidence) ->
Tuple[Playbook, ...]`, and each `Playbook.confirm(evidence) ->
Optional[TradeIdea]`.

## 4. Inputs

- `PairEvidence` from Evidence Engine (score, regime, structure
  findings) — as of this revision, the *only* other component's data
  this input list names; `EntryGateDecision` and `is_halted()` are no
  longer inputs to this component (see §2 revision).
- Per-playbook configuration (`config.py`): which playbooks are
  enabled, per-playbook parameter overrides.

**Note on tie-break inputs:** the tie-break cascade in §7.1 needs data
Strategy Engine deliberately does not hold (historical strategy
performance from Research & Learning Engine, statistical confidence and
portfolio exposure from Risk Engine, liquidity/news-risk from Market
Intelligence Engine). Giving Strategy Engine those dependencies would
both re-expand its dependency footprint (reversing this revision's own
simplification) and, for Research & Learning Engine specifically,
violate the existing one-directional-flow rule (`phantom/strategy/`
must never import from `phantom/research/`). Resolving this: Strategy
Engine's `evaluate()` returns *every* currently-qualifying candidate
idea for a pair (§3, revised), and the tie-break cascade itself is
resolved by `phantom/runtime/runtime.py`, the one component already
permitted to depend on all 8 others. See
`docs/specs/00_runtime_orchestrator.md` §5.1 for the resolution
procedure.

## 5. Outputs

Zero or more `TradeIdea`s per pair per cycle: pair, direction,
originating strategy kind, proposed entry level/condition, proposed
exit level(s), invalidation condition, the `PairEvidence` snapshot it
was built from, and a timestamp. No volume, no order type beyond
direction — sizing is Risk Engine's job entirely. More than one
`TradeIdea` for the same pair in the same cycle means more than one
playbook currently qualifies; Strategy Engine reports this fact, it
does not resolve it (§7).

## 6. Internal data models

| Model | Shape |
|---|---|
| `StrategyKind` | enum: `LIQUIDITY_SWEEP`, `BOS_FVG`, `TREND_CONTINUATION`, `SESSION_BREAKOUT`, `RANGE_REVERSAL` |
| `TradeIdea` | `(pair, direction, strategy_kind, entry, exit_levels, invalidation, evidence_snapshot, created_at)` |
| `Playbook` (interface) | one method: `confirm(evidence: PairEvidence) -> Optional[TradeIdea]`; every playbook file implements exactly this |

## 7. Decision authority

Confirmation only. Strategy Engine decides *which pattern(s) are
present*, never *whether to trade one* (that composite decision
belongs to Risk Engine + Compliance Engine downstream), never *how
much* to trade, and — as of this revision — never *which one wins*
when more than one playbook qualifies simultaneously.

### 7.1 Tie-break resolution (owned by Runtime, specified here for
completeness)

When `evaluate()` returns more than one `TradeIdea` for a pair in one
cycle, `phantom/runtime/runtime.py` resolves exactly one winner using
this fixed, deterministic cascade — no step is skipped, no randomness
at any point:

1. **Evidence score** — the candidate whose `evidence_snapshot.score`
   is higher wins; tie proceeds to 2.
2. **Historical strategy performance** — the candidate whose
   `strategy_kind` ranks higher in Research & Learning Engine's
   `strategy_ranking.py` output wins; tie proceeds to 3.
3. **Statistical confidence** — the candidate Risk Engine's
   `portfolio_stats()` currently associates with higher confidence
   (e.g. a lower recent variance/drawdown-probability for that
   strategy kind) wins; tie proceeds to 4.
4. **Lower portfolio exposure** — the candidate that would add less
   currency/correlation exposure (per Risk Engine's current
   `PortfolioSnapshot`) wins; tie proceeds to 5.
5. **Higher liquidity quality** — the candidate whose pair currently
   has the higher `liquidity_quality` from Market Intelligence
   Engine's `PairIntelligence` wins; tie proceeds to 6.
6. **Lower news risk** — the candidate whose pair currently has the
   lower `MarketImpactScore` wins.
7. **Still tied after all six** — reject the pair for this cycle
   entirely; no idea proceeds. Never break a tie by arbitrary/insertion
   order, and never introduce randomness anywhere in this cascade.

This closes Red Team Audit Finding 8.1. Because this cascade requires
Research & Learning Engine's, Risk Engine's, and Market Intelligence
Engine's data, it is deliberately specified as Runtime's
responsibility, not Strategy Engine's — see §4's note above and
`docs/specs/00_runtime_orchestrator.md` §5.

## 8. Dependencies

Evidence Engine only, plus `phantom/shared/`. (Revised — Market
Intelligence Engine and System Reliability Engine are no longer direct
dependencies; see §2.)

## 9. Explicit non-responsibilities

- Never sizes a position (no lot/volume concept anywhere in
  `TradeIdea`).
- Never submits a command to PhantomBridgeEA — has no dependency on
  `phantom/bridge` at all.
- Never checks Market Intelligence Engine's entry gate or System
  Reliability Engine's halt state itself — Runtime does, before and
  after calling this component respectively (§2).
- Never resolves a tie among multiple simultaneously-qualifying
  playbooks itself — reports all of them; Runtime resolves per §7.1.
- Never hand-lists playbook names anywhere (registry is auto-discovery
  only, per the drift-risk lesson already on record for this exact
  anti-pattern).
- Never recomputes regime or market structure independently of
  `evidence.regime`/`evidence.findings` — closes Red Team Audit Finding
  1.1; enforced by a structural-boundary test asserting no file under
  `phantom/strategy/playbooks/` imports
  `phantom/evidence/regime.py`/`market_structure.py` directly.

## 10. Test plan

- One fixture-driven unit-test suite per playbook (below).
- `registry.py` auto-discovery test: adding a new playbook file makes
  it appear in `applicable_playbooks` output with zero other code
  changes.
- **Multi-candidate test** (revised from "mutual-exclusion test"): a
  crafted fixture where two playbooks' conditions both match must
  produce a `Tuple` with both `TradeIdea`s present — Strategy Engine
  itself must **not** collapse this to one internally.
- **No-independent-regime test:** a fixture confirms no playbook's
  output changes if `market_structure.py`'s internal detail changes
  while `evidence.regime` is held fixed (proves playbooks consume only
  the public `PairEvidence` surface).
- Structural-boundary test per §9's regime-duplication rule.

## 11. Performance requirements

`evaluate_all` across the full enabled-pair list must complete within
Strategy Engine's own decision-cycle budget (target: well under 1
second for a realistic enabled-pair count, validated during
implementation) — this is a target, not a guarantee made here.
Single-threaded caller assumed (Runtime); this component is not
required to be internally thread-safe (closes Red Team Audit Finding
5.2 for this component).

## 12. Failure modes

| Failure | Expected behavior |
|---|---|
| A playbook raises during `confirm()` | Caught per-playbook at `strategy_engine.py`; that playbook contributes no idea this cycle, logged, other playbooks/pairs unaffected. |
| Tie-break cascade's upstream data (Research/Risk/Intelligence) unreachable during Runtime's resolution | Fail closed — Runtime rejects the tied pair for this cycle rather than guessing a winner from partial data. |

## 13. Security considerations

In-process library, no external network surface. No user-supplied
input beyond configured pair/playbook enablement lists.

## 14. Logging requirements

`logging_sink.py` logs every `TradeIdea` produced (pair, strategy kind,
levels) and every multi-candidate cycle (which playbooks qualified,
handed to Runtime for tie-break). `metrics.py` tracks ideas produced
per strategy kind, multi-candidate frequency, and per-playbook
evaluation latency. Gate/halt suppression is now logged by Runtime
(§14 of `docs/specs/00_runtime_orchestrator.md`), not here.

**Authority restatement (Architecture Hardening):** Strategy Engine
holds **selection/confirmation authority only** — the sole source of
"which pattern(s) are present." It claims no scoring, sizing, gating,
or execution authority (see the system-wide authority matrix in
`PHANTOM_ARCHITECTURE_HARDENING.md`).

---

## The five approved strategies (playbooks), in detail

Each is a **confirmation layer only** — it identifies whether its own
named pattern is present in the current `PairEvidence`; it never
decides trade size or executes.

### 1. Liquidity Sweep

- **Market conditions:** an established, well-respected liquidity pool
  (equal highs/lows, a prior session's high/low, or an untested swing
  point) that has not yet been swept.
- **Entry conditions:** price trades beyond the liquidity pool and
  produces a sharp rejection (a wick/rapid-reversal candle, or a
  lower-timeframe micro break-of-structure back through the sweep
  point) — entry triggers on that confirmed reversal, never on the
  sweep itself.
- **Exit conditions:** take-profit at the next significant structure
  level (the opposing liquidity pool or prior swing point), with an
  optional trail behind newly formed swing points in the reversal's
  direction.
- **Invalidation conditions:** a decisive close beyond the sweep
  extreme with no rejection (the sweep becomes a genuine breakout), or
  no rejection candle forms within the configured bar window after the
  sweep.
- **Preferred sessions:** London open and New York open — liquidity
  pools are most reliably swept at session-open volume; an Asian-range
  sweep at London open is the classic sub-case.
- **Suitable currency pairs:** majors with clean, well-respected range
  structure and session-driven liquidity — EURUSD, GBPUSD, USDJPY,
  GBPJPY. Avoid illiquid/exotic pairs, where apparent sweeps are noise
  rather than structural.

### 2. Break of Structure + Fair Value Gap (BOS + FVG)

- **Market conditions:** a trending or transitioning market with a
  just-confirmed structural break (a decisive close beyond the
  relevant swing point) leaving an imbalance (FVG) in the impulsive
  leg.
- **Entry conditions:** after the confirmed BOS, price retraces into
  the FVG created by the impulsive move; entry on rejection from the
  FVG (or its consequent-encroachment midpoint) in the break's
  direction.
- **Exit conditions:** take-profit at the next opposing structure
  level or a measured-move projection of the impulsive leg; optional
  partial exit at a fixed R-multiple with a trailing runner.
- **Invalidation conditions:** price trades fully through the FVG and
  closes beyond it without reacting (imbalance fully filled, structure
  fails), or an opposite-direction BOS occurs before entry triggers.
- **Preferred sessions:** the London/New York overlap — highest-quality
  impulsive moves with real follow-through; avoid low-volume Asian-
  session breaks, which are prone to false BOS.
- **Suitable currency pairs:** trending majors/crosses with clean
  impulsive legs — EURUSD, GBPUSD, USDJPY, EURJPY, AUDUSD. Underperforms
  on choppy/range-bound pairs.

### 3. Trend Continuation

- **Market conditions:** Evidence Engine's regime classified as
  `TRENDING`, with a healthy pattern of higher-highs/higher-lows (or
  the inverse) and no recent structural break against the trend.
- **Entry conditions:** a shallow pullback to a prior order block,
  minor support/resistance, or dynamic level within the trend, with a
  confirming lower-timeframe reaction (rejection candle or a minor BOS
  in the trend's own direction).
- **Exit conditions:** trailing exit behind newly formed swing points
  in the trend direction; a secondary hard target at a prior extension
  or measured-move/psychological level.
- **Invalidation conditions:** a break of structure against the
  prevailing trend (the pullback becomes a reversal), or the pullback
  exceeding a configured depth (retracing past the most recent
  higher-low/lower-high).
- **Preferred sessions:** whichever session is actively extending the
  already-established trend — commonly the session that initiated it;
  avoid entries in a session with no relationship to the trend's
  driving order flow.
- **Suitable currency pairs:** regime-gated, not a fixed list — any
  pair Evidence Engine currently classifies as cleanly trending is
  eligible; this strategy has no pair preference of its own beyond
  that regime confirmation.

### 4. Session Breakout

- **Market conditions:** a well-respected consolidation range formed
  during a lower-liquidity session (commonly Asian), with multiple
  boundary touches and low volatility inside it.
- **Entry conditions:** a confirmed break of the range's high or low at
  or shortly after the next major session's open, ideally with a
  retest of the broken boundary before continuation (to filter false
  breakouts).
- **Exit conditions:** take-profit at a measured-move projection of the
  range's height from the breakout point, or the next major structural
  level; trail once price extends beyond one range-height.
- **Invalidation conditions:** price re-enters the range and closes
  back inside it after the breakout (false breakout), or the breakout
  reverses within a small configured number of bars with no retest
  ever forming.
- **Preferred sessions:** the breakout is timed to a session
  transition — London open breaking an Asian range, or New York open
  breaking a London range; the strategy is inherently
  session-transition-driven.
- **Suitable currency pairs:** pairs with a reliable Asian-session
  consolidation habit (USDJPY, AUDUSD, NZDUSD, AUDJPY) for the
  London-open variant; pairs with a reliable London-session range
  (EURUSD, GBPUSD) for the New-York-open variant.

### 5. Range Reversal

- **Market conditions:** Evidence Engine's regime classified as
  `RANGING`, with clearly bounded, multiply-tested boundaries and no
  active trend bias.
- **Entry conditions:** at or near a range boundary, on a confirming
  rejection signal — a rejection candle, a minor liquidity sweep of the
  boundary followed by reversal, or a lower-timeframe BOS back into the
  range. Never on a bare touch of the boundary with no confirmation.
- **Exit conditions:** take-profit at the opposing range boundary, with
  an optional conservative partial exit at range mid-equilibrium.
- **Invalidation conditions:** a confirmed breakout of the boundary
  (structure break out of the range) invalidates that touch's reversal
  thesis; also invalidated if no rejection signal forms within the
  configured bar window after the touch.
- **Preferred sessions:** lower-volatility sessions where ranges are
  more likely to hold (commonly Asian, for pairs that range predictably
  there); avoid major-session opens and high-impact news windows —
  Market Intelligence Engine's entry gate is expected to block most of
  these automatically regardless.
- **Suitable currency pairs:** pairs prone to clean, sustained ranges
  rather than trend persistence — EURGBP, AUDNZD, USDCHF in quiet
  periods. Underperforms on pairs with strong directional bias.
