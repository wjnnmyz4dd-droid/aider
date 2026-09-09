"""Phase 8E-R G3 — non-finite JSON fail-closed at the parser boundary.

Verifies that serialize.loads rejects NaN/Infinity/-Infinity (in any position)
deterministically as a parse failure, that valid finite JSON is unaffected, that
digest success/mismatch behavior is unchanged, and that the Consumer quarantines
a non-finite instruction with the existing E_SERDE reason code WITHOUT crashing.
"""

from __future__ import annotations

from forex_swing_orb import bridge as bridge_pkg
from forex_swing_orb.bridge import serialize
from forex_swing_orb.bridge.atomic import atomic_write_text
from forex_swing_orb.bridge.contract import ReasonCode
from forex_swing_orb.bridge.paths import instruction_name
from conftest import NOW, make_instruction

SID = "a1b2c3d4e5f60718"


# --------------------------------------------------------------------------- #
# Parser boundary: non-finite constants are rejected deterministically
# --------------------------------------------------------------------------- #
def test_nan_in_numeric_field_rejected():
    assert serialize.loads('{"entry_price": NaN}') == (False, None)


def test_positive_infinity_rejected():
    assert serialize.loads('{"entry_price": Infinity}') == (False, None)


def test_negative_infinity_rejected():
    assert serialize.loads('{"entry_price": -Infinity}') == (False, None)


def test_nested_non_finite_rejected():
    assert serialize.loads('{"evidence_summary": {"atr14": NaN}}') == (False, None)
    assert serialize.loads('{"a": {"b": [1, 2, Infinity]}}') == (False, None)


def test_non_finite_in_unknown_field_rejected():
    assert serialize.loads('{"totally_unknown": -Infinity}') == (False, None)


def test_malformed_json_still_rejected():
    assert serialize.loads("{ not json") == (False, None)
    assert serialize.loads("") == (False, None)
    assert serialize.loads("[1, 2, 3]") == (False, None)     # non-dict top-level


# --------------------------------------------------------------------------- #
# Valid JSON behavior preserved exactly
# --------------------------------------------------------------------------- #
def test_valid_finite_floats_parse():
    ok, obj = serialize.loads('{"entry_price": 1.10005, "risk_fraction": 0.0025}')
    assert ok and obj["entry_price"] == 1.10005 and obj["risk_fraction"] == 0.0025


def test_valid_integers_parse():
    ok, obj = serialize.loads('{"schema_version": 1, "ticket": 5000001}')
    assert ok and obj["schema_version"] == 1 and obj["ticket"] == 5000001


def test_string_nan_is_not_a_constant():
    # a quoted "NaN"/"Infinity" is an ordinary string, not the numeric constant
    ok, obj = serialize.loads('{"note": "NaN", "x": "Infinity"}')
    assert ok and obj["note"] == "NaN" and obj["x"] == "Infinity"


def test_roundtrip_of_valid_record_unchanged():
    rec = serialize.with_integrity_digest(make_instruction())
    ok, back = serialize.loads(serialize.dumps(rec))
    assert ok and back == rec


# --------------------------------------------------------------------------- #
# Digest behavior unchanged
# --------------------------------------------------------------------------- #
def test_digest_success_unchanged():
    rec = serialize.with_integrity_digest(make_instruction())
    assert serialize.verify_integrity_digest(rec) is True


def test_digest_mismatch_unchanged():
    rec = serialize.with_integrity_digest(make_instruction())
    rec["entry_price"] = 9.99999            # tamper after digesting
    assert serialize.verify_integrity_digest(rec) is False


# --------------------------------------------------------------------------- #
# Consumer: deterministic quarantine + no crash on a non-finite instruction
# --------------------------------------------------------------------------- #
def _write_pending(paths, sid, raw_text):
    atomic_write_text(paths.pending / instruction_name(sid), raw_text)


def test_consumer_quarantines_non_finite_without_crashing(tmp_path):
    paths, ledger, audit, consumer = bridge_pkg.open_bridge(tmp_path)
    # a syntactically-claimable instruction file whose body carries a NaN price
    _write_pending(paths, SID, '{"schema_version": 1, "signal_id": "%s", '
                   '"entry_price": NaN}' % SID)
    assert consumer.claim_next(NOW) == SID
    result = consumer.process(SID, NOW)          # must NOT raise
    assert result is None                         # quarantined -> None
    # the artifact moved to quarantine (fail closed), not archived
    assert (paths.quarantine / instruction_name(SID)).exists()
    assert not (paths.claimed / instruction_name(SID)).exists()
    # deterministic reason code recorded in the audit
    events = audit.read_all()
    q = [e for e in events if e.get("action") == "quarantine"]
    assert q and q[-1]["reason_code"] == ReasonCode.E_SERDE


def test_consumer_processes_valid_instruction_unchanged(tmp_path):
    # control: a valid finite instruction still validates/finishes as before
    paths, ledger, audit, consumer = bridge_pkg.open_bridge(tmp_path)
    rec = serialize.with_integrity_digest(make_instruction(signal_id=SID))
    _write_pending(paths, SID, serialize.dumps(rec))
    assert consumer.claim_next(NOW) == SID
    result = consumer.process(SID, NOW)
    assert result is not None and result["signal_id"] == SID
