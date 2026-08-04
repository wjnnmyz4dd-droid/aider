"""Market Intelligence Agent (LLM-eligible; advisory).

Interprets and summarizes market CONTEXT: regime, higher-timeframe structure,
session, volatility, trend-continuation, ranging-vs-trending. It does NOT
recompute the deterministic strategy's calculations and never creates a trade
direction — the strategy remains authoritative.
"""

from __future__ import annotations

from ..base import Agent
from ..contract import Assessment, ReasonCode

CONTEXT_KEYS = ("regime", "htf_structure", "session", "volatility",
                "trend_continuation", "ranging_vs_trending")


class MarketIntelligenceAgent(Agent):
    agent_id = "market_intelligence"
    agent_version = "0.1.0"
    uses_llm = True

    def _assess(self, request, context, now):
        market = (context or {}).get("market") or {}
        evidence = {k: market.get(k, "UNKNOWN") for k in CONTEXT_KEYS}
        missing = [k for k in CONTEXT_KEYS if market.get(k) in (None, "UNKNOWN")]

        # summarization is informational: full context -> CLEAR, gaps -> CAUTION.
        if len(missing) >= 3:
            assessment, reasons, conf = (Assessment.CAUTION,
                                         [ReasonCode.INSUFFICIENT_EVIDENCE], 0.3)
        else:
            assessment, reasons, conf = (Assessment.CLEAR, [ReasonCode.OK],
                                         round(1.0 - len(missing) * 0.15, 3))
        out = {"assessment": assessment, "confidence": conf, "evidence": evidence,
               "reason_codes": reasons, "missing_inputs": missing,
               "data_freshness": {"market": market.get("age_sec")}}

        if self.llm is not None:          # optional NL summary; capture provenance
            resp = self.llm.summarize(
                {"role": "market_intelligence", "context": evidence},
                prompt_version="market_intelligence.v1")
            out["evidence"]["nl_summary"] = resp.text
            out["model_id"] = resp.model_id
            out["prompt_version"] = resp.prompt_version
        return out
