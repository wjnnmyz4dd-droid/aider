"""PR-3G.1 / G-1 — periodic broker-truth reconciliation of HELD execution state.

A transient/ambiguous execution outcome leaves the instruction HELD (claimed, no
terminal result, capacity-reserved). reconcile_held() re-resolves such items on the
normal poll cadence against AUTHORITATIVE broker truth WITHOUT ever resending:
  * broker holds the position -> finalize EXECUTED;
  * broker truth unknown / disconnect / error -> remain HELD (fail closed);
  * no position + no stronger terminal evidence -> remain HELD (never "definitely
    failed"); expiry alone never releases.
Restart recovery and periodic reconciliation share the same per-item logic.
Deterministic; mock MT5; no networking.
"""

from __future__ import annotations

from datetime import timedelta

from forex_swing_orb.bridge.contract import ResultState, ReasonCode
from forex_swing_orb.ea_mt5 import mock_mt5
from forex_swing_orb.ea_mt5.execution_consumer import instruction_name
from forex_swing_orb.producer.bridge_health import observe_entry_bridge
from ea_helpers import make_instruction, NOW

SID = "a1b2c3d4e5f60718"


def _write_pending(paths, rec):
    from forex_swing_orb.bridge import serialize
    from forex_swing_orb.bridge.atomic import atomic_write_text
    rec = serialize.with_integrity_digest(dict(rec))
    atomic_write_text(paths.pending / instruction_name(rec["signal_id"]), serialize.dumps(rec))


def _make_held(env, mt5, rec=None, retcode=mock_mt5.TRADE_RETCODE_TIMEOUT):
    """Produce a HELD (ambiguous) item: claimed file remains, no terminal result."""
    rec = rec or make_instruction()
    mt5.script(retcode)
    _write_pending(env.paths, rec)
    r = env.process_next(NOW)
    assert r["status"] == ReasonCode.RECONCILIATION_REQUIRED
    assert (env.paths.claimed / instruction_name(rec["signal_id"])).exists()
    return rec


def _pos(mt5, sid, ticket=90):
    mt5.positions[ticket] = mock_mt5.Position(
        ticket=ticket, symbol="EURUSD", type=mock_mt5.ORDER_TYPE_BUY, volume=0.10,
        price_open=1.10000, sl=1.09800, tp=1.10400, comment=sid)


# --------------------------------------------------------------------------- #
# 1-4: broker-truth outcomes
# --------------------------------------------------------------------------- #
def test_held_with_broker_position_finalizes_executed(env, mt5):
    _make_held(env, mt5)
    _pos(mt5, SID)                                   # broker actually holds it
    before = len(mt5.order_log)
    summary = env.reconcile_held(NOW)
    assert summary["recovered_from_broker"] == 1
    assert len(mt5.order_log) == before             # NEVER resent
    assert (env.paths.archive_accepted / instruction_name(SID)).exists()


def test_held_no_position_remains_held(env, mt5):
    _make_held(env, mt5)
    before = len(mt5.order_log)
    summary = env.reconcile_held(NOW)
    assert summary["reconciliation_required"] == 1
    assert len(mt5.order_log) == before
    assert (env.paths.claimed / instruction_name(SID)).exists()      # still HELD


def test_held_broker_disconnect_remains_held(env, mt5):
    _make_held(env, mt5)
    mt5.connected = False                            # broker truth unavailable
    before = len(mt5.order_log)
    env.reconcile_held(NOW)
    assert len(mt5.order_log) == before
    assert (env.paths.claimed / instruction_name(SID)).exists()      # HELD, no release


def test_held_broker_exception_remains_held(env, mt5):
    _make_held(env, mt5)
    orig = mt5.position_by_comment
    mt5.position_by_comment = lambda sid: (_ for _ in ()).throw(RuntimeError("boom"))
    before = len(mt5.order_log)
    summary = env.reconcile_held(NOW)
    mt5.position_by_comment = orig
    assert len(mt5.order_log) == before
    assert (env.paths.claimed / instruction_name(SID)).exists()      # HELD, fail closed


# --------------------------------------------------------------------------- #
# 5-6: no resend / idempotent passes (property A, E)
# --------------------------------------------------------------------------- #
def test_periodic_reconciliation_never_sends(env, mt5):
    _make_held(env, mt5)
    before = len(mt5.order_log)
    for _ in range(5):
        env.reconcile_held(NOW)                      # repeated passes
    assert len(mt5.order_log) == before             # zero order_send calls, ever


def test_repeated_passes_do_not_duplicate_execution(env, mt5):
    _make_held(env, mt5)
    _pos(mt5, SID)
    env.reconcile_held(NOW)                          # finalizes EXECUTED
    n_positions = len([p for p in mt5.positions.values() if p.comment == SID])
    for _ in range(3):
        env.reconcile_held(NOW)                      # further passes are no-ops
    assert len([p for p in mt5.positions.values() if p.comment == SID]) == n_positions == 1


