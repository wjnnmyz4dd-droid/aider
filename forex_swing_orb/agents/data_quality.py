"""Data-quality contract (deterministic; runs BEFORE any agent).

Fail-closed gate: if required data is missing, stale, malformed, lacks
provenance, has non-monotonic timestamps, an unknown timezone, or an invalid
symbol mapping, the whole evaluation stops and no agent runs. Deterministic only
— never LLM-assisted.
"""

from __future__ import annotations

from ..bridge import serialize
from .contract import ReasonCode

# canonical bridge symbol form, e.g. EURUSD.FX
import re
_SYMBOL_RE = re.compile(r"^[A-Z]{6}\.FX$")


class DataQualityReport:
    __slots__ = ("ok", "reason_codes", "missing_inputs", "freshness", "detail")

    def __init__(self, ok, reason_codes, missing_inputs, freshness, detail):
        self.ok = ok
        self.reason_codes = reason_codes
        self.missing_inputs = missing_inputs
        self.freshness = freshness
        self.detail = detail

    def as_dict(self):
        return {
            "ok": self.ok,
            "reason_codes": list(self.reason_codes),
            "missing_inputs": list(self.missing_inputs),
            "freshness": dict(self.freshness),
            "detail": dict(self.detail),
        }


def _age_seconds(now, ts):
    a = serialize.parse_iso(ts)
    if a is None or now is None:
        return None
    return (now - a).total_seconds()


def validate(request, bundle, now, max_age_sec=900):
    """Validate the data ``bundle`` referenced by ``request`` at time ``now``.

    ``bundle`` is a plain dict the caller assembles from the referenced sources:
      market: {timestamp, provenance, bars_monotonic(bool), malformed(bool)}
      news:   {timestamp, provenance, malformed(bool)}
      (memory context is optional and never blocks)

    Returns a :class:`DataQualityReport`. Fails closed on the first problem class
    while still collecting all missing inputs.
    """
    reasons = []
    missing = []
    freshness = {}
    detail = {}

    if not isinstance(bundle, dict):
        return DataQualityReport(False, [ReasonCode.DQ_MALFORMED], ["bundle"], {},
                                 {"bundle": "not-a-dict"})

    # symbol mapping must be a known canonical form
    if not _SYMBOL_RE.match(str(request.get("symbol", ""))):
        reasons.append(ReasonCode.DQ_SYMBOL_MAP)
        detail["symbol"] = request.get("symbol")

    for key in ("market", "news"):
        section = bundle.get(key)
        if not isinstance(section, dict):
            missing.append(key)
            continue
        ts = section.get("timestamp")
        if not ts:
            missing.append(f"{key}.timestamp")
        else:
            age = _age_seconds(now, ts)
            freshness[key] = age
            if age is None:
                reasons.append(ReasonCode.DQ_MALFORMED)
                detail[f"{key}.timestamp"] = ts
            elif age > max_age_sec or age < -1:      # stale or implausibly future
                reasons.append(ReasonCode.DQ_STALE)
                detail[f"{key}.age_sec"] = age
        if not section.get("provenance"):
            reasons.append(ReasonCode.DQ_NO_PROVENANCE)
            missing.append(f"{key}.provenance")
        if section.get("malformed"):
            reasons.append(ReasonCode.DQ_MALFORMED)
            detail[f"{key}.malformed"] = True

    # timezone must be explicit for the market series
    market = bundle.get("market") if isinstance(bundle.get("market"), dict) else {}
    if market and not market.get("timezone"):
        reasons.append(ReasonCode.DQ_NO_TIMEZONE)
        missing.append("market.timezone")
    if market.get("bars_monotonic") is False:
        reasons.append(ReasonCode.DQ_NON_MONOTONIC)
        detail["market.monotonic"] = False

    if missing:
        reasons.append(ReasonCode.DQ_MISSING_INPUT)

    ok = not reasons and not missing
    if ok:
        reasons = [ReasonCode.DQ_OK]
    # de-dup reasons, keep order
    seen = set()
    ordered = [r for r in reasons if not (r in seen or seen.add(r))]
    return DataQualityReport(ok, ordered, missing, freshness, detail)
