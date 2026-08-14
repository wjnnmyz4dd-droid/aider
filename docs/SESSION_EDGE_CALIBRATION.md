# Session Edge — Quality-Factor Validation & Score-Model Calibration (PR-3Q)

Status: **RESEARCH / VALIDATION ONLY.** Implements **no live trade score**, **no 70
gate**, **no score-based risk or lot sizing**, and changes **no trading behaviour**
(all code is in `research/`; no trading module imports it). Its job is to answer one
question with evidence:

> Can the PR-3P quality facts support a defensible, stable, monotonic 0–100 Session
> Edge trade-quality score?

## Decision (this repository, today)

**DECISION D — NO REALIZED DATASET AVAILABLE — CALIBRATION CANNOT BEGIN.**

The repository contains the full calibration machinery but **zero** realized
outcome data: the canonical `execution_outcome` fact is written at runtime by
`manage.outcome.OutcomeReconciler` into a runtime `MemoryStore` (a `runtime_dir`,
not committed). No `execution_outcome` records, no `memory/raw` store, and no trade
fixtures are committed (only `run_dir/config.json`). With **0 closed trades** there
is nothing to calibrate. This is the expected, honest result — Session Edge has not
yet earned the right to score-based sizing, and no score was manufactured to pretend
otherwise.

PR-3Q therefore delivers the machinery so that when real demo/live outcomes are
collected, calibration runs with **no analytics rewrite**: point it at the
MemoryStore and the accumulated authorized instructions.

## Canonical owner & non-duplication

`research/calibration.py` is the ONE calibration owner. It delegates every owned
calculation to its single owner and adds only analysis math nobody owns yet:

| Concern | Single owner (reused, never re-derived) |
|---|---|
| setup-quality facts | `research.quality_facts.extract` |
| per-signal realized R | `manage.outcome` (produced) via `research.lifecycle.quality_dataset` |
| expectancy / profit factor / win rate / drawdown / equity | `research.portfolio` |
| score cohort classification | `research.lifecycle.cohort_of` |
| percentile | `research.montecarlo._percentile` |
| provenance / git head / strategy version | `research.provenance` |
| lot sizing | `compliance.sizing.allowable_volume` (untouched) |

**New analysis this module owns** (no prior owner): Pearson & Spearman correlation,
tie-corrected ranks, quantile binning, univariate factor statistics, monotonicity
classification, cross-stratum stability, chronological (no-shuffle) OOS split,
robustness perturbation, sample-size classification, and the A/B/C/D decision.

`analysis_version = "session_edge_calibration.v1"`.

## Facts analyzed

The PR-3P continuous facts (raw `_price` + ATR-normalized `_atr`): `range_width`,
`retest_depth`, `entry_extent_beyond_boundary`, `confirmation_margin`,
`stop_distance`, plus `rr_planned`. **Raw vs normalized (§G):** the ATR-normalized
variants are the cross-symbol-comparable candidates; the raw `_price` variants are
retained for provenance and the raw-vs-normalized comparison and are **not** deleted.
Which variants survive into a future model is an evidence question the machinery
measures — it is not assumed. Explicitly UNAVAILABLE (engine-discarded, never
fabricated): raw breakout-bar magnitude, `setup_age_bars`, trend-health graded
counts, pivot-strength counts.

## Sample-size gate (transparent — not a magic universal threshold)

Evidence-readiness bands from the closed-trade count (constants in
`calibration.py`, versioned with `analysis_version`):

| Band | Closed trades | Meaning |
|---|---|---|
| `INSUFFICIENT` | `< 30` | Every quantile/stratum bucket is a handful; any "relationship" is one or two trades. |
| `EXPLORATORY` | `30 – 199` | Relationships can be *observed and described* but the chronological OOS split leaves windows too thin to *validate*. |
| `CALIBRATION-CANDIDATE` | `≥ 200` | Stratified, out-of-sample, robustness-checked calibration becomes defensible. |

These cut points are heuristic and documented so they can be revised transparently.
Per-statement minimums also apply: ≥8 finite (fact, R) pairs before any univariate
statement, ≥20 before a monotonicity classification.

## Method (per factor, once data exists)

- **Univariate (§H):** count, missing, mean/median/stdev/min/max, p25/p50/p75,
  Pearson & Spearman vs realized R, and per-quantile mean R / median R / win rate /
  profit factor via the **canonical** `portfolio` calculators.
