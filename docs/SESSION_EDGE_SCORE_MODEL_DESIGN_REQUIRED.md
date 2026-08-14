# Session Edge — Trade-Score Model: DESIGN REQUIRES PRODUCT SPECIFICATION (PR-3O)

Status: **IMPLEMENTATION BLOCKED — SCORE MODEL DESIGN REQUIRES PRODUCT SPECIFICATION.**

PR-3O was authorized to implement a canonical 0–100 trade score (and to adopt a 70
minimum). A read-only audit of the frozen engine proves the score **cannot be built
from the facts the engine emits today** without either double-counting a single geometry
axis or inventing new facts (which would require changing the FROZEN engine and a
product decision on quality semantics). Per the PR's STOP condition, no score was
fabricated and no production score code was added.

This extends PR-3N (no score exists) with the concrete reason a score is not yet
*derivable* and the exact decisions/facts required to make it derivable.

## Why the emitted facts are insufficient (source-proven)

The engine (`run_dir/code/signal_engine.py`) is a deterministic all-gates-pass emitter
(spec §8.3). At emission (`build_instruction`, evidence `evidence_summary` +
`numeric_evidence`) the candidate facts split as follows:

### Hard-gated to CONSTANTS at emission → carry no scoring information
- **`rr_planned` ≡ `rr_target` (2.0).** `tgt = entry ± rr_target·stop_dist`, so
  `planned_rr = |tgt−entry|/stop_dist = rr_target` exactly (lines 910–911). The
  `min_rr` gate always passes; zero variance.
- **`trend_d1` and `trend_h4`.** Arming requires `combined_trend` BULLISH/BEARISH,
  which is BULLISH only if **both** H4 and D1 are BULLISH (else NEUTRAL) (lines 420–426),
  gated at 793–796 and re-gated every bar (830–835). Emitted candidates always have
  `trend_d1 == trend_h4 == direction` — no information beyond `direction`.
- **Trend health.** Both H4 and D1 health must be "OK" to arm (798–802); WEAK blocks.
  Health is not even carried into the emitted instruction (audit-only).
- **`confidence` = 1.0** (hardcoded, line 1020); **`risk_fraction`** = config constant.
- Breakout confirmation, retest-held, minor-swing confirmation, news eligibility — all
  boolean pass/fail gates; a passing candidate carries only "passed."

### VARYING facts collapse to ONE correlated axis + a raw scale
The facts that do vary among emitted candidates — `range_high`/`range_low` (OR width),
`boundary`, `retest_extreme`, `minor_swing_ref`, `confirm_close`(=`entry_price`),
`stop_basis`(=`stop_lvl`), `stop_distance`, `atr14` — are all **prices/distances of one
OR-plus-retest geometry** plus the raw ATR scale:
- `stop_distance = entry − min(retest_extreme, boundary) + stop_pad(atr)` (lines 893/895);
  `stop_basis` is that minus the pad; `take_profit = entry + rr_target·stop_distance` —
  algebraic transforms, not independent facts.
- `atr14` is the common denominator baked into every gate (buffer, retest_tol, stop_pad,
  width_atr), so ATR-normalizing any geometry fact just reproduces the same ratio.

Net independent axes ≈ **one** (OR/retest geometry in ATR units). A 4–6 component
independent score is not available.

### The two signals that COULD be independent are discarded
- **Breakout extent beyond the boundary in ATR units** — computed only as the boolean
  `c[i] > rh + buffer` (line 805) and thrown away; the magnitude is never stored.
- **Confirmation margin `entry − minor_swing_ref` in ATR units** — computed only as the
  boolean `c[i] > ref` (line 877) and thrown away.
- **`width_atr = (rh−rl)/atr`** — computed for gating (line 665) but never emitted.

## Decisions / facts required before a score can be implemented

A future, source-authorized change (with an explicit engine/`strategy_version` bump, so
exactly-once identity and P-1 parity stay intact) must supply BOTH new independent
evidence facts AND the product quality semantics:

| # | Required decision / fact | Why it is required |
|---|---|---|
| 1 | **Emit graded quality facts** (product + versioned engine change): breakout extent/ATR, confirmation margin/ATR, retest depth/ATR, OR width/ATR — the magnitudes the engine currently discards. | Without ≥3–4 genuinely independent continuous facts, any multi-component score double-counts the single OR/ATR axis. |
| 2 | **Quality DIRECTION for each fact** ("higher = better"?). Is a larger breakout stronger or over-extended? Is a deeper retest better or a failure risk? | The source establishes NO quality direction; assigning one is a subjective product decision, forbidden without authority. |
| 3 | **Score range** (0–100 to match cohort bands, or re-spec bands). | Cohorts are defined 70–74…95–100. |
| 4 | **Component weights summing to 100** with documented rationale. | "No magic unexplained weights"; must be product-set, not invented. |
| 5 | **Hard-gate vs score classification** — confirm RR/trend/health/news/FTMO/session/geometry remain absolute gates never compensated by score. | Preserve safety authority. |
| 6 | **Minimum threshold = 70** adoption (measurement) and, separately, whether it becomes an entry gate (policy PR). | Keep measurement and policy separate. |
| 7 | **Freeze timing** (at candidate generation, pre-compliance) + `score_model_version`. | Immutability + cohort comparability across model versions. |
| 8 | **Session/symbol policy** — one shared model (matches the single ORB methodology) unless facts differ structurally by session/pair. | v1 must not introduce session/pair-specific weights without evidence. |
| 9 | **Missing-fact policy** — fail closed vs UNAVAILABLE per component. | Never substitute default/average/previous points. |
| 10 | **Calibration disclaimer** — weights are an initial HYPOTHESIS requiring PR-3M forward validation, not proven alpha. | Do not claim 95 > 75 empirically until evidence exists. |

## Unchanged authorities and boundaries (this PR changed no production code)

- **No score-based sizing** and **no score-based entry threshold** were implemented.
- **PR-3J (`compliance/sizing.py::allowable_volume`) remains the sole volume/lot-size
  authority.** The only permitted future path: `score → risk-tier policy → permitted
  risk_fraction → PR-3J sizing → volume → compliance recomputation → EA verbatim`.
- Score cohorts remain owned solely by `research/lifecycle.py::cohort_of` (dormant /
  UNAVAILABLE until a score fact exists). No duplicate score/threshold/cohort authority.
- The frozen engine (ORB/trend/breakout/retest math), M12/M13, news, FTMO, H6, PR-3L,
  M1/G-1/H5/F-3, and EA behavior are untouched.
