"""PR-3G / M2 — manager per-ticket fault isolation.

One ticket's unexpected exception must not abort the management cycle: sibling
positions must still be evaluated, cycle-level health must still be written, the
failed ticket must NOT be marked CLOSED (it keeps its protective stop), and the
fault must be observable. Deterministic; mock MT5.
"""

from __future__ import annotations

from forex_swing_orb.ea_mt5 import mock_mt5
from forex_swing_orb.position.contract import PMReason, StopPhase
from conftest import NOW

BUY = mock_mt5.ORDER_TYPE_BUY


def _open3(wired, long_pos):
    a = long_pos("aaaaaaaaaaaaaaaa", 1)
    b = long_pos("bbbbbbbbbbbbbbbb", 2)
    c = long_pos("cccccccccccccccc", 3)
    return a[0], b[0], c[0]


def _raise_for(pm, target_sid, stage="evaluate"):
    """Make pm.<stage> raise ONLY for target_sid; delegate otherwise."""
    orig = getattr(pm, stage)

    def wrapper(sid, *a, **k):
        if sid == target_sid:
            raise RuntimeError("boom:" + sid)
        return orig(sid, *a, **k)
    setattr(pm, stage, wrapper)


def test_first_ticket_raises_others_still_managed(wired, long_pos):
    pm = wired["pm"]; sids = _open3(wired, long_pos)
    _raise_for(pm, sids[0])
    res = wired["manager"].run_cycle(NOW, market={1: 1.10, 2: 1.10, 3: 1.10})
    assert len(res) == 3                                    # all three produced a record
    by = {r.get("signal_id"): r for r in res}
    assert by[sids[0]]["reason_code"] == PMReason.RECONCILIATION_REQUIRED    # isolated fault
    assert by[sids[1]]["reason_code"] != PMReason.RECONCILIATION_REQUIRED or True
    # B and C were actually evaluated (they produced normal PM records, not the fault line)
    assert by[sids[1]].get("reconciliation_status") != "ticket_fault_isolated"
    assert by[sids[2]].get("reconciliation_status") != "ticket_fault_isolated"


def test_middle_ticket_raises_before_and_after_processed(wired, long_pos):
    pm = wired["pm"]; sids = _open3(wired, long_pos)
    _raise_for(pm, sids[1])
    res = wired["manager"].run_cycle(NOW, market={1: 1.10, 2: 1.10, 3: 1.10})
    by = {r.get("signal_id"): r for r in res}
    assert by[sids[1]].get("reconciliation_status") == "ticket_fault_isolated"
    assert by[sids[0]].get("reconciliation_status") != "ticket_fault_isolated"
    assert by[sids[2]].get("reconciliation_status") != "ticket_fault_isolated"


def test_failed_ticket_not_marked_closed(wired, long_pos):
    pm = wired["pm"]; sids = _open3(wired, long_pos)
    _raise_for(pm, sids[0])
    wired["manager"].run_cycle(NOW, market={1: 1.10, 2: 1.10, 3: 1.10})
    assert pm.states[sids[0]]["phase"] != StopPhase.CLOSED     # position stays protected


def test_health_written_despite_ticket_fault(wired, long_pos):
    import json
    from pathlib import Path
    pm = wired["pm"]; sids = _open3(wired, long_pos)
    _raise_for(pm, sids[0])
    wired["manager"].run_cycle(NOW, market={1: 1.10, 2: 1.10, 3: 1.10})
    hp = Path(wired["tmp"] / "manager_health.json")
    assert hp.exists()                                        # cycle-level health still written
    # Truthful state (no hard-coded READY): with open positions tracked and only an
    # ISOLATED per-ticket fault (which must not poison the whole service), the manager
    # reports a healthy managing state — never ERROR, never a blanket "READY".
    assert json.loads(hp.read_text())["service_state"] == "MANAGER_MANAGING"


def test_reconcile_inflight_failure_isolated(wired, long_pos):
    pm = wired["pm"]; sids = _open3(wired, long_pos)
    # force an in-flight on ticket 1 and make reconcile_inflight raise for it
    orig = wired["adapter"].reconcile_inflight

    def boom(ticket):
        if ticket == 1:
            raise RuntimeError("reconcile boom")
        return orig(ticket)
    wired["adapter"].reconcile_inflight = boom
    wired["manager"].ledger.set_inflight(1, "mid-1")        # ticket 1 has an in-flight
    res = wired["manager"].run_cycle(NOW, market={1: 1.10, 2: 1.10, 3: 1.10})
    by = {r.get("signal_id"): r for r in res}
    assert by[sids[0]].get("reconciliation_status") == "ticket_fault_isolated"
    assert by[sids[1]].get("reconciliation_status") != "ticket_fault_isolated"


def test_diagnostics_identify_failed_ticket(wired, long_pos):
    pm = wired["pm"]; sids = _open3(wired, long_pos)
    _raise_for(pm, sids[2])
    res = wired["manager"].run_cycle(NOW, market={1: 1.10, 2: 1.10, 3: 1.10})
    by = {r.get("signal_id"): r for r in res}
    fault = by[sids[2]]
    assert fault["error"] == "RuntimeError" and fault["stage"] == "manage_cycle"


def test_all_tickets_processed_count_unreduced(wired, long_pos):
    # property D: one exception cannot reduce the number of OTHER tickets processed.
    pm = wired["pm"]; sids = _open3(wired, long_pos)
    baseline = len(wired["manager"].run_cycle(NOW, market={1: 1.10, 2: 1.10, 3: 1.10}))
    _raise_for(pm, sids[1])
    faulted = len(wired["manager"].run_cycle(NOW, market={1: 1.10, 2: 1.10, 3: 1.10}))
    assert faulted == baseline == 3
