"""PR-3H / M6+M7 — news impact-uncertainty and malformed-event boundaries.

The compliance news gate is the SINGULAR authorization authority. For a RELEVANT,
in-window event:
  * M6 — an UNKNOWN/unrecognized/empty impact must NOT be treated as harmless
    (fail closed);
  * M7 — a malformed RELEVANT event fails closed; a provably UNRELATED malformed
    event must NOT block a safe pair; an event whose currency/relevance cannot be
    established fails closed.
These tests call the real gate_news authority. Deterministic; no networking.
"""

from __future__ import annotations

from datetime import timedelta

from forex_swing_orb.bridge import serialize
from forex_swing_orb.compliance.contract import NewsLockoutConfig, ReasonCode
from forex_swing_orb.compliance.news import gate_news
from conftest import NOW

CFG = NewsLockoutConfig()                 # pre/post 15m, max_age 3600, require_verified=True
CAND = {"symbol": "EURUSD.FX"}


def _bundle(events, as_of=None, verified=True):
    return {"as_of": as_of or serialize.iso_utc(NOW), "verified": verified, "events": events}


def _ev(currency="USD", impact="HIGH", offset_min=0, event_id="EV1",
        verification_state="VERIFIED", **extra):
    ev = {"event_id": event_id, "currency": currency, "impact": impact,
          "event_timestamp": serialize.iso_utc(NOW + timedelta(minutes=offset_min)),
          "verification_state": verification_state}
    ev.update(extra)
    return ev


def _gate(events, now=NOW, cfg=CFG, cand=CAND):
    return gate_news(cand, _bundle(events), cfg, now)


# --------------------------------------------------------------------------- #
# M6 — impact vocabulary (relevant + in-window)
# --------------------------------------------------------------------------- #
def test_high_relevant_blocks():
    v = _gate([_ev(currency="USD", impact="HIGH")])
    assert not v.passed and ReasonCode.INTERNAL_NEWS_LOCKOUT in v.reason_codes


def test_medium_relevant_does_not_block():
    assert _gate([_ev(currency="USD", impact="MEDIUM")]).passed


def test_low_relevant_does_not_block():
    assert _gate([_ev(currency="USD", impact="LOW")]).passed


def test_unknown_impact_relevant_fails_closed():
    for imp in ("SEVERE", "CRITICALLY", "XYZ", "URGENT", "4", "9999"):
        v = _gate([_ev(currency="USD", impact=imp)])
        assert not v.passed and ReasonCode.NEWS_IMPACT_UNKNOWN in v.reason_codes, imp


def test_empty_and_whitespace_impact_relevant_fails_closed():
    for imp in ("", "   ", "\t"):
        v = _gate([_ev(currency="USD", impact=imp)])
        assert not v.passed and ReasonCode.NEWS_IMPACT_UNKNOWN in v.reason_codes, repr(imp)


def test_missing_impact_relevant_fails_closed():
    v = _gate([_ev(currency="USD", impact=None)])
    assert not v.passed and ReasonCode.NEWS_DATA_UNAVAILABLE in v.reason_codes


def test_numeric_type_unknown_impact_fails_closed():
    v = _gate([_ev(currency="USD", impact=7)])           # unexpected numeric type
    assert not v.passed and ReasonCode.NEWS_IMPACT_UNKNOWN in v.reason_codes


def test_high_aliases_block():
    for imp in ("high", " HIGH ", "RED", "CRITICAL", "3", "3.0", "H"):
        v = _gate([_ev(currency="USD", impact=imp)])
        assert not v.passed and ReasonCode.INTERNAL_NEWS_LOCKOUT in v.reason_codes, imp


def test_unknown_impact_but_OUT_of_window_does_not_block():
    # unknown impact only fails closed when the event is temporally APPLICABLE
    assert _gate([_ev(currency="USD", impact="SEVERE", offset_min=600)]).passed


def test_unknown_impact_but_UNRELATED_does_not_block():
    # M6/M7: an unknown-impact event on an unrelated currency must not block EURUSD
    assert _gate([_ev(currency="JPY", impact="SEVERE")]).passed