- **Monotonicity (§I):** `POSITIVE / NEGATIVE / NON-MONOTONIC / FLAT / INSUFFICIENT`.
  `POSITIVE`/`NEGATIVE` require the Spearman sign **and** a per-quantile mean-R bucket
  trend of the **same** sign; a non-ordered bucket trend (U-shaped, inverted-U, one
  reversal) is `NON-MONOTONIC`, never coerced into "higher = better" from the raw rank
  sign alone.
- **Correlation / redundancy (§J–K):** pairwise Pearson + Spearman; pairs above a
  |0.9| threshold flagged so two correlated measurements never get independent full
  weight. Interpretability over fitted performance (§AA — no ML, no boosted trees).
- **Stability (§L–N):** Spearman sign within each session / symbol / direction
  stratum; sign reversals flagged. This PR builds no session- or direction-specific
  model.
- **Time / OOS (§O–P):** a strictly **chronological** split (never shuffled) into an
  earlier calibration window and a later validation window, ordered by **true UTC
  instant** via the canonical `bridge.serialize.parse_iso` (so timezone-offset variants
  never mis-order and no future row leaks into the earlier window); rows whose timestamp
  is missing/unparseable are excluded (fail closed). OOS relationships are reported
  separately and marked `UNVALIDATED` when the later window is too thin.
- **Robustness (§Q):** does a factor's Spearman sign survive removing the single
  best and worst trade? A relationship that vanishes when one trade is removed is
  flagged not-robust.

## No score, no threshold, no risk coupling

- **No proposed score model** is produced unless the evidence is
  `CALIBRATION-CANDIDATE` **and** a model survives the stability/OOS/robustness
  checks. With the current dataset that is impossible, so `proposed_score_model` is
  `None` — **no fake weights** (§V), no forced 100 points, no forced Decision A.
- The **70 threshold** (`SCORE_MIN_QUALIFYING`) is a predeclared product hypothesis,
  **not activated**. `threshold_retrospective` can, once a score exists, split closed
  trades at 70 (score exactly 70 retained) and compare **canonical** retained-vs-
  removed metrics without mutating the trades or creating a live gate. It reports
  `UNAVAILABLE` while no score exists — no score is invented to make 70 look good
  (§X, no threshold search).
- **Risk tiers (§Y–Z):** observational only. A future score/risk hypothesis is
  "ready" only if risk-adjusted performance improves **reasonably monotonically**
  across ascending score cohorts (70-74 → 95-100). If 70-74 materially outperforms
  95-100, the hypothesis is **not** ready. No risk percentages are assigned.
- **No lot coupling (§AI):** no calibration output feeds `risk_fraction`,
  `allowable_volume`, monetary risk, SL, TP, trailing, or break-even. **PR-3J
  (`compliance/sizing.py`) remains the sole lot-size authority.**

## Version isolation (§AF)

Reports record the `quality_fact_version` distribution. Incompatible versions are
**never silently pooled**: if closed trades carry more than one version and none is
pinned, factor analysis is **skipped** (`version_mixing =
MULTIPLE_VERSIONS_NOT_POOLED`) rather than mixing definitions.

## Provenance (§AE)

Every report embeds a `research.provenance.ExperimentRecord`: git commit, strategy
version, `quality_fact_version`, dataset id, `analysis_version`, closed-trade count,
sample-size class, and the **injected** generation timestamp (no wall clock).

## Synthetic-data rule (§AB)

Deterministic fixtures may exercise the math, joins, binning, OOS mechanics,
missing-data behaviour, and duplicate prevention. Synthetic data may **never** be
presented as evidence of predictive edge, factor significance, 70-threshold
effectiveness, or future profitability. The test suite uses synthetic fixtures for
mechanics only and labels them as such.

## Decision states (§AO)

- **A** — evidence sufficient, a defensible model survived stability/OOS. *(Never
  forced.)*
- **B** — exploratory; continue data collection.
- **C** — a calibration-sized dataset shows factors fail to be useful/stable.
- **D** — machinery present, **no realized outcome data**. ← current state.

## What is needed to progress past D

Accumulate real (demo-first, per the standing FOREX/DEMO/no-AI-authority
constraints) `execution_outcome` records via the live/demo `OutcomeReconciler`
path, keyed by `signal_id`, alongside the authorized instructions. Re-run
`calibration.calibration_report(instructions, memory=…, timestamp=…)`. No analytics
rewrite is required.
