"""Critic Agent (LLM-eligible; advisory adversary).

Argues AGAINST the proposed setup: late-trend risk, liquidity-trap risk, news
conflict, weak trend health, insufficient evidence. It CANNOT approve a trade —
it may only return CLEAR objection / CAUTION / BLOCK. Its verdict is derived
deterministically from the prior agents' structured outputs and supplied risk
flags; an optional LLM drafts the counter-argument text (provenance captured).
"""

from __future__ import annotations

from ..base import Agent
from ..contract import Assessment, ReasonCode


class CriticAgent(Agent):
    agent_id = "critic"
    agent_version = "0.1.0"
    uses_llm = True

    def _assess(self, request, context, now):
        priors = (context or {}).get("agent_results") or {}
        flags = (context or {}).get("critic_flags") or {}

        objections = []
        # escalate on any upstream objection or explicit risk flag
        for name in ("market_intelligence", "liquidity", "news_compliance", "risk"):
            res = priors.get(name)
            if res and res.get("assessment") == Assessment.BLOCK:
                objections.append(("upstream_block", name))
        if flags.get("late_trend"):
            objections.append(("late_trend_risk", True))
        if flags.get("liquidity_trap"):
            objections.append(("liquidity_trap_risk", True))
        if flags.get("news_conflict"):
            objections.append(("news_conflict", True))
        if flags.get("weak_trend_health"):
            objections.append(("weak_trend_health", True))
        if flags.get("insufficient_evidence"):
            objections.append(("insufficient_evidence", True))

        cautions = []
        for name in ("market_intelligence", "liquidity", "risk"):
            res = priors.get(name)
            if res and res.get("assessment") == Assessment.CAUTION:
                cautions.append(name)

        if objections:
            # a hard-blocking objection (upstream BLOCK / news conflict) blocks;
            # otherwise the critic escalates to CAUTION (it can never approve).
            hard = any(k in ("upstream_block", "news_conflict") for k, _ in objections)
            assessment = Assessment.BLOCK if hard else Assessment.CAUTION
            reasons = [ReasonCode.CRITIC_BLOCK] if hard else [ReasonCode.OK]
            conf = 0.85
        elif cautions:
            assessment, reasons, conf = Assessment.CAUTION, [ReasonCode.OK], 0.6
        else:
            # "CLEAR objection" == the critic has no sustained objection
            assessment, reasons, conf = Assessment.CLEAR, [ReasonCode.OK], 0.7

        out = {"assessment": assessment, "confidence": conf,
               "evidence": {"objections": objections, "cautions": cautions,
                            "note": "critic cannot approve; advisory objection only"},
               "reason_codes": reasons, "missing_inputs": [], "data_freshness": {}}
        if self.llm is not None:
            resp = self.llm.summarize(
                {"role": "critic", "objections": objections, "cautions": cautions},
                prompt_version="critic.v1")
            out["evidence"]["nl_argument"] = resp.text
            out["model_id"] = resp.model_id
            out["prompt_version"] = resp.prompt_version
        return out
