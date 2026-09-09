"""M-5 crash-recovery / stranded in-flight management fix (Phase 7B-B).

Reproduces and fixes the HIGH-severity defect where the live management path
persists an in-flight marker (``ledger.set_inflight``) BEFORE the manage
instruction is durably written (``write_manage_instruction``). A crash in that
window leaves a persisted in-flight entry whose ``manage_id`` exists NOWHERE in
the bridge (no pending/claimed/archived instruction, no result). Nothing ever
reached the EA/broker, yet the one-in-flight guard blocks the ticket from ALL
future management (BE, stop tighten, trail, protective close, Friday flatten)
forever.

Invariant under test: a persisted in-flight must correspond to (A) a durable
recoverable instruction, (B) a terminal result, or (C) an actively recoverable
broker-state path. A proven orphan (absence everywhere) must self-heal — cleared
so the PositionManager re-decides fresh through the normal broker-verified emit
path — and must never trigger a duplicate broker action.

No PM arithmetic, no close-confirmation change (M-6 separate), no manage_id
change (M-4 separate). Mock terminal only; no networking; no real MT5.
"""

from __future__ import annotations

import pytest

from forex_swing_orb.bridge import serialize
from forex_swing_orb.ea_mt5 import mock_mt5
from forex_swing_orb.manage import ManageStatus, write_manage_instruction
from forex_swing_orb.position.contract import StopPhase
from conftest import NOW

# A syntactically valid but never-emitted manage_id (16 hex): the crash left this
# marker in the ledger, but no instruction with this id was ever written.
ORPHAN_MID = "a1b2c3d4e5f60718"


def _strand(wired, ticket, mid=ORPHAN_MID):
    """Simulate the M-5 crash: an in-flight marker persisted with NO instruction
    ever written to the bridge (crash between set_inflight and the atomic write)."""
    wired["adapter"].ledger.set_inflight(ticket, mid)
    assert wired["adapter"].ledger.get_inflight(ticket) == mid
    # prove the orphan: the id exists nowhere durable in the bridge
    assert not list(wired["mpaths"].pending.glob("*.json"))
    assert not list(wired["mpaths"].claimed.glob("*.json"))
    assert not list(wired["mpaths"].results.glob("*.json"))


# --- core reproduction + self-heal ------------------------------------------
def test_m5_orphan_inflight_self_heals_on_management_cycle(wired, long_pos):
    """REPRODUCES M-5: after the crash orphan, a +1R management cycle must still
    move the stop to breakeven (the orphan self-heals instead of stranding)."""
    sid, ticket = long_pos()
    _strand(wired, ticket)

    # +1R: normally triggers the BE stop move. Pre-fix this is swallowed by the
    # stale in-flight guard (pm.recover), leaving the stop frozen forever.
    wired["manager"].run_cycle(NOW, market={ticket: 1.10200})

    assert wired["adapter"].ledger.get_inflight(ticket) is None      # orphan cleared
    assert wired["mt5"].positions[ticket].sl > 1.09800               # BE applied
    assert wired["pm"].states[sid]["phase"] == StopPhase.BREAKEVEN


def test_m5_orphan_clear_causes_no_duplicate_broker_action(wired, long_pos):
    """The orphan carried no broker action (nothing was ever written); after the
    self-heal exactly ONE instruction is emitted for the fresh decision."""
    sid, ticket = long_pos()
    _strand(wired, ticket)
    wired["manager"].run_cycle(NOW, market={ticket: 1.10200})

    # exactly one terminal result for the (single) fresh BE emit — no duplicate.
    results = list(wired["mpaths"].results.glob("*.json"))
    assert len(results) == 1
    # the fresh instruction is NOT the orphan id
    assert ORPHAN_MID not in results[0].name
    # archived once to the applied family (single applied broker action)
    assert len(list(wired["mpaths"].archive_applied.glob("*.json"))) == 1


def test_m5_orphan_reconcile_clears_directly(wired, long_pos):
    """reconcile_inflight itself clears a proven orphan (the seam the cycle uses)."""
    sid, ticket = long_pos()
    _strand(wired, ticket)
    out = wired["adapter"].reconcile_inflight(ticket)
    assert out is None
    assert wired["adapter"].ledger.get_inflight(ticket) is None


# --- guard: genuine in-flight must NOT be cleared ---------------------------
def test_m5_genuine_pending_instruction_not_cleared(wired, long_pos):
    """A real, unprocessed instruction in pending/ is a genuine in-flight (its id
    IS in the bridge) and must NOT be mistaken for an orphan."""
    sid, ticket = long_pos()
    # drive one real emit but do not let it resolve (no pump) -> instruction sits
    # in pending, in-flight persists legitimately.
    wired["adapter"]._pump = None
    wired["adapter"].timeout_sec = 1
    wired["adapter"].modify_stop(ticket, 1.10020)
    mid = wired["adapter"].ledger.get_inflight(ticket)
    assert mid is not None
    assert list(wired["mpaths"].pending.glob("*.json"))               # real instruction present

    out = wired["adapter"].reconcile_inflight(ticket)
    assert out is None
    assert wired["adapter"].ledger.get_inflight(ticket) == mid        # preserved, NOT cleared