# --------------------------------------------------------------------------- #
# M7 — malformed / relevance matrix
# --------------------------------------------------------------------------- #
def test_caseA_relevant_malformed_fails_closed():
    # known relevant currency but missing timestamp -> cannot establish safety
    ev = _ev(currency="USD"); ev.pop("event_timestamp")
    v = _gate([ev])
    assert not v.passed and ReasonCode.NEWS_DATA_UNAVAILABLE in v.reason_codes


def test_caseB_unrelated_malformed_does_not_block():
    # malformed (missing impact+timestamp) but currency is a valid UNRELATED code
    ev = {"event_id": "E", "currency": "JPY"}            # no impact / timestamp
    assert _gate([ev]).passed                            # EURUSD safe -> not blocked


def test_caseC_unestablishable_currency_fails_closed():
    for bad_cur in (None, "US", "USDD", "12", "US1", 123, ""):
        ev = _ev(currency=bad_cur, impact="LOW")
        v = _gate([ev])
        assert not v.passed and ReasonCode.NEWS_DATA_UNAVAILABLE in v.reason_codes, repr(bad_cur)


def test_caseC_non_dict_event_fails_closed():
    v = _gate(["not-a-dict"])
    assert not v.passed and ReasonCode.NEWS_DATA_UNAVAILABLE in v.reason_codes


def test_caseE_valid_high_relevant_blocks_despite_unrelated_malformed():
    unrelated_malformed = {"event_id": "M", "currency": "JPY"}     # no impact/ts
    valid_high = _ev(currency="USD", impact="HIGH", event_id="H1")
    v = _gate([unrelated_malformed, valid_high])
    assert not v.passed and ReasonCode.INTERNAL_NEWS_LOCKOUT in v.reason_codes


def test_caseF_malformed_relevant_blocks_despite_valid_harmless():
    harmless = _ev(currency="GBP", impact="LOW", event_id="L1")    # unrelated to EURUSD
    malformed_relevant = {"event_id": "R", "currency": "EUR"}      # relevant, no impact/ts
    v = _gate([harmless, malformed_relevant])
    assert not v.passed and ReasonCode.NEWS_DATA_UNAVAILABLE in v.reason_codes


# --------------------------------------------------------------------------- #
# property tests (§11 A-F)
# --------------------------------------------------------------------------- #
def test_propA_more_uncertainty_never_more_permissive():
    # MEDIUM (authorized) -> replacing with UNKNOWN can only tighten (block)
    assert _gate([_ev(currency="USD", impact="MEDIUM")]).passed
    assert not _gate([_ev(currency="USD", impact="???")]).passed


def test_propB_unrelated_malformed_cannot_cause_block():
    base = _gate([])                                     # no events -> authorized
    with_unrelated = _gate([{"event_id": "x", "currency": "JPY"}])   # unrelated malformed
    assert base.passed and with_unrelated.passed


def test_propC_unknown_relevance_never_more_permissive():
    # a malformed-currency event can never authorize (must fail closed)
    assert not _gate([_ev(currency="US", impact="LOW")]).passed


def test_propD_high_relevant_always_blocks_with_noise():
    noise = [{"event_id": "n1", "currency": "JPY"}, _ev(currency="GBP", impact="LOW", event_id="n2")]
    v = _gate(noise + [_ev(currency="EUR", impact="HIGH", event_id="hi")])
    assert not v.passed and ReasonCode.INTERNAL_NEWS_LOCKOUT in v.reason_codes


def test_propE_persistence_roundtrip_same_decision():
    events = [_ev(currency="USD", impact="SEVERE")]      # unknown -> fail closed
    b = _bundle(events)
    direct = gate_news(CAND, b, CFG, NOW)
    roundtrip = gate_news(CAND, serialize.loads(serialize.dumps(b))[1], CFG, NOW)
    assert direct.passed == roundtrip.passed is False
    assert set(direct.reason_codes) == set(roundtrip.reason_codes)


def test_propF_stale_bundle_still_stale_regardless_of_events():
    stale = _bundle([_ev(currency="USD", impact="MEDIUM")],
                    as_of=serialize.iso_utc(NOW - timedelta(seconds=7200)))
    v = gate_news(CAND, stale, CFG, NOW)
    assert not v.passed and ReasonCode.NEWS_DATA_STALE in v.reason_codes
