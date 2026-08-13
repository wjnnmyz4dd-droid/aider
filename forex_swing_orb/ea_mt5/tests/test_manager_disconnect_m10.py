"""PR-3I / M10 — manager mid-run disconnect never reads as "NO POSITIONS".

The manager evaluates its in-memory ``pm.states`` registry (not a broker position
list), and every cycle ``_reconcile`` checks ``terminal_connected()`` BEFORE any
read: a disconnect yields PM_DATA_STALE / ``terminal_disconnected`` with no stop
action, and even a connected-but-empty read requires POSITIVE deal-history closure
evidence before marking CLOSED. Reconnect resumes management with no restart and
no duplicate state. These prove M10 is already closed; NO production change is made.
Deterministic; MockMT5; no MT5.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from forex_swing_orb.ea_mt5 import mock_mt5
from forex_swing_orb.ea_mt5.position_manager import PositionManager
from forex_swing_orb.position import DEFAULT_PM_CONFIG
from forex_swing_orb.position.contract import StopPhase, PMReason

NOW = datetime(2024, 1, 25, 12, 0, tzinfo=timezone.utc)
CFG = DEFAULT_PM_CONFIG
BUY = mock_mt5.ORDER_TYPE_BUY


def _mkt():
    m = mock_mt5.MockMT5(); m.add_symbol("EURUSD")
    return m


def _open(m, sid, entry=1.1000, sl=1.0980, tp=1.1100):
    return m.order_send({"symbol": "EURUSD", "volume": 0.10, "type": BUY,
                         "price": entry, "sl": sl, "tp": tp, "comment": sid}).order


def _pm(m, path=None):
    return PositionManager(m, path or (Path(tempfile.mkdtemp()) / "pm.jsonl"), CFG)


def _rig(sid="sig"):
    m = _mkt(); tk = _open(m, sid)
    path = Path(tempfile.mkdtemp()) / "pm.jsonl"
    pm = _pm(m, path)
    pm.register(sid, tk, "EURUSD", "LONG", 1.1000, 1.0980, 1.1100, NOW)
    return pm, m, tk, path


# --------------------------------------------------------------------------- #
# 1 connected start: management proceeds normally
# --------------------------------------------------------------------------- #
def test_1_connected_management_proceeds():
    pm, m, _tk, _path = _rig()
    r = pm.evaluate("sig", market_price=1.1005, now=NOW)
    assert r["reason_code"] != PMReason.DATA_STALE
    assert pm.states["sig"]["phase"] != StopPhase.CLOSED


# --------------------------------------------------------------------------- #
# 2/3 mid-run disconnect: no false CLOSED, no stop modification
# --------------------------------------------------------------------------- #
def test_2_disconnect_no_false_closed():
    pm, m, _tk, _path = _rig()
    m.connected = False
    r = pm.evaluate("sig", market_price=1.1005, now=NOW)
    assert r["reason_code"] == PMReason.DATA_STALE
    assert pm.states["sig"]["phase"] != StopPhase.CLOSED


def test_3_disconnect_no_stop_modification():
    pm, m, _tk, _path = _rig()
    n = len(m.modify_log)
    m.connected = False
    pm.evaluate("sig", market_price=1.2000, now=NOW)     # a price that would trail
    assert len(m.modify_log) == n                        # never modifies while stale


# --------------------------------------------------------------------------- #
# 4 empty-due-to-disconnect is UNKNOWN, not truly empty
# --------------------------------------------------------------------------- #
def test_4_disconnect_is_unknown_not_empty():
    pm, m, tk, _path = _rig()
    m.connected = False
    disc = pm.evaluate("sig", market_price=1.1005, now=NOW)
    assert disc["reason_code"] == PMReason.DATA_STALE
    # a CONNECTED-but-absent read is also not "closed" without positive evidence
    m.connected = True; m.hide(tk)
    absent = pm.evaluate("sig", market_price=1.1005, now=NOW)
    assert absent["reason_code"] == PMReason.RECONCILIATION_REQUIRED
    assert pm.states["sig"]["phase"] != StopPhase.CLOSED


# --------------------------------------------------------------------------- #
# 5/6 reconnect: rediscovered + management resumes (no restart)
# --------------------------------------------------------------------------- #
def test_5_6_reconnect_resumes_management():
    pm, m, _tk, _path = _rig()
    m.connected = False
    assert pm.evaluate("sig", market_price=1.1005, now=NOW)["reason_code"] == PMReason.DATA_STALE
    m.connected = True                                   # terminal returns
    r = pm.evaluate("sig", market_price=1.1005, now=NOW)
    assert r["reason_code"] != PMReason.DATA_STALE       # resumes automatically
    assert pm.states["sig"]["phase"] != StopPhase.CLOSED


# --------------------------------------------------------------------------- #
# 7 restart during disconnect stays safe (recover fails closed, state kept)
# --------------------------------------------------------------------------- #
def test_7_restart_during_disconnect_safe():
    pm, m, tk, path = _rig()
    pm.evaluate("sig", market_price=1.1005, now=NOW)     # audited ACTIVE
    m.connected = False
    # restart: rebuild from the SAME audit path while the broker is disconnected
    pm2 = PositionManager(m, path, CFG)
    rec = pm2.recover("sig", NOW)
    assert rec["reason_code"] == PMReason.DATA_STALE
    assert rec.get("reconciliation_status") == "terminal_disconnected"
    assert pm2.states["sig"]["phase"] != StopPhase.CLOSED


# --------------------------------------------------------------------------- #
# 8 multi-ticket: one state not lost during disconnect
# --------------------------------------------------------------------------- #
def test_8_two_tickets_state_not_lost():
    m = _mkt(); pm = _pm(m)
    for sid, entry in (("a", 1.1000), ("b", 1.2000)):
        tk = _open(m, sid, entry=entry, sl=entry - 0.002, tp=entry + 0.004)
        pm.register(sid, tk, "EURUSD", "LONG", entry, entry - 0.002, entry + 0.004, NOW)
    m.connected = False
    for sid in ("a", "b"):
        assert pm.evaluate(sid, market_price=1.1005, now=NOW)["reason_code"] == PMReason.DATA_STALE
        assert sid in pm.states and pm.states[sid]["phase"] != StopPhase.CLOSED
    m.connected = True
    for sid in ("a", "b"):
        assert pm.evaluate(sid, market_price=1.1005, now=NOW)["reason_code"] != PMReason.DATA_STALE


# --------------------------------------------------------------------------- #
# 9 health surfaces the disconnected state
# --------------------------------------------------------------------------- #
def test_9_health_shows_disconnected():
    pm, m, _tk, _path = _rig()
    m.connected = False
    r = pm.evaluate("sig", market_price=1.1005, now=NOW)
    assert r["reconciliation_status"] == "terminal_disconnected"


# --------------------------------------------------------------------------- #
# 10 no duplicate PM state across reconnect cycles
# --------------------------------------------------------------------------- #
def test_10_no_duplicate_state_after_reconnect():
    pm, m, _tk, _path = _rig()
    before = len(pm.states)
    for connected in (False, True, False, True):
        m.connected = connected
        pm.evaluate("sig", market_price=1.1005, now=NOW)
    assert len(pm.states) == before == 1


# --------------------------------------------------------------------------- #
# property C — disconnect/exception can never turn a position CLOSED
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("mode", ["disconnect", "exception"])
def test_propC_unknown_never_becomes_closed(mode):
    pm, m, _tk, _path = _rig()
    if mode == "disconnect":
        m.connected = False
    else:
        def _raise(_t):
            raise mock_mt5.MT5Disconnected("boom")
        m.position_by_ticket = _raise
    r = pm.evaluate("sig", market_price=1.1005, now=NOW)
    assert r["reason_code"] == PMReason.DATA_STALE
    assert pm.states["sig"]["phase"] != StopPhase.CLOSED