def test_m5_bridge_has_positive_for_each_durable_location(wired, long_pos):
    """_bridge_has must return True whenever the id exists in any durable location
    (pending/claimed/archives/results) so those are never treated as orphans."""
    sid, ticket = long_pos()
    ad = wired["adapter"]
    mp = wired["mpaths"]
    # pending
    (mp.pending / "1111111111111111.json").write_text("{}", encoding="utf-8")
    assert ad._bridge_has("1111111111111111") is True
    # claimed
    (mp.claimed / "2222222222222222.json").write_text("{}", encoding="utf-8")
    assert ad._bridge_has("2222222222222222") is True
    # archives
    (mp.archive_applied / "3333333333333333.json").write_text("{}", encoding="utf-8")
    assert ad._bridge_has("3333333333333333") is True
    (mp.archive_rejected / "4444444444444444.json").write_text("{}", encoding="utf-8")
    assert ad._bridge_has("4444444444444444") is True
    (mp.archive_closed / "5555555555555555.json").write_text("{}", encoding="utf-8")
    assert ad._bridge_has("5555555555555555") is True
    # result
    (mp.results / "6666666666666666.abc.json").write_text("{}", encoding="utf-8")
    assert ad._bridge_has("6666666666666666") is True
    # genuinely absent
    assert ad._bridge_has("7777777777777777") is False


def test_m5_terminal_result_still_records_not_orphan(wired, long_pos):
    """When a terminal result DID arrive but in-flight lingered, reconcile must
    record the terminal (the pre-existing converged path) — not clear as orphan."""
    sid, ticket = long_pos()
    # a real modify resolves to a terminal APPLIED result and clears in-flight,
    # then we re-arm in-flight to the SAME id to simulate a lingering marker.
    wired["adapter"].modify_stop(ticket, 1.10020)
    results = list(wired["mpaths"].results.glob("*.json"))
    assert len(results) == 1
    mid = serialize.loads(results[0].read_text(encoding="utf-8"))[1]["manage_id"]
    wired["adapter"].ledger.set_inflight(ticket, mid)                 # lingering marker

    out = wired["adapter"].reconcile_inflight(ticket)
    assert out == ManageStatus.APPLIED                               # recorded terminal
    assert wired["adapter"].ledger.get_inflight(ticket) is None
    # no NEW result created by the reconcile (idempotent)
    assert len(list(wired["mpaths"].results.glob("*.json"))) == 1


# --- recover_orphans sweep --------------------------------------------------
def test_m5_recover_orphans_sweep_clears_only_orphans(wired, long_pos):
    """recover_orphans clears proven orphans and leaves genuine in-flight."""
    sid, ticket = long_pos()
    # a second tracked ticket with a genuine (pending) in-flight
    sid2, ticket2 = long_pos(signal_id="fedcba9876543210", ticket=5000002)
    wired["adapter"]._pump = None
    wired["adapter"].timeout_sec = 1
    wired["adapter"].modify_stop(ticket2, 1.10020)                   # genuine pending
    genuine_mid = wired["adapter"].ledger.get_inflight(ticket2)
    assert genuine_mid is not None
    # first ticket: crash orphan
    wired["adapter"].ledger.set_inflight(ticket, ORPHAN_MID)

    cleared = wired["adapter"].recover_orphans(NOW)

    assert str(ticket) in {str(c) for c in cleared}
    assert wired["adapter"].ledger.get_inflight(ticket) is None      # orphan gone
    assert wired["adapter"].ledger.get_inflight(ticket2) == genuine_mid  # genuine kept


def test_m5_service_run_once_sweeps_orphans(wired, long_pos):
    """service.run_once must run the orphan sweep so a crash orphan is healed at
    the top of the autonomous cycle even before per-ticket evaluation."""
    sid, ticket = long_pos()
    wired["adapter"].ledger.set_inflight(ticket, ORPHAN_MID)
    # no _truth wired -> run_once takes the run_cycle path, but the orphan sweep
    # runs first regardless of the truth source.
    wired["manager"].run_once(NOW)
    assert wired["adapter"].ledger.get_inflight(ticket) is None


# --- protective close orphan ------------------------------------------------
def test_m5_protective_close_orphan_self_heals(wired, long_pos):
    """A crash orphan must not block an authorized (kill-switch) protective close."""
    sid, ticket = long_pos()
    _strand(wired, ticket)
    wired["manager"].run_cycle(NOW, market={ticket: 1.10100}, kill_switch=True)
    assert wired["adapter"].ledger.get_inflight(ticket) is None
    assert wired["mt5"].positions[ticket].closed is True


# --- observability ----------------------------------------------------------
def test_m5_orphan_clear_emits_audit_diagnostic(wired, long_pos):
    sid, ticket = long_pos()
    _strand(wired, ticket)
    wired["adapter"].reconcile_inflight(ticket)
    log = wired["mpaths"].audit_log
    assert log.exists()
    lines = [serialize.loads(l)[1] for l in log.read_text(encoding="utf-8").splitlines() if l.strip()]
    orphan_lines = [r for r in lines if r.get("kind") == "manage_orphan_cleared"]
    assert orphan_lines
    assert orphan_lines[0]["manage_id"] == ORPHAN_MID
    assert str(ticket) == str(orphan_lines[0]["ticket"])


# --- idempotency ------------------------------------------------------------
def test_m5_reconcile_orphan_idempotent(wired, long_pos):
    sid, ticket = long_pos()
    _strand(wired, ticket)
    assert wired["adapter"].reconcile_inflight(ticket) is None
    # second call on an already-cleared ticket is a harmless no-op
    assert wired["adapter"].reconcile_inflight(ticket) is None
    assert wired["adapter"].ledger.get_inflight(ticket) is None
