"""Market Intelligence Agent (LLM-eligible; advisory) — Phase 4B live behavior.

Classifies market regime and summarizes higher-timeframe structure, session,
volatility and continuation context, and judges whether conditions support the
EXISTING strategy candidate. It CONSUMES strategy-produced facts (H4/D1 trend,
Trend Health, session) — it never recalculates trend, Trend Health, the London
Opening Range, breakout, retest, or price-action confirmation. The authoritative
regime is deterministic; an LLM may only enrich the natural-language summary.
"""

from __future__ import annotations

from ..base import Agent
from ..contract import Assessment, ReasonCode

# regime taxonomy
TRENDING, RANGING, TRANSITIONAL, DISORDERED, UNKNOWN = (
    "TRENDING", "RANGING", "TRANSITIONAL", "DISORDERED", "UNKNOWN")

_DIRECTIONAL = ("BULLISH", "BEARISH")
_ABNORMAL_VOL = ("ABNORMAL", "EXTREME", "SPIKE")
FAVORABLE_SESSION = "LONDON"          # Session Edge is a London-ORB strategy


class MarketIntelligenceAgent(Agent):
    agent_id = "market_intelligence"
    agent_version = "0.2.0"
    uses_llm = True

    def _assess(self, request, context, now):
        market = (context or {}).get("market") or {}
        candidate = (context or {}).get("strategy_candidate_direction")

        # strategy facts are CONSUMED, never recomputed
        d1 = _norm(market.get("trend_d1"))
        h4 = _norm(market.get("trend_h4"))
        health = _norm(market.get("trend_health"))
        session = _norm(market.get("session"))
        volatility = _norm(market.get("volatility"))
        structure = _norm(market.get("htf_structure"))
        continuation = _norm(market.get("trend_continuation"))
        regime_hint = _norm(market.get("regime"))

        missing = [k for k in ("trend_d1", "trend_h4", "trend_health")
                   if market.get(k) is None]
        reasons = []

        regime = self._classify_regime(d1, h4, health, volatility, regime_hint,
                                       structure, continuation)

        # map regime -> advisory assessment + reason codes
        if regime == UNKNOWN:
            assessment = Assessment.CAUTION
            reasons.append(ReasonCode.MI_DATA_INSUFFICIENT)
        elif regime == DISORDERED:
            assessment = Assessment.BLOCK
            reasons.append(ReasonCode.MI_DISORDERED)
            if _abnormal(volatility):
                reasons.append(ReasonCode.MI_VOLATILITY_ABNORMAL)
        elif regime == TRENDING:
            assessment = Assessment.CLEAR
            reasons.append(ReasonCode.MI_TRENDING_SUPPORTIVE)
        elif regime == RANGING:
            assessment = Assessment.CAUTION
            reasons.append(ReasonCode.MI_RANGING)
        else:  # TRANSITIONAL
            assessment = Assessment.CAUTION
            reasons.append(ReasonCode.MI_TRANSITIONAL)

        # structure conflict: opposing directional HTF trends OR candidate vs regime
        if d1 in _DIRECTIONAL and h4 in _DIRECTIONAL and d1 != h4:
            reasons.append(ReasonCode.MI_STRUCTURE_CONFLICT)
            assessment = _downgrade(assessment, Assessment.CAUTION)
        if candidate and regime == TRENDING and _conflicts(candidate, d1 or h4):
            reasons.append(ReasonCode.MI_STRUCTURE_CONFLICT)
            assessment = _downgrade(assessment, Assessment.CAUTION)

        # session favorability (advisory downgrade only)
        if session and session != FAVORABLE_SESSION:
            reasons.append(ReasonCode.MI_SESSION_UNFAVORABLE)
            assessment = _downgrade(assessment, Assessment.CAUTION)

        if not reasons:
            reasons = [ReasonCode.OK]
        conf = self._confidence(regime, missing, health)

        out = {
            "assessment": assessment,
            "confidence": conf,
            "evidence": {
                "regime": regime,
                "structure_summary": {"trend_d1": d1, "trend_h4": h4,
                                      "trend_health": health, "htf_structure": structure},
                "session_context": {"session": session,
                                    "favorable": session == FAVORABLE_SESSION if session else None},
                "volatility_context": {"volatility": volatility,
                                       "abnormal": _abnormal(volatility)},
                "continuation_context": {"trend_continuation": continuation},
                "supports_candidate": (candidate is None) or
                (regime == TRENDING and not _conflicts(candidate, d1 or h4)),
                "consumes_strategy_facts": True,
                "recomputes_strategy": False,
            },
            "reason_codes": _dedup(reasons),
            "missing_inputs": missing,
            "data_freshness": {"market": market.get("age_sec")},
        }
        if self.llm is not None:            # summary only; never sets the regime
            resp = self.llm.summarize(
                {"role": "market_intelligence", "regime": regime,
                 "structure": out["evidence"]["structure_summary"]},
                prompt_version="market_intelligence.v2")
            if _valid_llm(resp):
                out["evidence"]["nl_summary"] = resp.text
                out["model_id"] = resp.model_id
                out["prompt_version"] = resp.prompt_version
                out["evidence"]["llm_validation"] = "OK"
            else:
                out["evidence"]["llm_validation"] = "REJECTED"   # facts stand regardless
        return out

    # -- deterministic regime classifier (interpretation, not recomputation) --
    def _classify_regime(self, d1, h4, health, volatility, regime_hint,
                         structure, continuation):
        if _abnormal(volatility):
            return DISORDERED
        # prefer explicit strategy trend facts
        if d1 in _DIRECTIONAL and h4 in _DIRECTIONAL:
            if d1 == h4:
                if health in ("STRONG", "MODERATE"):
                    return TRENDING
                return TRANSITIONAL       # aligned but weak health
            return TRANSITIONAL           # opposing HTF trends
        if d1 == "NEUTRAL" and h4 == "NEUTRAL":
            return RANGING
        if d1 in _DIRECTIONAL or h4 in _DIRECTIONAL:
            return TRANSITIONAL           # partial trend
        # fall back to provided context hints when explicit facts are absent
        if regime_hint in (TRENDING, RANGING, TRANSITIONAL, DISORDERED):
            if regime_hint == TRENDING and continuation == "NO":
                return TRANSITIONAL
            return regime_hint
        if structure in ("HH_HL", "LH_LL") and continuation in ("YES", None):
            return TRENDING
        if structure in ("RANGE", "MIXED"):
            return RANGING
        return UNKNOWN

    def _confidence(self, regime, missing, health):
        if regime == UNKNOWN:
            return 0.25
        base = {TRENDING: 0.8, RANGING: 0.6, TRANSITIONAL: 0.5, DISORDERED: 0.7}.get(regime, 0.4)
        base -= 0.1 * len(missing)
        if health == "STRONG":
            base += 0.05
        return round(max(0.1, min(1.0, base)), 3)


def _norm(v):
    return v.upper() if isinstance(v, str) else v


def _abnormal(volatility):
    return isinstance(volatility, str) and volatility.upper() in _ABNORMAL_VOL


def _conflicts(direction, trend):
    if trend not in _DIRECTIONAL:
        return False
    want = "BULLISH" if str(direction).upper() in ("LONG", "BULLISH") else "BEARISH"
    return want != trend


def _downgrade(current, floor):
    return current if Assessment.severity(current) >= Assessment.severity(floor) else floor


def _dedup(seq):
    seen = set()
    return [x for x in seq if not (x in seen or seen.add(x))]


def _valid_llm(resp):
    return resp is not None and isinstance(getattr(resp, "text", None), str) \
        and getattr(resp, "model_id", None) and getattr(resp, "prompt_version", None)
