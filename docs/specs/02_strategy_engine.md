# Technical Specification — Strategy Engine

Specification only. Cross-references `PHANTOM_FINAL_ARCHITECTURE.md`
and `PHANTOM_IMPLEMENTATION_ROADMAP.md` Phase 4a.

## 1. Purpose

Decide which, if any, of the five approved confirmation playbooks
applies to a pair's current `PairEvidence`, and if one does, produce a
`TradeIdea` — never a sized or executed trade.

## 2. Responsibilities

- Maintain the playbook registry (auto-discovered, never hand-listed).
- Check System Reliability Engine's `is_halted()` and Market
  Intelligence Engine's `get_entry_gate()` before evaluating any
  playbook for a pair.
- Run every registered playbook against the pair's current
  `PairEvidence` and let at most one playbook produce a `TradeIdea` per
  evaluation cycle per pair.
- Attach the originating playbook's identity and the specific
  entry/exit/invalidation levels it computed to the `TradeIdea`.

## 3. Public interfaces

```
strategy_engine.evaluate(pair: Pair, now: Clock) -> Optional[TradeIdea]
strategy_engine.evaluate_all(now: Clock) -> Mapping[Pair, Optional[TradeIdea]]
```

Internal-only (not exposed outside this package):
`registry.applicable_playbooks(evidence: PairEvidence) ->
Tuple[Playbook, ...]`, and each `Playbook.confirm(evidence) ->
Optional[TradeIdea]`.

## 4. Inputs

- `PairEvidence` from Evidence Engine (score, regime, structure
  findings).
- `EntryGateDecision` from Market Intelligence Engine.
- `is_halted()` from System Reliability Engine.
- Per-playbook configuration (`config.py`): which playbooks are
  enabled, per-playbook parameter overrides.

## 5. Outputs

`TradeIdea`: pair, direction, originating strategy kind, proposed
entry level/condition, proposed exit level(s), invalidation condition,
the `PairEvidence` snapshot it was built from, and a timestamp. No
volume, no order type beyond direction — sizing is Risk Engine's job
entirely.

## 6. Internal data models

| Model | Shape |
|---|---|
| `StrategyKind` | enum: `LIQUIDITY_SWEEP`, `BOS_FVG`, `TREND_CONTINUATION`, `SESSION_BREAKOUT`, `RANGE_REVERSAL` |
| `TradeIdea` | `(pair, direction, strategy_kind, entry, exit_levels, invalidation, evidence_snapshot, created_at)` |
| `Playbook` (interface) | one method: `confirm(evidence: PairEvidence) -> Optional[TradeIdea]`; every playbook file implements exactly this |

## 7. Decision authority

Confirmation only. Strategy Engine decides *which pattern is present*,
never *whether to trade it* (that composite decision belongs to Risk
Engine + Compliance Engine downstream) and never *how much* to trade.

## 8. Dependencies

Evidence Engine (Phase 3a), Market Intelligence Engine (Phase 3b),
System Reliability Engine (Phase 3c), `phantom/shared/`.

## 9. Explicit non-responsibilities

- Never sizes a position (no lot/volume concept anywhere in
  `TradeIdea`).
- Never submits a command to PhantomBridgeEA — has no dependency on
  `phantom/bridge` at all.
- Never overrides Market Intelligence Engine's entry gate or System
  Reliability Engine's halt state.
- Never lets two playbooks both fire for the same pair in the same
  evaluation cycle (would be a duplicate signal, forbidden by the
  Charter's Strategy philosophy) — `registry.applicable_playbooks`
  plus `evaluate`'s "at most one" rule enforces this structurally.
- Never hand-lists playbook names anywhere (registry is auto-discovery
  only, per the drift-risk lesson already on record for this exact
  anti-pattern).

## 10. Test plan

- One fixture-driven unit-test suite per playbook (below).
- `registry.py` auto-discovery test: adding a new playbook file makes
  it appear in `applicable_playbooks` output with zero other code
  changes.
- Entry-gate/halt suppression integration tests: a fixture pair whose
  evidence would otherwise fire a playbook produces no `TradeIdea` when
  `get_entry_gate` returns any `BLOCKED_*` value or `is_halted()` is
  true.
- Mutual-exclusion test: a crafted fixture where two playbooks' naive
  conditions could both match must still produce exactly one
  `TradeIdea`.

## 11. Performance requirements

`evaluate_all` across the full enabled-pair list must complete within
Strategy Engine's own decision-cycle budget (target: well under 1
second for a realistic enabled-pair count, validated during
implementation) — this is a target, not a guarantee made here.

## 12. Failure modes

| Failure | Expected behavior |
|---|---|
| A playbook raises during `confirm()` | Caught per-playbook at `strategy_engine.py`; that playbook contributes no idea this cycle, logged, other playbooks/pairs unaffected. |
| Market Intelligence Engine or System Reliability Engine unreachable/erroring | Fail closed — no `TradeIdea` is ever produced if either upstream gate cannot be positively confirmed as `ALLOWED`/not-halted. |

## 13. Security considerations

In-process library, no external network surface. No user-supplied
input beyond configured pair/playbook enablement lists.

## 14. Logging requirements

`logging_sink.py` logs every `TradeIdea` produced (pair, strategy kind,
levels) and every suppressed evaluation (pair, reason: gate/halt/no
playbook matched). `metrics.py` tracks ideas produced per strategy
kind, suppression counts by reason, and per-playbook evaluation
latency.

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
