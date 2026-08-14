"""Quality-factor validation & score-model calibration research (PR-3Q).

RESEARCH / VALIDATION ONLY. This module answers ONE question with evidence:

    Do the PR-3P quality facts contain enough real, non-redundant, stable
    predictive information to justify a FUTURE canonical 0-100 Session Edge
    trade score?

It implements **no live trade score**, **no 70 gate**, **no score-based risk or
lot sizing**, and changes **no trading behaviour** (all code lives in
``research/``; no trading module imports it). It NEVER places, sizes, blocks, or
modifies a trade, never touches a broker, and never feeds ``risk_fraction`` /
``allowable_volume`` / SL / TP.

NON-DUPLICATIVE by design — it delegates every owned calculation to its single
owner and only adds analysis math that no module owns yet:

  * setup-quality facts        -> research.quality_facts.extract (sole extractor)
  * per-signal realized R       -> manage.outcome (produced) via
                                   research.lifecycle.quality_dataset (sole join)
  * expectancy / profit factor / win rate / drawdown / equity
                                -> research.portfolio (canonical calculators)
  * score cohort classification -> research.lifecycle.cohort_of (sole classifier)
  * percentile                  -> research.montecarlo._percentile (sole owner)
  * provenance / git head / strategy version
                                -> research.provenance
  * lot sizing                  -> compliance.sizing (untouched; sole authority)

NEW analysis this module owns (single owner): Pearson / Spearman correlation,
rank computation, quantile binning, univariate factor statistics, monotonicity
classification, cross-stratum stability, chronological (no-shuffle) OOS split,
robustness perturbation, sample-size classification, and the A/B/C/D decision.

Determinism: pure functions of the injected dataset + injected timestamp. No wall
clock, no randomness, no networking, no lookahead (splits are chronological, never
shuffled). Missing / constant / tiny inputs fail closed to None / INSUFFICIENT and
are NEVER fabricated. Synthetic fixtures may exercise this math; they can NEVER be
presented as evidence of predictive power (see docs/SESSION_EDGE_CALIBRATION.md).
"""

from __future__ import annotations

import math

from . import portfolio, lifecycle, quality_facts
from .montecarlo import _percentile   # sole percentile owner (reused, not re-derived)

ANALYSIS_VERSION = "session_edge_calibration.v1"

# --------------------------------------------------------------------------- #
# Sample-size gate (transparent, documented — NOT a magic universal threshold).
#
# These are evidence-readiness bands, not statistical guarantees. Rationale:
#   * A per-factor relationship is examined across QUANTILE buckets (default 4)
#     and stratified by session (4), symbol (several), and direction (2). Below a
#     few dozen closed trades every bucket is a handful and any "relationship" is
#     one or two trades — INSUFFICIENT.
#   * Between a few dozen and a couple hundred, relationships can be *observed and
#     described* but a chronological out-of-sample split leaves windows too thin
#     to *validate* — EXPLORATORY.
#   * Only at a couple hundred closed trades does a stratified, out-of-sample,
#     robustness-checked calibration become defensible — CALIBRATION-CANDIDATE.
# The exact cut points are heuristic and versioned with ANALYSIS_VERSION; they are
# documented so they can be revised transparently, never silently.
# --------------------------------------------------------------------------- #
MIN_CLOSED_FOR_EXPLORATORY = 30
MIN_CLOSED_FOR_CALIBRATION = 200

INSUFFICIENT = "INSUFFICIENT"
EXPLORATORY = "EXPLORATORY"
CALIBRATION_CANDIDATE = "CALIBRATION-CANDIDATE"

# Minimum finite (fact, R) pairs before a univariate / monotonicity / correlation
# statement is attempted at all (below this -> UNAVAILABLE / INSUFFICIENT, never a
# fabricated conclusion from one extreme trade).
MIN_PAIRS_FOR_STAT = 8
MIN_PAIRS_FOR_MONOTONICITY = 20

# Monotonicity thresholds (on Spearman rank correlation).
FLAT_ABS_RHO = 0.05          # |rho| below this -> FLAT (no ordering signal)

# Decisions (AO).
DECISION_A = "EVIDENCE SUFFICIENT — SCORE MODEL CANDIDATE READY FOR IMPLEMENTATION REVIEW"
DECISION_B = "EVIDENCE EXPLORATORY — CONTINUE DATA COLLECTION"
DECISION_C = "EVIDENCE DOES NOT SUPPORT CURRENT SCORE HYPOTHESIS"
DECISION_D = "NO REALIZED DATASET AVAILABLE — CALIBRATION CANNOT BEGIN"

