"""Shared memory tests: provenance required, immutable raw records, deterministic
ids, versioned derived summaries, query interface. (Test reqs 15,20,21.)"""

from __future__ import annotations

import pytest

from forex_swing_orb.agents.memory import MemoryStore, MemoryError
from conftest import NOW, iso


def test_provenance_is_required(memory):
    with pytest.raises(MemoryError):
        memory.write_raw("lesson", "EURUSD.FX", {"note": "x"}, source="", timestamp=iso(NOW))


def test_unknown_kind_rejected(memory):
    with pytest.raises(MemoryError):
        memory.write_raw("not_a_kind", "EURUSD.FX", {}, source="s", timestamp=iso(NOW))


def test_raw_records_are_immutable_and_deterministic(memory):
    rid1 = memory.write_raw("lesson", "EURUSD.FX", {"note": "a"},
                            source="critic/0.1.0", timestamp=iso(NOW))
    rec1 = memory.get_raw(rid1)
    # identical content -> same deterministic id, written at most once
    rid2 = memory.write_raw("lesson", "EURUSD.FX", {"note": "a"},
                            source="critic/0.1.0", timestamp=iso(NOW))
    assert rid1 == rid2
    # the stored record is unchanged (immutable)
    assert memory.get_raw(rid1) == rec1
    assert rec1["source"] == "critic/0.1.0"
    assert rec1["kind"] == "lesson"


def test_raw_content_addressing_differs_on_change(memory):
    a = memory.write_raw("lesson", "EURUSD.FX", {"note": "a"}, source="s", timestamp=iso(NOW))
    b = memory.write_raw("lesson", "EURUSD.FX", {"note": "b"}, source="s", timestamp=iso(NOW))
    assert a != b


def test_versioned_derived_summaries(memory):
    k1, v1 = memory.write_derived("market_context", "EURUSD.FX",
                                  {"regime": "TRENDING"}, source="mi", timestamp=iso(NOW))
    k2, v2 = memory.write_derived("market_context", "EURUSD.FX",
                                  {"regime": "RANGING"}, source="mi", timestamp=iso(NOW))
    assert k1 == k2 and v1 == 1 and v2 == 2
    latest = memory.latest_derived("market_context", "EURUSD.FX")
    assert latest["version"] == 2 and latest["summary"]["regime"] == "RANGING"


def test_query_interface_filters(memory):
    memory.write_raw("agent_assessment", "EURUSD.FX", {"a": 1}, source="s",
                     timestamp=iso(NOW), correlation_id="c1")
    memory.write_raw("agent_assessment", "GBPUSD.FX", {"a": 2}, source="s",
                     timestamp=iso(NOW), correlation_id="c2")
    eur = memory.query(kind="agent_assessment", subject="EURUSD.FX")
    assert len(eur) == 1 and eur[0]["subject"] == "EURUSD.FX"
    c2 = memory.query(correlation_id="c2")
    assert len(c2) == 1 and c2[0]["subject"] == "GBPUSD.FX"


def test_memory_records_carry_timestamp_and_id(memory):
    rid = memory.write_raw("pnl", "EURUSD.FX", {"pnl": 12.5}, source="exec",
                           timestamp=iso(NOW))
    rec = memory.get_raw(rid)
    assert rec["id"] == rid and rec["timestamp"] == iso(NOW)


def test_memory_has_its_own_audit_trail(memory):
    memory.write_raw("pnl", "EURUSD.FX", {"pnl": 1}, source="exec", timestamp=iso(NOW))
    rows = memory.audit.read_all()
    assert any(r["action"] == "memory_write" for r in rows)
