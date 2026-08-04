"""Liquidity Agent (LLM-eligible; advisory) — Phase 4B live behavior.

Identifies liquidity structure from CLOSED bars only (equal highs/lows, prior-
session extremes, liquidity pools/stop clusters, completed sweeps, failed
breakouts, breakout-trap risk, retest quality vs nearby liquidity) and emits a
structured FAVORABLE / CAUTION / AVOID rating mapped onto the one canonical
scale. It consumes strategy swing points (never recomputes pivots), never creates
direction, never qualifies a setup by itself, never replaces the strategy retest
rule, and frames any statement about stops/pools as evidence-based INFERENCE.

Live computation runs when a closed-bar bundle is supplied; otherwise the agent
falls back to explicitly-provided advisory flags (deterministic either way).
"""

from __future__ import annotations

from ..base import Agent
from ..contract import Assessment, LiquidityRating, ReasonCode
from . import liquidity_calc as LC

MIN_BARS = 20


class LiquidityAgent(Agent):
    agent_id = "liquidity"
    agent_version = "0.2.0"
    uses_llm = True

    def _assess(self, request, context, now):
        liq = (context or {}).get("liquidity") or {}
        if liq.get("bars") is not None:
            out = self._assess_live(liq, context, now)
        else:
            out = self._assess_from_flags(liq, context)
        if self.llm is not None:
            resp = self.llm.summarize(
                {"role": "liquidity", "rating": out["evidence"].get("liquidity_rating"),
                 "sweep": out["evidence"].get("sweep_state")},
                prompt_version="liquidity.v2")
            if resp is not None and isinstance(getattr(resp, "text", None), str) \
                    and resp.model_id and resp.prompt_version:
                out["evidence"]["nl_summary"] = resp.text
                out["model_id"] = resp.model_id
                out["prompt_version"] = resp.prompt_version
                out["evidence"]["llm_validation"] = "OK"
            else:
                out["evidence"]["llm_validation"] = "REJECTED"
        return out

    # -- live, closed-bar computation --------------------------------------
    def _assess_live(self, liq, context, now):
        bars = LC.norm_bars(liq.get("bars"))
        pip = float(liq.get("pip_size", 0.0001))
        tol = float(liq.get("tolerance_pips", 2.0)) * pip
        # stale / insufficient guards (fail closed)
        if liq.get("stale") is True:
            return self._avoid([ReasonCode.LIQUIDITY_DATA_STALE], ["fresh_bars"])
        if len(bars) < MIN_BARS:
            return self._insufficient(["bars(>=%d)" % MIN_BARS])

        price = bars[-1][4]                       # last CLOSED bar close
        candidate = liq.get("candidate") or {}
        direction = candidate.get("direction")    # CONSUMED, never created
        entry = candidate.get("entry"); target = candidate.get("target")

        # liquidity pools are clusters of LOCAL extrema (not every bar's high/low)
        eq_highs = LC.equal_levels(LC.local_peaks(bars), tol)
        eq_lows = LC.equal_levels(LC.local_troughs(bars), tol)
        ps_high, ps_low = LC.prior_session_extremes(liq.get("prior_session_bars"))

        # consume strategy swing points (do NOT recompute pivots)
        swings = liq.get("strategy_swings") or {}
        swing_highs = list(swings.get("highs", []))
        swing_lows = list(swings.get("lows", []))

        up_levels = [lv for lv, _ in eq_highs] + swing_highs + ([ps_high] if ps_high else [])
        dn_levels = [lv for lv, _ in eq_lows] + swing_lows + ([ps_low] if ps_low else [])
        all_levels = up_levels + dn_levels
        liq_above, liq_below = LC.split_above_below(all_levels, price)
        _, nearest_dist = LC.nearest(all_levels, price)
        nearest_pips = round(nearest_dist / pip, 2) if nearest_dist is not None else None

        # sweeps / failed breakouts over the pools themselves (price-independent)
        sweep_state = "NONE"
        failed = False
        for lv in up_levels:
            s = LC.detect_sweep(bars, lv, "above", tol)
            if s == "CONFIRMED":
                sweep_state = "CONFIRMED"
                failed = failed or LC.failed_breakout(bars, lv, "above", tol)
                break
            if s == "UNCONFIRMED" and sweep_state == "NONE":
                sweep_state = "UNCONFIRMED"
        if sweep_state != "CONFIRMED":
            for lv in dn_levels:
                s = LC.detect_sweep(bars, lv, "below", tol)
                if s == "CONFIRMED":
                    sweep_state = "CONFIRMED"
                    failed = failed or LC.failed_breakout(bars, lv, "below", tol)
                    break
                if s == "UNCONFIRMED" and sweep_state == "NONE":
                    sweep_state = "UNCONFIRMED"

        # pool relative to the candidate (behind entry = trap risk; near target = fuel)
        pool_behind_entry = pool_near_target = False
        if entry is not None and direction:
            behind = liq_below if str(direction).upper() in ("LONG", "BULLISH") else liq_above
            if behind is not None and abs(behind - entry) <= 5 * tol:
                pool_behind_entry = True
        if target is not None:
            _, dt = LC.nearest(all_levels, target)
            pool_near_target = dt is not None and dt <= 5 * tol

        trap_risk = bool(failed or pool_behind_entry)
        retest_q = self._retest_quality(liq, price, entry, tol, pool_behind_entry)

        # rating (deterministic)
        reasons = []
        if trap_risk:
            rating = LiquidityRating.AVOID
            reasons.append(ReasonCode.LIQUIDITY_TRAP_RISK)
            if failed:
                reasons.append(ReasonCode.LIQUIDITY_FAILED_BREAKOUT)
            if pool_behind_entry:
                reasons.append(ReasonCode.LIQUIDITY_POOL_BEHIND_ENTRY)
        elif sweep_state == "CONFIRMED":
            rating = LiquidityRating.CAUTION
            reasons.append(ReasonCode.LIQUIDITY_SWEEP_CONFIRMED)
        elif retest_q == "WEAK":
            rating = LiquidityRating.CAUTION
            reasons.append(ReasonCode.LIQUIDITY_RETEST_WEAK)
        elif sweep_state == "UNCONFIRMED":
            rating = LiquidityRating.CAUTION
            reasons.append(ReasonCode.LIQUIDITY_SWEEP_UNCONFIRMED)
        else:
            rating = LiquidityRating.FAVORABLE
            reasons.append(ReasonCode.LIQUIDITY_FAVORABLE)
            if pool_near_target:
                reasons.append(ReasonCode.LIQUIDITY_POOL_NEAR_TARGET)

        conf = 0.75 if rating != LiquidityRating.CAUTION else 0.6
        return self._result(rating, conf, reasons, {
            "liquidity_rating": rating,
            "liquidity_above": liq_above, "liquidity_below": liq_below,
            "nearest_liquidity_distance_pips": nearest_pips,
            "sweep_state": sweep_state, "trap_risk": trap_risk,
            "retest_liquidity_quality": retest_q,
            "equal_highs": [lv for lv, _ in eq_highs],
            "equal_lows": [lv for lv, _ in eq_lows],
            "prior_session_high": ps_high, "prior_session_low": ps_low,
            "stop_cluster_inference": "evidence-based inference; unobservable stops not asserted",
            "closed_bars_only": True, "creates_direction": False,
        }, freshness={"market": (context or {}).get("market", {}).get("age_sec")})

    def _retest_quality(self, liq, price, entry, tol, pool_behind_entry):
        # explicit strategy-provided retest quality is authoritative context
        q = liq.get("retest_quality")
        if isinstance(q, str):
            return q.upper()
        if entry is None:
            return "NONE"
        if pool_behind_entry:
            return "WEAK"
        return "GOOD" if abs(price - entry) <= 10 * tol else "NONE"

    # -- legacy flag fallback (deterministic; no bars supplied) -------------
    def _assess_from_flags(self, liq, context):
        keys = ("equal_highs", "equal_lows", "prior_session_high", "prior_session_low",
                "swing_highs", "swing_lows", "liquidity_pools", "liquidity_sweeps",
                "failed_breakouts", "stop_clusters", "breakout_trap_risk", "retest_quality")
        missing = [k for k in keys if liq.get(k) is None]
        if len(missing) >= 6:
            return self._insufficient(missing)
        trap = bool(liq.get("breakout_trap_risk"))
        swept_against = bool(liq.get("liquidity_sweeps")) and liq.get("sweep_against_entry")
        retest = liq.get("retest_quality")
        if trap or swept_against or retest == "NONE":
            rating, reasons, conf = LiquidityRating.AVOID, [ReasonCode.LIQUIDITY_TRAP_RISK], 0.7
        elif retest == "WEAK":
            rating, reasons, conf = LiquidityRating.CAUTION, [ReasonCode.LIQUIDITY_RETEST_WEAK], 0.55
        else:
            rating, reasons, conf = LiquidityRating.FAVORABLE, [ReasonCode.LIQUIDITY_FAVORABLE], 0.75
        return self._result(rating, conf, reasons, {
            "liquidity_rating": rating, "sweep_state": "NONE", "trap_risk": trap,
            "retest_liquidity_quality": retest, "closed_bars_only": True,
            "creates_direction": False, "mode": "flag_fallback",
            "liquidity_above": None, "liquidity_below": None,
            "nearest_liquidity_distance_pips": None,
        }, freshness={}, missing=missing)

    # -- shared shapers -----------------------------------------------------
    def _result(self, rating, conf, reasons, evidence, freshness=None, missing=None):
        return {"assessment": LiquidityRating.TO_ASSESSMENT[rating],
                "confidence": conf, "evidence": evidence,
                "reason_codes": _dedup(reasons), "missing_inputs": missing or [],
                "data_freshness": freshness or {}}

    def _insufficient(self, missing):
        return {"assessment": Assessment.CAUTION, "confidence": 0.3,
                "evidence": {"liquidity_rating": LiquidityRating.CAUTION,
                             "creates_direction": False},
                "reason_codes": [ReasonCode.LIQUIDITY_DATA_INSUFFICIENT],
                "missing_inputs": missing, "data_freshness": {}}

    def _avoid(self, reasons, missing):
        return {"assessment": Assessment.BLOCK, "confidence": 0.0,
                "evidence": {"liquidity_rating": LiquidityRating.AVOID,
                             "fail_closed": True, "creates_direction": False},
                "reason_codes": reasons, "missing_inputs": missing, "data_freshness": {}}


def _dedup(seq):
    seen = set()
    return [x for x in seq if not (x in seen or seen.add(x))]
