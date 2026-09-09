"""PR-3A H1: a Position Manager may mark a position CLOSED only with POSITIVE
closure evidence (a confirmed netted-flat deal set). Absence, disconnect, broker
error, or unavailable history must NEVER mark CLOSED, and a false persisted CLOSED
must be correctable from broker truth on restart. Deterministic; MockMT5; no MT5."""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from forex_swing_orb.ea_mt5 import mock_mt5                                  # noqa: E402
from forex_swing_orb.ea_mt5.position_manager import PositionManager          # noqa: E402
from forex_swing_orb.position import spec, DEFAULT_PM_CONFIG                  # noqa: E402
from forex_swing_orb.position.contract import StopPhase, PMReason            # noqa: E402

NOW = datetime(2024, 1, 25, 12, 0, tzinfo=timezone.utc)
CFG = DEFAULT_PM_CONFIG
BUY = mock_mt5.ORDER_TYPE_BUY


def _rig(entry=1.1000, sl=1.0980, tp=1.1100, audit_path=None):
    m = mock_mt5.MockMT5(); m.add_symbol("EURUSD")
    res = m.order_send({"symbol": "EURUSD", "volume": 0.10, "type": BUY,
                        "price": entry, "sl": sl, "tp": tp, "comment": "sig"})
    path = audit_path or (Path(tempfile.mkdtemp()) / "pm.jsonl")
    pm = PositionManager(m, path, CFG)
    pm.register("sig", res.order, "EURUSD", "LONG", entry, sl, tp, NOW)
    return pm, m, res.order, path


def _be_price():
    R = spec.initial_risk("LONG", 1.1000, 1.0980)
    return 1.1000 + CFG.breakeven_trigger_r * R


# --------------------------------------------------------------------------- #
def test_transient_absence_does_not_mark_closed():
    pm, m, tk, _ = _rig()
    m.hide(tk)                                    # connected, but position transiently absent
    n = len(m.modify_log)
    r = pm.evaluate("sig", market_price=1.1005, now=NOW)
    assert r["reason_code"] == PMReason.RECONCILIATION_REQUIRED
    assert r["reconciliation_status"] == "position_absent_unconfirmed"
    assert pm.states["sig"]["phase"] != StopPhase.CLOSED
    assert len(m.modify_log) == n                 # no PM action during reconciliation


def test_resumes_normally_after_transient_absence():
    pm, m, tk, _ = _rig()
    m.hide(tk)
    assert pm.evaluate("sig", market_price=1.1005, now=NOW)["reason_code"] \
        == PMReason.RECONCILIATION_REQUIRED
    m.unhide(tk)                                  # position returns next cycle
    r = pm.evaluate("sig", market_price=1.1005, now=NOW)
    assert r["reason_code"] != PMReason.RECONCILIATION_REQUIRED
    assert pm.states["sig"]["phase"] != StopPhase.CLOSED


def test_confirmed_full_close_marks_closed():
    pm, m, tk, _ = _rig()
    m.positions[tk].closed = True                 # broker-side close -> deal history confirms
    r = pm.evaluate("sig", market_price=1.1005, now=NOW)
    assert r["reason_code"] == PMReason.POSITION_CLOSED
    assert r["phase"] == StopPhase.CLOSED
    assert r["reconciliation_status"] == "no_position_confirmed"


def test_disconnected_terminal_does_not_mark_closed():
    pm, m, tk, _ = _rig()
    m.connected = False
    r = pm.evaluate("sig", market_price=1.1005, now=NOW)
    assert r["reason_code"] == PMReason.DATA_STALE
    assert pm.states["sig"]["phase"] != StopPhase.CLOSED


def test_broker_exception_does_not_mark_closed():
    pm, m, tk, _ = _rig()

    def _raise(_ticket):
        raise mock_mt5.MT5Disconnected("boom")
    m.position_by_ticket = _raise                 # broker query raises
    r = pm.evaluate("sig", market_price=1.1005, now=NOW)
    assert r["reason_code"] == PMReason.DATA_STALE
    assert pm.states["sig"]["phase"] != StopPhase.CLOSED


def test_restart_false_closed_with_live_position_recovers_active():
    pm, m, tk, path = _rig()
    pm.evaluate("sig", market_price=_be_price(), now=NOW)   # -> BREAKEVEN (audited)
    # inject a FALSE persisted CLOSED audit record (as the old buggy path would)
    st = pm.states["sig"]; prev = st["phase"]; st["phase"] = StopPhase.CLOSED
    pm._emit(st, PMReason.POSITION_CLOSED, NOW, reconciliation_status="no_position")
    st["phase"] = prev
    # restart: broker still holds the live position -> must recover ACTIVE, not CLOSED
    pm2 = PositionManager(m, path, CFG)
    rec = pm2.recover("sig", NOW)
    assert rec["phase"] != StopPhase.CLOSED
    assert pm2.states["sig"]["phase"] != StopPhase.CLOSED


def test_restart_genuine_confirmed_close_stays_closed():
    pm, m, tk, path = _rig()
    m.positions[tk].closed = True                 # genuine close (deal history confirms)
    pm.evaluate("sig", market_price=1.1005, now=NOW)       # writes CLOSED
    pm2 = PositionManager(m, path, CFG)
    rec = pm2.recover("sig", NOW)
    assert rec["phase"] == StopPhase.CLOSED
    assert rec["reason_code"] == PMReason.POSITION_CLOSED
    assert rec["reconciliation_status"] == "no_position_confirmed"
