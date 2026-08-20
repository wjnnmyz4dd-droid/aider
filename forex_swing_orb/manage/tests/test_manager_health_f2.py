"""F2 (manager side) — the manager stamps the canonical service-health envelope on
every cycle, so runtime.service_health can prove the manager process is recently
alive; and the F1 refusal path leaves the active manager's health untouched.
Deterministic; wired mock terminal; no networking.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from forex_swing_orb.runtime import service_health as sh
from conftest import NOW


def test_manager_write_health_stamps_envelope(wired, long_pos):
    sid, ticket = long_pos()
    wired["manager"].run_cycle(NOW, market={ticket: 1.10200})     # writes manager_health.json
    hp = Path(wired["manager"].health_path)
    assert hp.exists()
    r = sh.read_service_health(hp, sh.MANAGER, NOW)
    assert r.state == sh.PASS and r.ok                            # fresh + correct service
    # a later reader beyond the freshness window sees it STALE (dead-manager scenario)
    later = NOW + timedelta(seconds=sh.freshness_limit(900) + 120)
    assert sh.read_service_health(hp, sh.MANAGER, later).state == sh.STALE


def test_manager_health_wrong_service_guard(wired, long_pos):
    sid, ticket = long_pos()
    wired["manager"].run_cycle(NOW, market={ticket: 1.10200})
    hp = Path(wired["manager"].health_path)
    # the manager artifact must not be accepted as producer health
    assert sh.read_service_health(hp, sh.PRODUCER, NOW).state == sh.WRONG_SERVICE


def test_f1_refused_manager_does_not_touch_health(wired, long_pos, monkeypatch, tmp_path):
    # F1 interaction: a second manager refused by the ownership lock performs no work
    # and does not write/clobber the active manager's health artifact.
    from forex_swing_orb.manage import __main__ as M
    from forex_swing_orb.manage.manager_lock import ManagerLock

    # active manager writes a fresh health artifact
    sid, ticket = long_pos()
    wired["manager"].run_cycle(NOW, market={ticket: 1.10200})
    hp = Path(wired["manager"].health_path)
    before = hp.read_text(encoding="utf-8")

    # a second manager main() on the same domain is refused (lock held) and writes nothing
    class _Svc:
        paths = wired["mpaths"]
        _truth = type("T", (), {"terminal_connected": lambda self: True})()
        _cadence_sec = 900
    monkeypatch.setattr(M.ManagerService, "build_from_env", classmethod(lambda cls: _Svc()))
    monkeypatch.setattr(M, "_preflight", lambda s: None)
    owner = ManagerLock(wired["mpaths"].root).acquire()
    try:
        rc = M.main([])
    finally:
        owner.release()
    assert rc == 4
    assert hp.read_text(encoding="utf-8") == before                # active health untouched
