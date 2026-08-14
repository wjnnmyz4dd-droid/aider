"""Observational setup-quality fact extraction (PR-3P). MEASUREMENT ONLY.

The ONE observational owner that NORMALIZES continuous setup-quality facts from the
values the frozen engine ALREADY emits in an authorized instruction's
``evidence_summary`` (+ the instruction's own entry/stop). It is a PURE, deterministic
function of an immutable instruction dict: it reads NO bars, calls NO engine, recomputes
NO strategy state, and touches NO broker. It never authorizes / sizes / blocks a trade,
computes a score, or applies a threshold — it changes no trading behavior whatsoever.

Only facts derivable by pure arithmetic from already-emitted evidence are exposed. Facts
the engine computes as booleans and DISCARDS (the raw breakout-bar magnitude, setup age,
trend-health / pivot counts) remain UNAVAILABLE and are NEVER fabricated. Hard-gate
outcomes (news / RR / trend / health / stale-data) are NOT turned into numeric quality —
they remain separate absolute gates owned elsewhere.

There is NO trade score here (PR-3O remains blocked): this only measures continuous
facts so a FUTURE, separately-authorized score-model PR can be designed on evidence.
"""

from __future__ import annotations

import math

QUALITY_FACT_VERSION = "session_edge_quality.v1"

# Facts the frozen engine reduces to booleans / keeps audit-only and DISCARDS from the
# emitted instruction — not derivable here without changing the engine. Surfaced as
# UNAVAILABLE (None), never fabricated.
UNAVAILABLE_FACTS = ("breakout_bar_extent_atr", "setup_age_bars",
                     "trend_health_counts", "pivot_counts")

# Continuous quality facts this module owns (canonical names; price + ATR-normalized).
CONTINUOUS_FACTS = (
    "range_width_price", "range_width_atr",
    "retest_depth_price", "retest_depth_atr",
    "entry_extent_beyond_boundary_price", "entry_extent_beyond_boundary_atr",
    "confirmation_margin_price", "confirmation_margin_atr",
    "stop_distance_price", "stop_distance_atr",
    "rr_planned",
)


def _num(x):
    """Finite float or None (rejects bool / NaN / Inf / non-numeric) — fail closed."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x) if math.isfinite(x) else None


def _norm(price, atr):
    """ATR-normalize a price distance. None (UNAVAILABLE) if price/ATR absent or ATR<=0
    — never a guessed denominator, never divide-by-zero."""
    if price is None or atr is None or atr <= 0:
        return None
    return price / atr


def extract(instruction):
    """Pure extraction of continuous quality facts from ONE authorized instruction.

    Returns a dict with ``quality_fact_version`` + identity (signal_id/symbol/session/
    direction/strategy_version/generated_timestamp) + the continuous facts (None where a
    source value is absent) + the explicitly-UNAVAILABLE facts + ``trade_score=None``
    (no score exists). Deterministic and independent of dict key ordering. Returns None
    only if ``instruction`` is not a dict."""
    if not isinstance(instruction, dict):
        return None
    ev = instruction.get("evidence_summary")
    ev = ev if isinstance(ev, dict) else {}

    atr = _num(ev.get("atr14"))
    if atr is not None and atr <= 0:
        atr = None                      # non-positive ATR is not a usable denominator;
                                        # surface it as UNAVAILABLE for a self-consistent
                                        # record (all _atr facts already fail closed).
    boundary = _num(ev.get("boundary"))
    retest = _num(ev.get("retest_extreme"))
    rhigh = _num(ev.get("range_high"))
    rlow = _num(ev.get("range_low"))
    confirm = _num(ev.get("confirm_close"))
    swing = _num(ev.get("minor_swing_ref"))
    entry = _num(instruction.get("entry_price"))
    stop = _num(instruction.get("stop_loss"))

    # magnitude (like every other _price fact): the OR width is non-negative by
    # engine contract (range_high >= range_low); abs() keeps it a magnitude even for
    # a malformed non-engine dict, so no _price fact can ever go negative.
    range_width_price = (abs(rhigh - rlow) if (rhigh is not None and rlow is not None) else None)
    retest_depth_price = (abs(retest - boundary)
                          if (retest is not None and boundary is not None) else None)
    entry_ext_price = (abs(confirm - boundary)
                       if (confirm is not None and boundary is not None) else None)
    conf_margin_price = (abs(confirm - swing)
                         if (confirm is not None and swing is not None) else None)
    stop_dist_price = (abs(entry - stop)
                       if (entry is not None and stop is not None) else None)

    out = {
        "quality_fact_version": QUALITY_FACT_VERSION,
        "signal_id": instruction.get("signal_id"),
        "symbol": instruction.get("symbol"),
        "session_id": instruction.get("session_id"),
        "direction": instruction.get("direction"),
        "strategy_version": instruction.get("strategy_version"),
        "generated_timestamp": instruction.get("generated_timestamp"),
        "atr14": atr,
        # continuous quality facts (None = UNAVAILABLE; never fabricated)
        "range_width_price": range_width_price,
        "range_width_atr": _norm(range_width_price, atr),
        "retest_depth_price": retest_depth_price,
        "retest_depth_atr": _norm(retest_depth_price, atr),
        # NOTE: the engine discards the raw breakout-bar close; this is the CONFIRMATION/
        # entry close's distance beyond the OR boundary (honest name, not "breakout").
        "entry_extent_beyond_boundary_price": entry_ext_price,
        "entry_extent_beyond_boundary_atr": _norm(entry_ext_price, atr),
        "confirmation_margin_price": conf_margin_price,
        "confirmation_margin_atr": _norm(conf_margin_price, atr),
        "stop_distance_price": stop_dist_price,
        "stop_distance_atr": _norm(stop_dist_price, atr),
        "rr_planned": _num(ev.get("rr_planned")),   # emitted but currently constant (=rr_target)
        # measurement only: no score exists (PR-3O blocked)
        "trade_score": None,
    }
    for k in UNAVAILABLE_FACTS:                      # engine-discarded facts stay UNAVAILABLE
        out[k] = None
    return out
