"""F2 producer/manager health-artifact staleness / false-green readiness fix.

EA liveness already fails closed on a stale heartbeat; the producer and manager
health artifacts did not have equivalent age validation, so a dead process whose
health file lingered could read as current. This adds ONE canonical reader
(runtime.service_health) that classifies producer/manager health-artifact freshness
from a cadence-derived window (the same architectural principle as ea_liveness, kept
SEPARATE from EA liveness and H5), and threads it into readiness so stale health can
never satisfy SYSTEM READY. Freshness != eligibility: a blocked-but-alive service
still refreshes its artifact and reads FRESH.

Deterministic; injected clock; no networking; no real MT5.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from forex_swing_orb.bridge import serialize                              # noqa: E402
from forex_swing_orb.bridge.atomic import atomic_write_text               # noqa: E402
from forex_swing_orb.runtime import service_health as sh                  # noqa: E402
from forex_swing_orb.runtime import operator_status as ops               # noqa: E402

NOW = datetime(2026, 1, 7, 10, 0, 0, tzinfo=timezone.utc)
CADENCE = 900


def _write(path, service, now=NOW, cadence=CADENCE, **over):
    env = sh.stamp(service, now, cadence)
    env.update(over)
    atomic_write_text(Path(path), serialize.canonical_json(env))
    return Path(path)


# ============================================================================
# READER — freshness classification (mirrors ea_liveness, separate owner)
# ============================================================================
def test_1_8_fresh_health_passes(tmp_path):
    p = _write(tmp_path / "producer_health.json", sh.PRODUCER)
    r = sh.read_service_health(p, sh.PRODUCER, NOW)
    assert r.state == sh.PASS and r.ok
    m = _write(tmp_path / "manager_health.json", sh.MANAGER)
    assert sh.read_service_health(m, sh.MANAGER, NOW).ok


def test_2_9_stale_health_is_stale(tmp_path):
    old = NOW - timedelta(seconds=sh.freshness_limit(CADENCE) + 60)
    p = _write(tmp_path / "producer_health.json", sh.PRODUCER, now=old)
    r = sh.read_service_health(p, sh.PRODUCER, NOW)
    assert r.state == sh.STALE and not r.ok
    m = _write(tmp_path / "manager_health.json", sh.MANAGER, now=old)
    assert sh.read_service_health(m, sh.MANAGER, NOW).state == sh.STALE


def test_3_10_missing_health(tmp_path):
    assert sh.read_service_health(tmp_path / "nope.json", sh.PRODUCER, NOW).state == sh.MISSING


def test_4_11_malformed_health(tmp_path):
    p = tmp_path / "producer_health.json"
    p.write_text("{ not json", encoding="utf-8")
    assert sh.read_service_health(p, sh.PRODUCER, NOW).state == sh.MALFORMED
    p.write_text("[]", encoding="utf-8")                      # valid JSON, not a dict
    assert sh.read_service_health(p, sh.PRODUCER, NOW).state == sh.MALFORMED


def test_5_future_timestamp_not_pass(tmp_path):
    fut = NOW + timedelta(seconds=sh.freshness_limit(CADENCE) + 600)
    p = _write(tmp_path / "producer_health.json", sh.PRODUCER, now=fut)
    assert sh.read_service_health(p, sh.PRODUCER, NOW).state == sh.STALE


def test_30_wrong_service_identity(tmp_path):
    p = _write(tmp_path / "producer_health.json", sh.MANAGER)     # manager artifact...
    assert sh.read_service_health(p, sh.PRODUCER, NOW).state == sh.WRONG_SERVICE  # ...read as producer


def test_unknown_schema(tmp_path):
    p = _write(tmp_path / "producer_health.json", sh.PRODUCER, schema_version=999)
    assert sh.read_service_health(p, sh.PRODUCER, NOW).state == sh.UNKNOWN_SCHEMA
    p2 = _write(tmp_path / "p2.json", sh.PRODUCER, health_artifact="something_else")
    assert sh.read_service_health(p2, sh.PRODUCER, NOW).state == sh.UNKNOWN_SCHEMA


@pytest.mark.parametrize("bad", [None, "not-a-date", 12345, ""])
def test_26_27_28_bad_timestamp(tmp_path, bad):
    p = _write(tmp_path / "producer_health.json", sh.PRODUCER, generated_timestamp=bad)
    assert sh.read_service_health(p, sh.PRODUCER, NOW).state == sh.MALFORMED


def test_naive_timestamp_rejected(tmp_path):
    # a naive (tz-less) timestamp cannot be trusted for a UTC-age computation
    naive = "2026-01-07T10:00:00"                              # no offset/Z
    p = _write(tmp_path / "producer_health.json", sh.PRODUCER, generated_timestamp=naive)
    st = sh.read_service_health(p, sh.PRODUCER, NOW).state
    assert st in (sh.MALFORMED, sh.STALE) and st != sh.PASS


# ============================================================================
# FRESHNESS FORMULA — cadence-derived, never an arbitrary long timeout
# ============================================================================
def test_freshness_formula():
    assert sh.freshness_limit(900) == max(sh.MIN_FRESH_FLOOR_SEC, 900 * sh.FRESH_MULT)
    assert sh.freshness_limit(1) == sh.MIN_FRESH_FLOOR_SEC     # floor dominates tiny cadence
    assert sh.freshness_limit(0) >= sh.MIN_FRESH_FLOOR_SEC     # invalid -> safe default
    assert sh.freshness_limit(None) >= sh.MIN_FRESH_FLOOR_SEC


def test_stamp_envelope_shape():
    env = sh.stamp(sh.PRODUCER, NOW, 900)
    assert env["service"] == sh.PRODUCER
    assert env["health_artifact"] == sh.HEALTH_ARTIFACT
    assert env["schema_version"] == sh.HEALTH_SCHEMA
    assert env["generated_timestamp"] == serialize.iso_utc(NOW)
    assert env["health_cadence_sec"] == 900
    assert isinstance(env.get("pid"), int)


# ============================================================================
# READINESS AGGREGATION — stale health prevents SYSTEM READY
# ============================================================================
def _ready_bridge():
    return {"ready": True, "state": ops.BRIDGE_END_TO_END_READY, "blockers": ()}


def _ok_producer():
    return ops.producer_state(True, {"outcome": "NO_CANDIDATE"})   # WAITING (alive, benign)


def _ok_manager():
    return ops.manager_state(True, {"terminal_connected": True})


def test_17_both_fresh_health_does_not_block_ready():
    r = ops.system_readiness(bridge_e2e=_ready_bridge(), producer=_ok_producer(),
                             manager=_ok_manager(), producer_health=sh.PASS,
                             manager_health=sh.PASS)
    assert r["ready"] is True


def test_15_stale_producer_health_blocks_ready():
    r = ops.system_readiness(bridge_e2e=_ready_bridge(), producer=_ok_producer(),
                             manager=_ok_manager(), producer_health=sh.STALE,
                             manager_health=sh.PASS)
    assert r["ready"] is False
    assert any("producer health" in b.lower() for b in r["blockers"])


def test_16_stale_manager_health_blocks_ready():
    r = ops.system_readiness(bridge_e2e=_ready_bridge(), producer=_ok_producer(),
                             manager=_ok_manager(), producer_health=sh.PASS,
                             manager_health=sh.STALE)
    assert r["ready"] is False
    assert any("manager health" in b.lower() for b in r["blockers"])


def test_missing_health_blocks_ready():
    r = ops.system_readiness(bridge_e2e=_ready_bridge(), producer=_ok_producer(),
                             manager=_ok_manager(), producer_health=sh.MISSING,
                             manager_health=sh.PASS)
    assert r["ready"] is False


def test_health_none_preserves_prior_behavior():
    # default None = health not evaluated by this caller -> no new blocker (back-compat)
    r = ops.system_readiness(bridge_e2e=_ready_bridge(), producer=_ok_producer(),
                             manager=_ok_manager())
    assert r["ready"] is True


# ============================================================================
# BLOCKED-BUT-ALIVE — freshness is independent of eligibility
# ============================================================================
def test_6_7_blocked_producer_but_fresh_artifact_is_alive(tmp_path):
    # a producer blocked by NEWS/DATA/NO_CANDIDATE still refreshes its artifact:
    # health freshness is PASS even though the last cycle is not trade-ready.
    p = _write(tmp_path / "producer_health.json", sh.PRODUCER,
               service_state="PRODUCER_BLOCKED", last_reason="NEWS_REJECTED")
    assert sh.read_service_health(p, sh.PRODUCER, NOW).state == sh.PASS


# ============================================================================
# STARTUP GRACE
# ============================================================================
def test_20_21_22_startup_grace(tmp_path):
    spawned = NOW
    # within grace + missing -> STARTING (launcher-side helper), not a hard failure
    assert sh.within_startup_grace(spawned, NOW, CADENCE) is True
    later = NOW + timedelta(seconds=sh.startup_grace_sec(CADENCE) + 30)
    assert sh.within_startup_grace(spawned, later, CADENCE) is False
    # once a fresh artifact exists, freshness supersedes grace
    p = _write(tmp_path / "producer_health.json", sh.PRODUCER, now=later)
    assert sh.read_service_health(p, sh.PRODUCER, later).state == sh.PASS


# ============================================================================
# PREFLIGHT — reports Producer/Manager Health explicitly (no fake green)
# ============================================================================
def test_preflight_health_checks(tmp_path, monkeypatch):
    from forex_swing_orb.runtime import preflight as pf

    class _Cfg:
        producer_health_path = str(tmp_path / "producer_health.json")
        manager_health_path = str(tmp_path / "manager_health.json")
        cadence_sec = CADENCE

    cfg = _Cfg()
    # fresh producer, stale manager
    _write(cfg.producer_health_path, sh.PRODUCER)
    _write(cfg.manager_health_path, sh.MANAGER,
           now=NOW - timedelta(seconds=sh.freshness_limit(CADENCE) + 120))
    pr = pf._check_producer_health(cfg, NOW)
    mr = pf._check_manager_health(cfg, NOW)
    assert pr[1] == pf.PASS
    assert mr[1] == pf.FAIL and "STALE" in mr[2].upper()      # stale -> FAIL blocker
    # missing -> not a false green
    import os
    os.remove(cfg.manager_health_path)
    assert pf._check_manager_health(cfg, NOW)[1] in (pf.ENV, pf.FAIL)


def test_preflight_run_checks_includes_health(tmp_path, monkeypatch):
    from forex_swing_orb.runtime import preflight as pf
    names = {n for (n, _s, _d) in pf.run_checks(NOW)}
    assert any("producer health" in n.lower() for n in names)
    assert any("manager health" in n.lower() for n in names)


# ============================================================================
# SEPARATION — EA liveness and H5 unchanged / independent
# ============================================================================
def test_18_19_health_is_separate_owner():
    from forex_swing_orb.runtime import ea_liveness as el
    # distinct artifact identities and distinct modules (no merge)
    assert sh.HEALTH_ARTIFACT != el.EA_STATUS_ARTIFACT
    assert sh.__name__ != el.__name__
