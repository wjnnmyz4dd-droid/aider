"""M-3 news bundle-level verification fail-closed (PR-3M3).

Bundle verification is a property of the BUNDLE, not merely of individual events.
When require_verified=True an UNVERIFIED bundle must NEVER pass the news gate —
regardless of zero events, irrelevant events, out-of-window events, malformed
symbols, session, or time of day. The old gate enforced verification only inside
the per-event loop, so a fresh-but-unverified bundle with no in-window relevant
event fell through to PASS (fail-open). This closes that gap at the bundle boundary
before any event filtering, while keeping freshness an independent gate.

Deterministic; calls the real gate_news authority; no networking.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from forex_swing_orb.bridge import serialize
from forex_swing_orb.compliance.contract import NewsLockoutConfig, ReasonCode
from forex_swing_orb.compliance.news import gate_news
from conftest import NOW

CFG = NewsLockoutConfig()                       # require_verified=True by default
CFG_UNVERIFIED_OK = NewsLockoutConfig(require_verified=False)
CAND = {"symbol": "EURUSD.FX"}


def _bundle(events, as_of=None, verified=True, **extra):
    b = {"as_of": as_of or serialize.iso_utc(NOW), "verified": verified, "events": events}
    b.update(extra)
    return b


def _ev(currency="USD", impact="HIGH", offset_min=0, event_id="EV1",
        verification_state="VERIFIED", **extra):
    ev = {"event_id": event_id, "currency": currency, "impact": impact,
          "event_timestamp": serialize.iso_utc(NOW + timedelta(minutes=offset_min)),
          "verification_state": verification_state}
    ev.update(extra)
    return ev


def _gate(bundle, now=NOW, cfg=CFG, cand=CAND):
    return gate_news(cand, bundle, cfg, now)


UNVERIFIED = ReasonCode.NEWS_SOURCE_UNVERIFIED


# ============================================================================
# BUNDLE VERIFICATION (1-8) — reproduction + core fail-closed
# ============================================================================
def test_1_unverified_zero_events_fails():
    # REPRODUCTION: a fresh but unverified bundle with zero events must fail closed.
    # Pre-fix this returned PASS (verification only checked inside the event loop).
    v = _gate(_bundle([], verified=False))
    assert not v.passed and UNVERIFIED in v.reason_codes


def test_2_missing_verified_zero_events_fails():
    b = {"as_of": serialize.iso_utc(NOW), "events": []}      # no "verified" key
    v = _gate(b)
    assert not v.passed and UNVERIFIED in v.reason_codes


def test_3_verified_none_zero_events_fails():
    v = _gate(_bundle([], verified=None))
    assert not v.passed and UNVERIFIED in v.reason_codes


@pytest.mark.parametrize("bad", [1, 0, "true", "false", "VERIFIEDx", [], {}, 1.0])
def test_4_verified_wrong_type_fails(bad):
    # no truthiness: only a real boolean True or the canonical "VERIFIED" token passes.
    v = _gate(_bundle([], verified=bad))
    assert not v.passed and UNVERIFIED in v.reason_codes, repr(bad)


def test_5_unverified_irrelevant_events_fails():
    # JPY event is irrelevant to EURUSD, but the bundle is unverified -> fail closed
    v = _gate(_bundle([_ev(currency="JPY", impact="LOW")], verified=False))
    assert not v.passed and UNVERIFIED in v.reason_codes


def test_6_unverified_outside_window_events_fails():
    v = _gate(_bundle([_ev(currency="USD", impact="HIGH", offset_min=600)], verified=False))
    assert not v.passed and UNVERIFIED in v.reason_codes


def test_7_unverified_in_window_event_fails():
    v = _gate(_bundle([_ev(currency="USD", impact="HIGH", offset_min=0)], verified=False))
    assert not v.passed and UNVERIFIED in v.reason_codes


def test_8_verified_zero_events_passes():
    # verified empty bundle: proven "no relevant events" -> existing PASS behavior
    v = _gate(_bundle([], verified=True))
    assert v.passed


def test_8b_verified_true_token_string_passes():
    v = _gate(_bundle([], verified="VERIFIED"))
    assert v.passed


# ============================================================================
# ORDERING (9-12) — verification precedes all event filtering
# ============================================================================
def test_9_verification_before_event_filtering():
    # a malformed event that would fail-closed per-event, plus unverified bundle:
    # the BUNDLE verification reason is what surfaces (checked first).
    v = _gate(_bundle([{"garbage": True}], verified=False))
    assert not v.passed and UNVERIFIED in v.reason_codes


def test_10_verification_before_currency_relevance():
    # malformed currency would normally fail-closed inside the loop; bundle check first
    v = _gate(_bundle([_ev(currency="US", impact="LOW")], verified=False))
    assert not v.passed and UNVERIFIED in v.reason_codes


def test_11_verification_before_time_window():
    v = _gate(_bundle([_ev(currency="USD", impact="HIGH", offset_min=-999)], verified=False))
    assert not v.passed and UNVERIFIED in v.reason_codes


def test_12_malformed_symbol_cannot_bypass_verification():
    # even a malformed/non-FX candidate symbol cannot let an unverified bundle pass
    for bad_symbol in ("", "XXX", "NOTAPAIR", None, "12345"):
        v = _gate(_bundle([], verified=False), cand={"symbol": bad_symbol})
        assert not v.passed and UNVERIFIED in v.reason_codes, repr(bad_symbol)


# ============================================================================
# INDEPENDENT GATES (13-16) — verification vs freshness vs impact
# ============================================================================
def test_13_verified_stale_gives_stale_failure():
    stale_as_of = serialize.iso_utc(NOW - timedelta(seconds=CFG.max_age_sec + 60))
    v = _gate(_bundle([], as_of=stale_as_of, verified=True))
    assert not v.passed and ReasonCode.NEWS_DATA_STALE in v.reason_codes
    assert UNVERIFIED not in v.reason_codes          # freshness is the failing gate here


def test_14_unverified_fresh_gives_verification_failure():
    v = _gate(_bundle([], verified=False))           # fresh as_of, unverified
    assert not v.passed and UNVERIFIED in v.reason_codes
    assert ReasonCode.NEWS_DATA_STALE not in v.reason_codes


def test_15_verified_fresh_blocking_event_still_blocks():
    v = _gate(_bundle([_ev(currency="USD", impact="HIGH", offset_min=0)], verified=True))
    assert not v.passed and ReasonCode.INTERNAL_NEWS_LOCKOUT in v.reason_codes


def test_16_verified_fresh_no_blocking_event_passes():
    v = _gate(_bundle([_ev(currency="USD", impact="MEDIUM", offset_min=0)], verified=True))
    assert v.passed


# ============================================================================
# CONFIGURATION (17-18)
# ============================================================================
def test_17_require_verified_false_preserves_behavior():
    # with verification not required, an unverified empty bundle passes as before
    v = _gate(_bundle([], verified=False), cfg=CFG_UNVERIFIED_OK)
    assert v.passed


def test_17b_require_verified_false_unverified_blocking_still_blocks():
    # verification-not-required does NOT weaken impact blocking
    v = _gate(_bundle([_ev(currency="USD", impact="HIGH", offset_min=0)], verified=False),
              cfg=CFG_UNVERIFIED_OK)
    assert not v.passed and ReasonCode.INTERNAL_NEWS_LOCKOUT in v.reason_codes


def test_18_require_verified_true_enforces_bundle_proof():
    assert CFG.require_verified is True
    v = _gate(_bundle([], verified=False))
    assert not v.passed and UNVERIFIED in v.reason_codes


# ============================================================================
# ADVERSARIAL PROOFS (M)
# ============================================================================
def test_adv_1_required_and_false_never_passes():
    assert not _gate(_bundle([], verified=False)).passed


def test_adv_2_missing_verified_never_treated_true():
    assert not _gate({"as_of": serialize.iso_utc(NOW), "events": []}).passed


def test_adv_3_4_5_empty_irrelevant_outofwindow_never_bypass():
    assert not _gate(_bundle([], verified=False)).passed
    assert not _gate(_bundle([_ev(currency="JPY")], verified=False)).passed
    assert not _gate(_bundle([_ev(offset_min=600)], verified=False)).passed


def test_adv_7_fix_does_not_pass_verified_stale():
    stale = serialize.iso_utc(NOW - timedelta(seconds=CFG.max_age_sec + 60))
    assert not _gate(_bundle([], as_of=stale, verified=True)).passed
