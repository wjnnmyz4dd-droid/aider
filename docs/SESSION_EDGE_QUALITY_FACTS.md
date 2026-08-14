# Session Edge — Setup-Quality Fact Instrumentation (PR-3P)

Status: **MEASUREMENT-ONLY.** Exposes continuous setup-quality facts for research and
future score-model design. It implements **no trade score**, **no 70 gate**, **no
score-based sizing**, and changes **no trading behavior** (zero production trading-module
diff — all code is in `research/`).

## Why (PR-3O recap)
PR-3O was blocked because the frozen engine collapses quality-bearing information into
booleans/hard gates: `rr_planned ≡ rr_target` (constant), trend/health are fully hard-
gated, and the only varying emitted facts collapse to a single OR/ATR geometry axis. The
two potentially-independent signals (breakout-bar extent, confirmation margin) were
computed only as booleans and discarded. A defensible score could not be derived. PR-3P
exposes the *continuous* facts that ARE derivable from what the engine already emits, so
a later score model can be designed on evidence.

## Canonical owner
`research/quality_facts.py::extract(instruction)` — the ONE observational extraction
owner. It is a **pure, deterministic** function of an immutable authorized instruction's
already-emitted `evidence_summary` (+ top-level `entry_price`/`stop_loss`). It reads no
bars, calls no engine, recomputes no strategy state, and touches no broker. Research
ingest/join: `research/lifecycle.py::quality_dataset`. Cohorts remain owned solely by
`research/lifecycle.py::cohort_of` (dormant/UNAVAILABLE — no score).

`quality_fact_version = "session_edge_quality.v1"` (passive; distinct from
`strategy_version`, and there is still **no** `score_model_version`).

## Facts exposed (formula + unit) — all CONTINUOUS QUALITY FACTS

| Fact | Formula (from emitted evidence) | Unit |
|---|---|---|
| `range_width_price` | `range_high − range_low` | price |
| `range_width_atr` | `range_width_price / atr14` | ATR (dimensionless) |
| `retest_depth_price` | `abs(retest_extreme − boundary)` | price |
| `retest_depth_atr` | `retest_depth_price / atr14` | ATR |
| `entry_extent_beyond_boundary_price` | `abs(confirm_close − boundary)` | price |
| `entry_extent_beyond_boundary_atr` | `entry_extent_beyond_boundary_price / atr14` | ATR |
| `confirmation_margin_price` | `abs(confirm_close − minor_swing_ref)` | price |
| `confirmation_margin_atr` | `confirmation_margin_price / atr14` | ATR |
| `stop_distance_price` | `abs(entry_price − stop_loss)` | price |
| `stop_distance_atr` | `stop_distance_price / atr14` | ATR |
| `rr_planned` | passthrough of emitted `rr_planned` | ratio (currently constant = `rr_target`) |

Naming is canonical (raw `_price` + normalized `_atr`); no aliases. `confirm_close` is
the engine's confirmation/entry close, so the extent beyond the boundary is named
`entry_extent_beyond_boundary_*` — **not** "breakout_extent", because the raw breakout-
bar magnitude is discarded by the engine (see UNAVAILABLE below).

## UNAVAILABLE facts (the engine discards these — never fabricated)
`breakout_bar_extent_atr` (breakout-bar magnitude computed only as a boolean, line 805),
`setup_age_bars` (engine-internal, not emitted), `trend_health_counts` / `pivot_counts`
(health is audit-only, not in the instruction). Exposing any would require changing the
FROZEN engine — out of scope. `trade_score` is always None.

## Hard-gate vs continuous-fact distinction
All facts above are CONTINUOUS QUALITY FACTS. Hard-gate outcomes remain **separate
absolute gates**, never turned into numeric quality: news block, stale data/account, RR
below minimum, trend misalignment/neutral, WEAK trend health, invalid geometry, FTMO/
account/bridge/session/weekend blocks. A news block is a block, not "−20 points."

## Persistence & immutability
No new persistence record is added: each fact set is a pure deterministic function of the
**immutable** authorized instruction (already durably persisted by `signal_id` in the
bridge). Therefore one `signal_id` → one immutable fact set by construction; retry,
restart, HELD, reconciliation, and management never change it (they never change the
instruction's `evidence_summary`). Observational quality facts do **not** participate in
`signal_id` (exactly-once identity intact).

## Candidate vs executed-trade policy
Facts are extracted per authorized instruction (compliance-passed, written). `quality_dataset`
joins realized `outcome_r` from the canonical `execution_outcome` fact by `signal_id`:
`closed=False`/`outcome_r=None` for a written-but-unexecuted signal (a **candidate
observation**, never phantom P&L); `closed=True`/`outcome_r=R` once the trade closes. R is
appended by the join; it never rewrites the quality facts.

## Dataset shape (`quality_dataset`)
`signal_id, symbol, session_id, direction, strategy_version, generated_timestamp,
quality_fact_version, <continuous facts + _atr>, rr_planned, atr14, trade_score(=None),
outcome_r(None until closed), closed(bool)`.

## Research integration (PR-3M)
Research may correlate each fact with realized R, build distributions, and compare
winners/losers/sessions/symbols — reusing canonical calculators. It must NOT authorize/
size/threshold trades. No score bins are created; no predictive power is claimed.

## No-risk-coupling rule
No quality fact feeds `risk_fraction`, `allowable_volume`, monetary risk, capacity, SL,
TP, trailing, or break-even. **PR-3J (`compliance/sizing.py`) remains the sole lot-size
authority.**

## Criteria before a FUTURE score-model PR (do NOT proceed merely because facts exist)
Sufficient sample size; a stable (ideally monotonic) fact↔realized-R relationship where
claimed; out-of-sample validation; no session/symbol confounding; component independence
/ limited multicollinearity (note several facts share the OR/ATR axis); no lookahead;
stable definitions across `quality_fact_version`. A score model also requires the
separately-authorized product decisions in `SESSION_EDGE_SCORE_MODEL_DESIGN_REQUIRED.md`.
