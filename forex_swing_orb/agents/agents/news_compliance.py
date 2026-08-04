"""News & Compliance Agent (DETERMINISTIC ONLY; no LLM).

Ingests normalized scheduled economic events, maps affected currencies to the
pair, applies pre/post-event lockout windows, and outputs CLEAR / CAUTION /
BLOCK. Fails closed on missing, stale, malformed, or unverifiable required data.
Operates continuously (including weekends / market-closed periods). It never
creates a trade direction.

This phase consumes a NORMALIZED, pre-supplied event bundle only. Live Forex
Factory scraping is out of scope until an approved source contract exists
(see docs); attempting to fetch is not possible here — there is no networking.
"""

from __future__ import annotations

from ...bridge import serialize
from ..base import Agent
from ..contract import Assessment, NewsRating, ReasonCode

# minimum fields a normalized event must carry to be trustworthy
REQUIRED_EVENT_FIELDS = ("time", "currency", "impact", "event", "source", "ingested_at")


class NewsComplianceAgent(Agent):
    agent_id = "news_compliance"
    agent_version = "0.1.0"
    uses_llm = False

    def _assess(self, request, context, now):
        news = (context or {}).get("news")
        if not isinstance(news, dict):
            return self._block([ReasonCode.DQ_MISSING_INPUT], ["news"])
        events = news.get("events")
        if events is None:
            return self._block([ReasonCode.DQ_MISSING_INPUT], ["news.events"])
        if news.get("verified") is not True:          # unverifiable -> fail closed
            return self._block([ReasonCode.DQ_NO_PROVENANCE], ["news.verified"])

        symbol = request["symbol"]                    # EURUSD.FX
        base, quote = symbol[0:3], symbol[3:6]
        pre = int(news.get("pre_lockout_min", 30))
        post = int(news.get("post_lockout_min", 30))

        worst = NewsRating.CLEAR
        hits = []
        for ev in events:
            miss = [f for f in REQUIRED_EVENT_FIELDS if f not in ev or ev[f] in (None, "")]
            if miss:                                   # malformed required data
                return self._block([ReasonCode.DQ_MALFORMED], [f"event.{miss[0]}"])
            cur = str(ev["currency"]).upper()
            if cur not in (base, quote):
                continue
            et = serialize.parse_iso(ev["time"])
            if et is None:
                return self._block([ReasonCode.DQ_MALFORMED], ["event.time"])
            if now is None:
                return self._block([ReasonCode.DQ_MISSING_INPUT], ["now"])
            delta_min = (et - now).total_seconds() / 60.0
            impact = str(ev["impact"]).upper()
            in_window = (-post) <= delta_min <= pre
            if in_window and impact == "HIGH":
                worst = NewsRating.BLOCK
                hits.append({"event": ev["event"], "currency": cur, "delta_min": round(delta_min, 1), "impact": impact})
            elif in_window and impact in ("MEDIUM", "MED"):
                if worst != NewsRating.BLOCK:
                    worst = NewsRating.CAUTION
                hits.append({"event": ev["event"], "currency": cur, "delta_min": round(delta_min, 1), "impact": impact})

        reasons = [ReasonCode.NEWS_BLOCK] if worst == NewsRating.BLOCK else [ReasonCode.OK]
        conf = 0.9 if worst != NewsRating.CLEAR else 0.8
        return {
            "assessment": NewsRating.TO_ASSESSMENT[worst],
            "confidence": conf,
            "evidence": {"news_rating": worst, "lockout_hits": hits,
                         "pre_lockout_min": pre, "post_lockout_min": post},
            "reason_codes": reasons, "missing_inputs": [],
            "data_freshness": {"news": news.get("age_sec")},
        }

    def _block(self, reasons, missing):
        return {"assessment": Assessment.BLOCK, "confidence": 0.0,
                "evidence": {"news_rating": NewsRating.BLOCK, "fail_closed": True},
                "reason_codes": reasons, "missing_inputs": missing,
                "data_freshness": {}}
