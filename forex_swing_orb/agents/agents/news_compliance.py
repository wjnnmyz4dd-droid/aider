"""News & Compliance Agent (DETERMINISTIC ONLY; no LLM) — Phase 4B live behavior.

Consumes a NORMALIZED event bundle (no scraping, no networking, no HTTP). It
validates event schema, normalizes event time, maps currencies to the affected
pair, applies deterministic pre/post-event lockout windows, and classifies
CLEAR / CAUTION / BLOCK. It fails closed when required news data is missing,
stale, malformed, unverifiable, timezone-ambiguous, or conflicting. It operates
logically 24/7 (weekends / market-closed included). News is a FILTER only: it
never creates trade direction, a strategy candidate, or an order, and never
predicts event outcomes or treats rumors as verified.

A future approved source-contract phase may populate the normalized bundle via a
separate adapter; this phase never fetches anything.
"""

from __future__ import annotations

import re

from ...bridge import serialize
from ..base import Agent
from ..contract import Assessment, NewsRating, ReasonCode

KNOWN_CURRENCIES = frozenset({
    "USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF", "CNY", "SEK",
    "NOK", "SGD", "HKD", "MXN", "ZAR", "TRY", "PLN"})

_HIGH = ("HIGH", "H", "3")
_MED = ("MEDIUM", "MED", "M", "2")
_OFFSET_RE = re.compile(r"([+-]\d\d:?\d\d)$")