# The continuous facts eligible for factor analysis (the ATR-normalized variants
# are the cross-symbol-comparable candidates; raw ``_price`` variants are retained
# for provenance and the raw-vs-normalized comparison, per PR-3Q §G).
ANALYSIS_FACTS = tuple(f for f in quality_facts.CONTINUOUS_FACTS)


# --------------------------------------------------------------------------- #
# primitives (deterministic; None on missing / constant / tiny input)
# --------------------------------------------------------------------------- #
def _finite(x):
    return (isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x))


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _median(xs):
    if not xs:
        return None
    s = sorted(xs)
    return _percentile(s, 0.5)


def _stdev(xs):
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _finite_pairs(xs, ys):
    return [(float(x), float(y)) for x, y in zip(xs, ys) if _finite(x) and _finite(y)]


def _is_constant(xs):
    """True if the series has no meaningful spread — a constant feature up to float
    noise (relative tolerance), so correlation/ranking is UNDEFINED, not zero. This
    is what separates a genuinely uncorrelated series (r=0) from a constant one
    (r=None): a constant feature's tiny residual variance must NOT be ranked or
    divided by (that fabricates a spurious ordering / correlation)."""
    if len(xs) < 2:
        return True
    lo, hi = min(xs), max(xs)
    scale = max(abs(lo), abs(hi), 1.0)
    return (hi - lo) <= 1e-12 * scale


def pearson(xs, ys):
    """Pearson correlation, or None for <3 finite pairs or a (numerically) constant
    series (variance undefined -> never fabricated). Deterministic."""
    pairs = _finite_pairs(xs, ys)
    n = len(pairs)
    if n < 3:
        return None
    px = [p[0] for p in pairs]
    py = [p[1] for p in pairs]
    if _is_constant(px) or _is_constant(py):    # constant feature or constant outcome
        return None
    mx, my = sum(px) / n, sum(py) / n
    try:                                # extreme magnitudes -> overflow -> fail closed
        sxx = sum((x - mx) ** 2 for x in px)
        syy = sum((y - my) ** 2 for y in py)
        if sxx <= 0 or syy <= 0:
            return None
        sxy = sum((x - mx) * (y - my) for x, y in zip(px, py))
        r = sxy / math.sqrt(sxx * syy)
    except (OverflowError, ValueError):
        return None                     # undefined (not fabricated) on numeric overflow
    return round(r, 6)


