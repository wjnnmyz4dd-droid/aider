"""Liquidity Agent (LLM-eligible; advisory).

Assesses liquidity structure: equal highs/lows, prior-session highs/lows, swing
points, liquidity pools, sweeps, failed breakouts, stop clusters, breakout-trap
risk, retest quality. Output is a structured FAVORABLE / CAUTION / AVOID rating
mapped onto the one canonical assessment scale. It never creates a trade
direction and never places trades.
"""

from __future__ import annotations

from ..base import Agent
from ..contract import Assessment, LiquidityRating, ReasonCode

OBSERVATION_KEYS = (
    "equal_highs", "equal_lows", "prior_session_high", "prior_session_low",
    "swing_highs", "swing_lows", "liquidity_pools", "liquidity_sweeps",
    "failed_breakouts", "stop_clusters", "breakout_trap_risk", "retest_quality",
)


class LiquidityAgent(Agent):
    agent_id = "liquidity"
    agent_version = "0.1.0"
    uses_llm = True

    def _assess(self, request, context, now):
        liq = (context or {}).get("liquidity") or {}
        evidence = {k: liq.get(k) for k in OBSERVATION_KEYS}
        missing = [k for k in OBSERVATION_KEYS if liq.get(k) is None]

        # deterministic rating from provided observation flags
        trap = bool(liq.get("breakout_trap_risk"))
        swept_against = bool(liq.get("liquidity_sweeps")) and liq.get("sweep_against_entry")
        retest = liq.get("retest_quality")            # GOOD / WEAK / NONE
        if len(missing) >= 6:
            rating, reasons, conf = (LiquidityRating.CAUTION,
                                     [ReasonCode.INSUFFICIENT_EVIDENCE], 0.3)
        elif trap or swept_against or retest == "NONE":
            rating, reasons, conf = (LiquidityRating.AVOID,
                                     [ReasonCode.OK], 0.7)
        elif retest == "WEAK":
            rating, reasons, conf = (LiquidityRating.CAUTION, [ReasonCode.OK], 0.55)
        else:
            rating, reasons, conf = (LiquidityRating.FAVORABLE, [ReasonCode.OK], 0.75)

        evidence["liquidity_rating"] = rating         # required structured label
        out = {
            "assessment": LiquidityRating.TO_ASSESSMENT[rating],
            "confidence": conf, "evidence": evidence, "reason_codes": reasons,
            "missing_inputs": missing,
            "data_freshness": {"market": ((context or {}).get("market") or {}).get("age_sec")},
        }
        if self.llm is not None:
            resp = self.llm.summarize(
                {"role": "liquidity", "rating": rating, "obs": evidence},
                prompt_version="liquidity.v1")
            out["evidence"]["nl_summary"] = resp.text
            out["model_id"] = resp.model_id
            out["prompt_version"] = resp.prompt_version
        return out
