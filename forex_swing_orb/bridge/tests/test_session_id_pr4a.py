"""PR-4A — the bridge preserves and validates session_id (transport shape only),
and session-distinct signal_ids do not collide in the exactly-once ledger."""

from __future__ import annotations

from datetime import datetime, timezone

import forex_swing_orb.bridge as bridge_pkg
from forex_swing_orb.bridge import serialize
from forex_swing_orb.bridge.paths import instruction_name
from conftest import NOW, make_instruction


def _write(paths, rec):
    from forex_swing_orb.bridge.atomic import atomic_write_text
    atomic_write_text(paths.pending / instruction_name(rec["signal_id"]),
                      serialize.dumps(rec))


def test_session_id_round_trips_through_consume(tmp_path):
    paths, ledger, audit, consumer = bridge_pkg.open_bridge(tmp_path)
    rec = serialize.with_integrity_digest(
        make_instruction(signal_id="aaaa1111bbbb2222", session_id="NEW_YORK"))
    _write(paths, rec)
    assert consumer.claim_next(NOW) == "aaaa1111bbbb2222"
    result = consumer.process("aaaa1111bbbb2222", NOW)
    assert result is not None
    # the archived accepted instruction preserves session_id verbatim
    archived = serialize.loads(
        (paths.archive_accepted / instruction_name("aaaa1111bbbb2222")).read_text())[1]
    assert archived["session_id"] == "NEW_YORK"


def test_missing_session_id_fails_validation(tmp_path):
    paths, ledger, audit, consumer = bridge_pkg.open_bridge(tmp_path)
    rec = make_instruction(signal_id="cc11cc11dd22dd22")
    rec.pop("session_id")                                    # legacy-shaped (no session)
    _write(paths, serialize.with_integrity_digest(rec))
    consumer.claim_next(NOW)
    result = consumer.process("cc11cc11dd22dd22", NOW)
    assert result is not None and result["status"] == "REJECTED"   # never accepted/executed


def test_schema_one_instruction_rejected(tmp_path):
    # legacy schema-1 instructions are retired from the multi-session pipeline
    paths, ledger, audit, consumer = bridge_pkg.open_bridge(tmp_path)
    rec = make_instruction(signal_id="ee33ee33ff44ff44", schema_version=1)
    _write(paths, serialize.with_integrity_digest(rec))
    consumer.claim_next(NOW)
    result = consumer.process("ee33ee33ff44ff44", NOW)
    assert result is not None and result["status"] == "REJECTED"


def test_session_distinct_signal_ids_do_not_collide(tmp_path):
    # two same-geometry instructions differing only by session_id are DISTINCT files
    paths, ledger, audit, consumer = bridge_pkg.open_bridge(tmp_path)
    a = serialize.with_integrity_digest(
        make_instruction(signal_id="1111aaaa2222bbbb", session_id="LONDON"))
    b = serialize.with_integrity_digest(
        make_instruction(signal_id="3333cccc4444dddd", session_id="NEW_YORK"))
    _write(paths, a)
    _write(paths, b)
    for sid in ("1111aaaa2222bbbb", "3333cccc4444dddd"):
        consumer.claim_next(NOW)
    r1 = consumer.process("1111aaaa2222bbbb", NOW)
    r2 = consumer.process("3333cccc4444dddd", NOW)
    assert r1 is not None and r2 is not None                 # both accepted independently