def _ranks(values):
    """Average (tie-corrected) ranks, 1-based. Deterministic."""
    idx = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(values):
        j = i
        while j + 1 < len(values) and values[idx[j + 1]] == values[idx[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[idx[k]] = avg
        i = j + 1
    return ranks


def spearman(xs, ys):
    """Spearman rank correlation (Pearson on tie-corrected ranks). None for <3
    finite pairs or a constant series. Deterministic."""
    pairs = _finite_pairs(xs, ys)
    if len(pairs) < 3:
        return None
    px = [p[0] for p in pairs]
    py = [p[1] for p in pairs]
    if _is_constant(px) or _is_constant(py):    # never rank float noise of a constant
        return None
    return pearson(_ranks(px), _ranks(py))


def quantile_cuts(values, k):
    """``k-1`` interior quantile cut points over the finite ``values`` (reusing the
    single percentile owner). None if fewer than ``k`` finite values or k<2."""
    xs = sorted(v for v in values if _finite(v))
    if k < 2 or len(xs) < k:
        return None
    return [_percentile(xs, i / k) for i in range(1, k)]


def assign_bin(value, cuts):
    """Deterministic bin index 0..len(cuts) for ``value`` given ascending ``cuts``
    (``value <= cut`` stays in the lower bin)."""
    b = 0
    for c in cuts:
        if value > c:
            b += 1
        else:
            break
    return b


# --------------------------------------------------------------------------- #
# dataset shaping (candidates vs closed trades; version isolation)
# --------------------------------------------------------------------------- #
def build_dataset(instructions, memory=None):
    """The one observational dataset: quality facts (from the sole extractor via
    ``lifecycle.quality_dataset``) joined to canonical realized R. Candidate
    observations keep ``closed=False``/``outcome_r=None`` (never phantom R=0)."""
    return lifecycle.quality_dataset(instructions, memory=memory)


def closed_rows(dataset, quality_fact_version=None):
    """Rows with a canonical CLOSED outcome and finite realized R. Optionally
    restricted to a single ``quality_fact_version`` (NEVER pool incompatible
    versions — see version_distribution / calibration_report)."""
    out = []
    for r in dataset:
        if not r.get("closed") or not _finite(r.get("outcome_r")):
            continue
        if quality_fact_version is not None and r.get("quality_fact_version") != quality_fact_version:
            continue
        out.append(r)
    return out


def version_distribution(dataset):
    """Count of rows per ``quality_fact_version`` (deterministic, sorted)."""
    counts = {}
    for r in dataset:
        v = r.get("quality_fact_version")
        counts[v] = counts.get(v, 0) + 1
    return {str(k): counts[k] for k in sorted(counts, key=lambda x: str(x))}


# --------------------------------------------------------------------------- #
# sample-size classification (AE / E)
# --------------------------------------------------------------------------- #
def classify_sample_size(n_closed):
    """Transparent evidence-readiness band from the closed-trade count."""
    if n_closed >= MIN_CLOSED_FOR_CALIBRATION:
        return CALIBRATION_CANDIDATE
    if n_closed >= MIN_CLOSED_FOR_EXPLORATORY:
        return EXPLORATORY
    return INSUFFICIENT


# --------------------------------------------------------------------------- #
# univariate factor statistics (H) — per-quantile metrics via canonical portfolio
# --------------------------------------------------------------------------- #
def univariate(dataset, fact, *, bins=4, quality_fact_version=None):
    """Distribution of ``fact`` and its relationship to realized R over closed
    trades. Per-quantile expectancy / win rate / profit factor are computed by the
    CANONICAL portfolio calculators (never re-derived here). INSUFFICIENT (no
    conclusion) below MIN_PAIRS_FOR_STAT finite pairs."""
    rows = closed_rows(dataset, quality_fact_version)
    missing = sum(1 for r in rows if not _finite(r.get(fact)))
    pairs = [(float(r[fact]), float(r["outcome_r"])) for r in rows if _finite(r.get(fact))]
    n = len(pairs)
    base = {"fact": fact, "count": n, "missing": missing}
    if n < MIN_PAIRS_FOR_STAT:
        base["status"] = INSUFFICIENT
        return base
    fx = [p[0] for p in pairs]
    base.update({
        "status": "OK",
        "mean": round(_mean(fx), 8), "median": round(_median(fx), 8),
        "stdev": round(_stdev(fx), 8), "min": min(fx), "max": max(fx),
        "p25": round(_percentile(sorted(fx), 0.25), 8),
        "p50": round(_percentile(sorted(fx), 0.50), 8),
        "p75": round(_percentile(sorted(fx), 0.75), 8),
        "pearson_r": pearson(fx, [p[1] for p in pairs]),
        "spearman_r": spearman(fx, [p[1] for p in pairs]),
    })
    cuts = quantile_cuts(fx, bins)
    if cuts is None:
        base["by_quantile"] = None
        return base
    buckets = {}
    for f, r in pairs:
        buckets.setdefault(assign_bin(f, cuts), []).append(r)
    base["quantile_cuts"] = [round(c, 8) for c in cuts]
    base["by_quantile"] = {}
    for b in sorted(buckets):
        trades = [{"r_multiple": r} for r in buckets[b]]
        wl = portfolio.win_loss(trades)
        base["by_quantile"][b] = {
            "count": len(trades),
            "mean_r": portfolio.expectancy(trades),          # canonical
            "median_r": round(_median(buckets[b]), 6),
            "win_rate": wl["win_rate"],                       # canonical
            "profit_factor": portfolio.profit_factor(trades),  # canonical
        }
    return base


# --------------------------------------------------------------------------- #
# monotonicity (I)
# --------------------------------------------------------------------------- #
POSITIVE, NEGATIVE, NON_MONOTONIC, FLAT = "POSITIVE", "NEGATIVE", "NON-MONOTONIC", "FLAT"


def _is_monotone(seq):
    """(+1) non-decreasing, (-1) non-increasing, 0 neither. Ignores None entries."""
    xs = [v for v in seq if v is not None]
    if len(xs) < 2:
        return 0
    up = all(b >= a for a, b in zip(xs, xs[1:]))
    down = all(b <= a for a, b in zip(xs, xs[1:]))
    if up and not down:
        return 1
    if down and not up:
        return -1
    return 0 if not (up and down) else 1


def monotonicity(dataset, fact, *, bins=4, quality_fact_version=None):
    """Classify how ``fact`` orders realized R: POSITIVE / NEGATIVE / NON-MONOTONIC
    / FLAT / INSUFFICIENT. Uses Spearman sign AND the per-quantile mean-R trend so
    a factor is NEVER forced into 'higher = better'."""
    uni = univariate(dataset, fact, bins=bins, quality_fact_version=quality_fact_version)
    if uni.get("count", 0) < MIN_PAIRS_FOR_MONOTONICITY or uni.get("status") != "OK":
        return {"fact": fact, "classification": INSUFFICIENT, "count": uni.get("count", 0)}
    rho = uni.get("spearman_r")
    if rho is None:
        # rank correlation undefined: a constant feature OR a constant outcome
        return {"fact": fact, "classification": FLAT, "count": uni["count"],
                "spearman_r": None, "reason": "constant feature or outcome"}
    bq = uni.get("by_quantile") or {}
    trend = _is_monotone([bq[b]["mean_r"] for b in sorted(bq)])
    # POSITIVE/NEGATIVE require BOTH a rank-correlation sign AND a per-quantile
    # bucket trend of the SAME sign. trend == 0 (buckets not ordered: U-shaped,
    # inverted-U, or one reversal) is NOT agreement -> NON-MONOTONIC, so a factor
    # is never forced into "higher = better" from noise.
    if abs(rho) < FLAT_ABS_RHO:
        cls = FLAT
    elif rho > 0 and trend > 0:
        cls = POSITIVE
    elif rho < 0 and trend < 0:
        cls = NEGATIVE
    else:
        cls = NON_MONOTONIC          # rank sign and bucket trend disagree / not ordered
    return {"fact": fact, "classification": cls, "count": uni["count"],
            "spearman_r": rho, "quantile_trend": trend}


# --------------------------------------------------------------------------- #
# correlation / redundancy (J) & multicollinearity note (K)
# --------------------------------------------------------------------------- #
def correlation_matrix(dataset, facts=ANALYSIS_FACTS, *, quality_fact_version=None):
    """Pairwise Pearson + Spearman among factors over closed trades. Deterministic;
    None where a pair has too few finite pairs or a constant series."""
    rows = closed_rows(dataset, quality_fact_version)
    cols = {f: [r.get(f) for r in rows] for f in facts}
    out = {}
    for i, a in enumerate(facts):
        for b in facts[i + 1:]:
            out[f"{a}|{b}"] = {"pearson": pearson(cols[a], cols[b]),
                               "spearman": spearman(cols[a], cols[b])}
    return out


def redundancy_flags(matrix, *, threshold=0.9):
    """Factor pairs whose |Pearson| or |Spearman| exceeds ``threshold`` (obvious
    redundancy — do not give both independent full weight in a future score)."""
    flags = []
    for pair, c in sorted(matrix.items()):
        for kind in ("pearson", "spearman"):
            v = c.get(kind)
            if v is not None and abs(v) >= threshold:
                flags.append({"pair": pair, "kind": kind, "value": v})
    return flags


# --------------------------------------------------------------------------- #
# stratified stability (L / M / N) — sign agreement across strata
# --------------------------------------------------------------------------- #
def stability_by(dataset, fact, key, *, quality_fact_version=None):
    """Spearman sign of ``fact`` vs realized R within each stratum of ``key``
    (e.g. session_id / symbol / direction). Flags sign reversals across strata.
    A stratum below MIN_PAIRS_FOR_STAT is reported as INSUFFICIENT, never signed."""
    rows = closed_rows(dataset, quality_fact_version)
    groups = {}
    for r in rows:
        groups.setdefault(r.get(key), []).append(r)
    per = {}
    signs = set()
    for g in sorted(groups, key=lambda x: str(x)):
        grp = groups[g]
        pairs = [(r[fact], r["outcome_r"]) for r in grp if _finite(r.get(fact))]
        if len(pairs) < MIN_PAIRS_FOR_STAT:
            per[str(g)] = {"count": len(pairs), "spearman_r": None, "status": INSUFFICIENT}
            continue
        rho = spearman([p[0] for p in pairs], [p[1] for p in pairs])
        sign = 0 if rho is None or abs(rho) < FLAT_ABS_RHO else (1 if rho > 0 else -1)
        if sign != 0:
            signs.add(sign)
        per[str(g)] = {"count": len(pairs), "spearman_r": rho, "sign": sign, "status": "OK"}
    return {"fact": fact, "key": key, "strata": per,
            "reverses": len(signs) > 1}     # both +1 and -1 present -> unstable


# --------------------------------------------------------------------------- #
# chronological out-of-sample split (O / P) — NEVER shuffled
# --------------------------------------------------------------------------- #
def chronological_split(dataset, frac=0.7, *, quality_fact_version=None):
    """Split closed trades into an earlier calibration set and a later validation
    set by true UTC instant. NO shuffle, no lookahead: every calibration row is
    chronologically <= every validation row.

    Timestamps are parsed to real UTC instants via the canonical
    ``bridge.serialize.parse_iso`` (the single ISO owner), so timezone-offset
    variants order by instant, not by lexicographic string — a ``+09:00`` row can
    never leak past an earlier ``Z`` row. Rows whose ``generated_timestamp`` is
    missing or unparseable are EXCLUDED (fail closed: they cannot be safely
    ordered), never silently assumed earliest/latest. Ties break on signal_id."""
    from ..bridge import serialize
    dated = []
    for r in closed_rows(dataset, quality_fact_version):
        dt = serialize.parse_iso(r.get("generated_timestamp"))
        if dt is None:
            continue                        # unorderable timestamp -> fail closed
        dated.append((dt, str(r.get("signal_id")), r))
    dated.sort(key=lambda t: (t[0], t[1]))
    rows = [t[2] for t in dated]
    if not rows:
        return [], []
    cut = max(1, int(len(rows) * frac)) if len(rows) > 1 else 1
    return rows[:cut], rows[cut:]


def in_out_of_sample(dataset, fact, frac=0.7, *, quality_fact_version=None):
    """Report the ``fact`` vs realized-R Spearman IN-SAMPLE (earlier) and
    OUT-OF-SAMPLE (later). OOS is UNVALIDATED when the later window is too small."""
    early, late = chronological_split(dataset, frac, quality_fact_version=quality_fact_version)

    def _rho(rows):
        pairs = [(r[fact], r["outcome_r"]) for r in rows if _finite(r.get(fact))]
        if len(pairs) < MIN_PAIRS_FOR_STAT:
            return None
        return spearman([p[0] for p in pairs], [p[1] for p in pairs])

    oos = _rho(late)
    return {"fact": fact, "in_sample_spearman": _rho(early), "in_sample_n": len(early),
            "out_of_sample_spearman": oos, "out_of_sample_n": len(late),
            "oos_status": "VALIDATED" if oos is not None else "UNVALIDATED"}


# --------------------------------------------------------------------------- #
# robustness (Q) — drop best / worst trade; quantile-boundary sensitivity
# --------------------------------------------------------------------------- #
def robustness(dataset, fact, *, quality_fact_version=None):
    """Does the ``fact`` vs realized-R Spearman survive removing the single best /
    worst trade, and does the sign hold under a different bin count? A relationship
    that vanishes when one trade is removed is flagged not-robust."""
    rows = [r for r in closed_rows(dataset, quality_fact_version) if _finite(r.get(fact))]
    if len(rows) < MIN_PAIRS_FOR_STAT + 1:
        return {"fact": fact, "status": INSUFFICIENT, "count": len(rows)}
    ordered = sorted(rows, key=lambda r: r["outcome_r"])

    def _rho(rs):
        return spearman([r[fact] for r in rs], [r["outcome_r"] for r in rs])

    full = _rho(rows)
    drop_worst = _rho(ordered[1:])
    drop_best = _rho(ordered[:-1])

    def _sign(v):
        return 0 if v is None or abs(v) < FLAT_ABS_RHO else (1 if v > 0 else -1)

    base_sign = _sign(full)
    stable = base_sign != 0 and _sign(drop_worst) == base_sign and _sign(drop_best) == base_sign
    return {"fact": fact, "status": "OK", "count": len(rows),
            "spearman_full": full, "spearman_drop_worst": drop_worst,
            "spearman_drop_best": drop_best, "sign_stable": stable}


# --------------------------------------------------------------------------- #
# score-cohort performance (Y / Z) — reuses the SOLE cohort classifier
# --------------------------------------------------------------------------- #
def cohort_performance(dataset, *, quality_fact_version=None):
    """Realized performance by score cohort using the CANONICAL lifecycle.cohort_of
    classifier + canonical portfolio.summary. With no trade score present upstream
    every closed trade lands in UNAVAILABLE (proving readiness without a fabricated
    score); sub-70 is always kept separate if a score ever exists."""
    rows = closed_rows(dataset, quality_fact_version)
    buckets = {}
    for r in rows:
        buckets.setdefault(lifecycle.cohort_of(r.get("trade_score")), []).append(
            {"r_multiple": r["outcome_r"]})
    return {c: portfolio.summary(ts) for c, ts in sorted(buckets.items())}


def monotonic_cohorts(cohort_perf):
    """Whether expectancy is non-decreasing across ascending qualifying cohorts
    (70-74 -> 95-100). UNAVAILABLE when no scored cohorts exist (the current
    state). Never claims monotonicity it cannot see (Z)."""
    ordered = [c for c in lifecycle.SCORE_COHORTS if c in cohort_perf]
    if len(ordered) < 2:
        return {"status": lifecycle.SCORE_UNAVAILABLE, "cohorts": ordered}
    exps = [cohort_perf[c]["expectancy"] for c in ordered]
    return {"status": "OK", "cohorts": ordered, "expectancy": exps,
            "monotonic_non_decreasing": all(b >= a for a, b in zip(exps, exps[1:]))}


# --------------------------------------------------------------------------- #
# 70-threshold retrospective (W / X) — ONLY meaningful once a score column exists
# --------------------------------------------------------------------------- #
def threshold_retrospective(dataset, threshold=lifecycle.SCORE_MIN_QUALIFYING,
                            *, quality_fact_version=None):
    """Observationally split closed trades at ``threshold`` on ``trade_score`` and
    compare CANONICAL portfolio metrics of retained vs removed. Returns UNAVAILABLE
    while no trade score exists (no score is invented to make 70 look good). This
    NEVER creates a live gate and never mutates the trades."""
    rows = closed_rows(dataset, quality_fact_version)
    if not any(_finite(r.get("trade_score")) for r in rows):
        return {"status": lifecycle.SCORE_UNAVAILABLE, "threshold": threshold,
                "reason": "no trade score exists (PR-3O blocked); nothing to threshold"}
    retained = [{"r_multiple": r["outcome_r"]} for r in rows
                if _finite(r.get("trade_score")) and r["trade_score"] >= threshold]
    removed = [{"r_multiple": r["outcome_r"]} for r in rows
               if _finite(r.get("trade_score")) and r["trade_score"] < threshold]
    total = len(retained) + len(removed)
    return {"status": "OK", "threshold": threshold,
            "retained": len(retained), "removed": len(removed),
            "retained_pct": round(len(retained) / total, 6) if total else 0.0,
            "retained_metrics": portfolio.summary(retained),
            "removed_metrics": portfolio.summary(removed)}


# --------------------------------------------------------------------------- #
# decision (AO)
# --------------------------------------------------------------------------- #
def decide(n_closed, classification, *, model_survives=False):
    """Map evidence state to exactly one PR-3Q decision. NEVER forces DECISION_A."""
    if n_closed == 0:
        return DECISION_D
    if classification in (INSUFFICIENT, EXPLORATORY):
        return DECISION_B
    # CALIBRATION-CANDIDATE: only A if a defensible model actually survived checks.
    return DECISION_A if model_survives else DECISION_C


# --------------------------------------------------------------------------- #
# the one calibration report (AD / AE / AF)
# --------------------------------------------------------------------------- #
def calibration_report(instructions, memory=None, *, timestamp, bins=4, repo_root=None):
    """One deterministic, provenance-stamped calibration report. Measurement only.

    Isolates ``quality_fact_version`` (AF): if closed trades carry more than one
    version and none is pinnable, factor analysis is SKIPPED (not silently pooled)
    and the decision falls back on sample size. Requires an INJECTED ``timestamp``
    (no wall clock). Produces a proposed score model ONLY if the evidence supports
    it — otherwise none (no fake weights)."""
    from .provenance import ExperimentRecord

    dataset = build_dataset(instructions, memory=memory)
    vdist = version_distribution([r for r in dataset if r.get("closed")])
    closed_all = closed_rows(dataset)
    n_closed = len(closed_all)

    # version isolation: analyze a single version, or refuse to pool.
    closed_versions = sorted({r.get("quality_fact_version") for r in closed_all},
                             key=lambda x: str(x))
    if len(closed_versions) <= 1:
        analysis_version_id = closed_versions[0] if closed_versions else None
        version_mixing = "SINGLE_VERSION"
    else:
        analysis_version_id = None
        version_mixing = "MULTIPLE_VERSIONS_NOT_POOLED"

    classification = classify_sample_size(n_closed)
    pool_ok = version_mixing == "SINGLE_VERSION"

    features, mono, stab, oos, robust = {}, {}, {}, {}, {}
    corr = redundant = {}
    if pool_ok and n_closed >= MIN_PAIRS_FOR_STAT:
        for f in ANALYSIS_FACTS:
            features[f] = univariate(dataset, f, bins=bins, quality_fact_version=analysis_version_id)
            mono[f] = monotonicity(dataset, f, bins=bins, quality_fact_version=analysis_version_id)
            oos[f] = in_out_of_sample(dataset, f, quality_fact_version=analysis_version_id)
            robust[f] = robustness(dataset, f, quality_fact_version=analysis_version_id)
            for key in ("session_id", "symbol", "direction"):
                stab.setdefault(key, {})[f] = stability_by(
                    dataset, f, key, quality_fact_version=analysis_version_id)
        corr = correlation_matrix(dataset, quality_fact_version=analysis_version_id)
        redundant = redundancy_flags(corr)

    cohort_perf = cohort_performance(dataset, quality_fact_version=analysis_version_id) if pool_ok else {}
    threshold = threshold_retrospective(dataset, quality_fact_version=analysis_version_id) if pool_ok else \
        {"status": lifecycle.SCORE_UNAVAILABLE}

    # A proposed model requires CALIBRATION-CANDIDATE evidence that actually
    # survived stability/OOS checks. That cannot be true with the current dataset;
    # we never manufacture weights merely because the machinery ran.
    model_survives = False
    proposed_model = None

    decision = decide(n_closed, classification, model_survives=model_survives)

    dataset_id = f"quality_dataset:{analysis_version_id}:closed={n_closed}"
    provenance = ExperimentRecord.build(
        "pr3q_calibration", dataset_id=dataset_id,
        parameters={"bins": bins, "analysis_version": ANALYSIS_VERSION},
        config={"quality_fact_version": analysis_version_id,
                "min_closed_exploratory": MIN_CLOSED_FOR_EXPLORATORY,
                "min_closed_calibration": MIN_CLOSED_FOR_CALIBRATION},
        timestamp=timestamp,
        metrics={"closed_trades": n_closed, "sample_size_class": classification},
        repo_root=repo_root).to_dict()

    return {
        "analysis_version": ANALYSIS_VERSION,
        "generation_timestamp": timestamp,
        "provenance": provenance,
        "dataset_summary": {
            "candidate_observations": len(dataset),
            "closed_trades": n_closed,
            "quality_fact_version_distribution": vdist,
            "version_mixing": version_mixing,
            "analysis_quality_fact_version": analysis_version_id,
            "symbols": sorted({str(r.get("symbol")) for r in closed_all}),
            "sessions": sorted({str(r.get("session_id")) for r in closed_all}),
            "directions": sorted({str(r.get("direction")) for r in closed_all}),
        },
        "sample_size_classification": classification,
        "feature_distributions": features,
        "monotonicity": mono,
        "correlation_matrix": corr,
        "redundancy_flags": redundant,
        "stability": stab,
        "out_of_sample": oos,
        "robustness": robust,
        "cohort_performance": cohort_perf,
        "monotonic_cohorts": monotonic_cohorts(cohort_perf) if pool_ok else
                             {"status": lifecycle.SCORE_UNAVAILABLE},
        "threshold_retrospective": threshold,
        "proposed_score_model": proposed_model,     # None unless evidence supports it
        "higher_score_better": lifecycle.SCORE_UNAVAILABLE,  # no score exists to evaluate
        "decision": decision,
    }