class NewsComplianceAgent(Agent):
    agent_id = "news_compliance"
    agent_version = "0.2.0"
    uses_llm = False

    def _assess(self, request, context, now):
        news = (context or {}).get("news")
        if not isinstance(news, dict):
            return self._block([ReasonCode.NEWS_DATA_UNAVAILABLE, ReasonCode.DQ_MISSING_INPUT],
                               ["news"])
        events = news.get("events")
        if events is None:
            return self._block([ReasonCode.NEWS_DATA_UNAVAILABLE, ReasonCode.DQ_MISSING_INPUT],
                               ["news.events"])
        if now is None:
            return self._block([ReasonCode.NEWS_DATA_UNAVAILABLE, ReasonCode.DQ_MISSING_INPUT],
                               ["now"])

        # bundle-level verification (legacy) and staleness
        bundle_verified = news.get("verified")
        if bundle_verified is False:
            return self._block([ReasonCode.NEWS_SOURCE_UNVERIFIED, ReasonCode.DQ_NO_PROVENANCE],
                               ["news.verified"])
        age = news.get("age_sec")
        max_age = int(news.get("max_age_sec", 3600))
        if isinstance(age, (int, float)) and age > max_age:
            return self._block([ReasonCode.NEWS_DATA_STALE, ReasonCode.DQ_STALE], [])

        symbol = str(request["symbol"])
        base, quote = symbol[0:3], symbol[3:6]
        pre = int(news.get("pre_lockout_min", 30))
        post = int(news.get("post_lockout_min", 30))

        # conflicting records: same event_id, differing time/impact
        by_id = {}
        for ev in events:
            eid = ev.get("event_id") if isinstance(ev, dict) else None
            if eid is None:
                continue
            sig = (ev.get("event_timestamp") or ev.get("time"), str(ev.get("impact")).upper())
            if eid in by_id and by_id[eid] != sig:
                return self._block([ReasonCode.NEWS_CONFLICTING_RECORDS], [f"event_id:{eid}"])
            by_id[eid] = sig

        worst = NewsRating.CLEAR
        hits = []
        notes = []
        event_reasons = []              # accurate, deterministic per-event codes
        for ev in events:
            if not isinstance(ev, dict):
                return self._block([ReasonCode.NEWS_DATA_MALFORMED, ReasonCode.DQ_MALFORMED],
                                   ["event"])
            norm = self._normalize(ev, bundle_verified)
            if norm.get("_malformed"):
                return self._block([ReasonCode.NEWS_DATA_MALFORMED, ReasonCode.DQ_MALFORMED],
                                   [norm["_malformed"]])
            cur = norm["currency"]
            if cur not in KNOWN_CURRENCIES:
                notes.append(ReasonCode.NEWS_CURRENCY_NOT_MAPPED)
                # unknown code cannot equal a known base/quote -> not relevant
                continue
            if cur not in (base, quote):
                continue                              # not relevant to this pair
            # timezone must be unambiguous for a relevant event
            if norm["_ambiguous_tz"]:
                return self._block([ReasonCode.NEWS_TIMEZONE_AMBIGUOUS], ["event.timezone"])
            et = norm["_utc"]
            if et is None:
                return self._block([ReasonCode.NEWS_DATA_MALFORMED, ReasonCode.DQ_MALFORMED],
                                   ["event.event_timestamp"])
            # Finding A: only events INSIDE the lockout window can affect the
            # decision. An out-of-window event (e.g. days away) is ignored here,
            # including its verification state — it can never block now.
            delta_min = (et - now).total_seconds() / 60.0
            in_window = (-post) <= delta_min <= pre
            if not in_window:
                continue
            # verification is enforced ONLY for in-window relevant events
            if norm["verification_state"] not in ("VERIFIED", None):
                worst = NewsRating.BLOCK
                event_reasons.append(ReasonCode.NEWS_SOURCE_UNVERIFIED)
                hits.append({"event": norm["event_name"], "currency": cur,
                             "delta_min": round(delta_min, 1), "issue": "unverified"})
                continue
            impact = norm["impact"]
            if impact in _HIGH:
                worst = NewsRating.BLOCK
                event_reasons.append(ReasonCode.NEWS_HIGH_IMPACT_BLOCK)
                hits.append({"event": norm["event_name"], "currency": cur,
                             "delta_min": round(delta_min, 1), "impact": "HIGH"})
            elif impact in _MED:
                if worst != NewsRating.BLOCK:
                    worst = NewsRating.CAUTION
                event_reasons.append(ReasonCode.NEWS_CAUTION_WINDOW)
                hits.append({"event": norm["event_name"], "currency": cur,
                             "delta_min": round(delta_min, 1), "impact": "MEDIUM"})

        if worst == NewsRating.CLEAR:
            if ReasonCode.NEWS_CURRENCY_NOT_MAPPED in notes:
                # unmappable-currency hygiene note: advisory caution, never a block
                worst = NewsRating.CAUTION
                reasons = [ReasonCode.NEWS_CAUTION_WINDOW, ReasonCode.NEWS_CURRENCY_NOT_MAPPED]
            else:
                reasons = [ReasonCode.NEWS_CLEAR]
        else:
            reasons = _dedup(event_reasons + notes)

        conf = 0.9 if worst != NewsRating.CLEAR else 0.85
        return {
            "assessment": NewsRating.TO_ASSESSMENT[worst],
            "confidence": conf,
            "evidence": {"news_rating": worst, "lockout_hits": hits,
                         "pre_lockout_min": pre, "post_lockout_min": post,
                         "creates_direction": False, "operates_24_7": True,
                         "predicts_outcomes": False},
            "reason_codes": reasons, "missing_inputs": [],
            "data_freshness": {"news": age},
        }

    # -- normalization ------------------------------------------------------
    def _normalize(self, ev, bundle_verified):
        et = ev.get("event_timestamp") or ev.get("time")
        name = ev.get("event_name") or ev.get("event")
        ing = ev.get("ingestion_timestamp") or ev.get("ingested_at")
        src = ev.get("source")
        cur = ev.get("currency")
        imp = ev.get("impact")
        for field, val in (("event_timestamp", et), ("event_name", name),
                           ("ingestion_timestamp", ing), ("source", src),
                           ("currency", cur), ("impact", imp)):
            if val in (None, ""):
                return {"_malformed": field}
        tz = ev.get("timezone")
        ambiguous, utc = self._resolve_time(et, tz)
        vstate = ev.get("verification_state")
        if vstate is None and bundle_verified is True:
            vstate = "VERIFIED"
        return {"currency": str(cur).upper(), "impact": str(imp).upper(),
                "event_name": name, "verification_state": vstate,
                "_ambiguous_tz": ambiguous, "_utc": utc}

    def _resolve_time(self, ts, tz):
        if not isinstance(ts, str):
            return True, None
        s = ts.strip()
        has_offset = s.endswith("Z") or bool(_OFFSET_RE.search(s))
        if has_offset:
            return False, serialize.parse_iso(s)
        # naive timestamp: only unambiguous if tz is explicitly UTC/GMT
        if isinstance(tz, str) and tz.upper() in ("UTC", "GMT"):
            return False, serialize.parse_iso(s + "Z")
        return True, None                            # ambiguous -> fail closed

    def _reasons_for(self, rating):
        return {NewsRating.BLOCK: [ReasonCode.NEWS_HIGH_IMPACT_BLOCK],
                NewsRating.CAUTION: [ReasonCode.NEWS_CAUTION_WINDOW],
                NewsRating.CLEAR: [ReasonCode.NEWS_CLEAR]}[rating]

    def _block(self, reasons, missing):
        return {"assessment": Assessment.BLOCK, "confidence": 0.0,
                "evidence": {"news_rating": NewsRating.BLOCK, "fail_closed": True,
                             "creates_direction": False},
                "reason_codes": _dedup(reasons), "missing_inputs": missing,
                "data_freshness": {}}


def _dedup(seq):
    seen = set()
    return [x for x in seq if not (x in seen or seen.add(x))]