# --------------------------------------------------------------------------- #
# 8-9: capacity + H5 while unresolved (property B)
# --------------------------------------------------------------------------- #
def test_capacity_reserved_while_held(env, mt5):
    _make_held(env, mt5)
    env.reconcile_held(NOW)                          # still no position
    obs = observe_entry_bridge(env.paths, NOW)
    assert obs.outstanding_count == 1               # HELD still reserves capacity
    assert SID in obs.outstanding_signal_ids


def test_h5_missing_ack_zero_while_held(env, mt5):
    _make_held(env, mt5)
    env.reconcile_held(NOW)
    obs = observe_entry_bridge(env.paths, NOW)
    assert obs.missing_ack_count == 0               # claimed = acknowledged (H5 intact)
    assert obs.healthy


# --------------------------------------------------------------------------- #
# 7: resolved EXECUTED leaves outstanding state correctly
# --------------------------------------------------------------------------- #
def test_resolved_executed_clears_outstanding(env, mt5):
    _make_held(env, mt5)
    _pos(mt5, SID)
    env.reconcile_held(NOW)
    obs = observe_entry_bridge(env.paths, NOW)
    assert obs.outstanding_count == 0               # archived; broker position is now authority
    assert not (env.paths.claimed / instruction_name(SID)).exists()


# --------------------------------------------------------------------------- #
# 10: restart uses the same logic
# --------------------------------------------------------------------------- #
def test_restart_and_periodic_same_result(env, mt5):
    _make_held(env, mt5)
    _pos(mt5, SID)
    before = len(mt5.order_log)
    summary = env.recover(NOW)                       # restart path, same shared helper
    assert summary["recovered_from_broker"] == 1
    assert len(mt5.order_log) == before             # restart also never resends here
    assert (env.paths.archive_accepted / instruction_name(SID)).exists()


# --------------------------------------------------------------------------- #
# 11-12: multi-item isolation
# --------------------------------------------------------------------------- #
def test_two_held_one_resolves_one_remains(env, mt5):
    a = make_instruction(signal_id="aaaa1111aaaa1111")
    b = make_instruction(signal_id="bbbb2222bbbb2222")
    _make_held(env, mt5, rec=a)
    _make_held(env, mt5, rec=b)
    _pos(mt5, "aaaa1111aaaa1111", ticket=101)        # only A has a broker position
    summary = env.reconcile_held(NOW)
    assert summary["recovered_from_broker"] == 1 and summary["reconciliation_required"] == 1
    assert (env.paths.archive_accepted / instruction_name("aaaa1111aaaa1111")).exists()
    assert (env.paths.claimed / instruction_name("bbbb2222bbbb2222")).exists()   # B still HELD


def test_one_lookup_fault_does_not_block_siblings(env, mt5):
    a = make_instruction(signal_id="aaaa1111aaaa1111")
    b = make_instruction(signal_id="bbbb2222bbbb2222")
    _make_held(env, mt5, rec=a)
    _make_held(env, mt5, rec=b)
    _pos(mt5, "bbbb2222bbbb2222", ticket=102)        # B resolvable
    orig = mt5.position_by_comment

    def flaky(sid):
        if sid == "aaaa1111aaaa1111":
            raise RuntimeError("lookup boom")
        return orig(sid)
    mt5.position_by_comment = flaky
    summary = env.reconcile_held(NOW)
    mt5.position_by_comment = orig
    # B still resolved despite A's lookup fault
    assert (env.paths.archive_accepted / instruction_name("bbbb2222bbbb2222")).exists()
    assert (env.paths.claimed / instruction_name("aaaa1111aaaa1111")).exists()   # A held


# --------------------------------------------------------------------------- #
# 13-14: expiry / no-position do not terminalize without proof
# --------------------------------------------------------------------------- #
def test_expiry_alone_does_not_release_held(env, mt5):
    rec = make_instruction(expiration=NOW + timedelta(minutes=5),
                           generated=NOW - timedelta(minutes=15))
    _make_held(env, mt5, rec=rec)
    later = NOW + timedelta(hours=2)                 # now past expiration
    env.reconcile_held(later)
    assert (env.paths.claimed / instruction_name(SID)).exists()      # still HELD, not released
    assert not (env.paths.archive_rejected / instruction_name(SID)).exists()


def test_no_position_never_terminalizes_as_failed(env, mt5):
    _make_held(env, mt5)
    env.reconcile_held(NOW)
    # no EXECUTION_FAILED / no rejected archive written from absence-of-position
    assert not (env.paths.archive_rejected / instruction_name(SID)).exists()
    results = list(env.paths.results.glob("*.json"))
    assert not any("EXECUTION_FAILED" in p.read_text() for p in results)


# --------------------------------------------------------------------------- #
# 15: cadence bounded (one pass, no tight loop)
# --------------------------------------------------------------------------- #
def test_poll_is_single_bounded_pass(env, mt5):
    _make_held(env, mt5)
    out = env.poll(NOW)                              # one tick: reconcile + process_next
    assert "held_reconcile" in out and "processed" in out
    assert (env.paths.claimed / instruction_name(SID)).exists()      # unresolved -> still HELD
