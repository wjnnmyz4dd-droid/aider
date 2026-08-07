"""PR-1 read-only execution-outcome reconciliation tests (no networking; no real
MT5). Deterministic fakes; the reconciler only READS broker truth + PM audit and
WRITES the shared MemoryStore — it never opens/closes/modifies a position."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from forex_swing_orb.agents.memory import MemoryStore                       # noqa: E402
from forex_swing_orb.bridge import serialize                               # noqa: E402
from forex_swing_orb.live import mt5_client as mc                          # noqa: E402
from forex_swing_orb.manage.outcome import OutcomeReconciler               # noqa: E402
from forex_swing_orb.manage.service import ManagerService                  # noqa: E402
from forex_swing_orb.runtime.truth import Mt5TruthSource                   # noqa: E402

NOW = datetime(2026, 1, 7, 12, 0, 0, tzinfo=timezone.utc)

IN = mc.DEAL_ENTRY_IN
OUT = mc.DEAL_ENTRY_OUT


# --------------------------------------------------------------------------- #
# Deterministic collaborators
# --------------------------------------------------------------------------- #
class _Pos:
    def __init__(self, ticket, symbol="EURUSD", volume=0.10):
        self.ticket = ticket
        self.symbol = symbol
        self.volume = volume
        self.closed = False


class FakeTruth:
    """Read-only broker truth over a FakeMt5Client-style store. Records every
    method invoked so tests can assert NO trading method is ever called."""

    def __init__(self, *, connected=True):
        self.connected = connected
        self.open = {}            # ticket -> _Pos
        self.deals = {}           # ticket -> list of deal objects (or None = unavailable)
        self.calls = []

    def terminal_connected(self):
        self.calls.append("terminal_connected")
        return self.connected

    def position_by_ticket(self, ticket):
        self.calls.append(("position_by_ticket", ticket))
        return self.open.get(ticket)

    def deals_for_position(self, position_id):
        self.calls.append(("deals_for_position", position_id))
        return self.deals.get(position_id, None)


class FakeAudit:
    def __init__(self, records):
        self._records = list(records)

    def read_all(self):
        return list(self._records)


def _deal(entry, volume, price):
    return mc._Deal(0, entry, volume, price)


def _facts_record(sid, ticket, symbol, direction, entry, istop):
    """A minimal PM-audit-shaped record carrying the immutable facts."""
    return {"signal_id": sid, "ticket": ticket, "symbol": symbol,
            "direction": direction, "entry_price": entry, "initial_stop": istop,
            "reason_code": "PM_INITIAL"}


def _rig(records, *, connected=True, tmp_path=None):
    truth = FakeTruth(connected=connected)
    audit = FakeAudit(records)
    memory = MemoryStore(str(tmp_path / "memory"))
    rec = OutcomeReconciler(truth, audit, memory, now_fn=lambda: NOW)
    return truth, audit, memory, rec


def _outcomes(memory, symbol=None):
    return memory.query(kind="execution_outcome", subject=symbol, limit=1_000_000)


# --------------------------------------------------------------------------- #
# Realized-R correctness
# --------------------------------------------------------------------------- #
def test_long_winner_records_positive_r(tmp_path):
    sid = "0123456789abcdef"
    truth, _, memory, rec = _rig(
        [_facts_record(sid, 5001, "EURUSD", "LONG", 1.10000, 1.09800)],
        tmp_path=tmp_path)
    # position gone from the broker; a full round trip in deal history
    truth.deals[5001] = [_deal(IN, 0.10, 1.10000), _deal(OUT, 0.10, 1.10400)]

    written = rec.run(NOW)

    assert len(written) == 1
    c = written[0]
    assert c["signal_id"] == sid
    assert c["status"] == "CLOSED"
    assert c["won"] is True
    assert c["taken"] is True
    assert c["r_multiple"] == pytest.approx(2.0)          # (1.10400-1.10000)/0.00200
    assert c["weighted_close"] == pytest.approx(1.10400)
    assert c["broker_order_id"] == 5001
    rows = _outcomes(memory, "EURUSD")
    assert len(rows) == 1 and rows[0]["content"]["r_multiple"] == pytest.approx(2.0)


def test_short_loser_records_negative_r(tmp_path):
    sid = "aaaabbbbccccdddd"
    truth, _, memory, rec = _rig(
        [_facts_record(sid, 5002, "EURUSD", "SHORT", 1.10000, 1.10200)],
        tmp_path=tmp_path)
    truth.deals[5002] = [_deal(IN, 0.10, 1.10000), _deal(OUT, 0.10, 1.10100)]

    written = rec.run(NOW)

    assert len(written) == 1
    c = written[0]
    assert c["won"] is False
    assert c["r_multiple"] == pytest.approx(-0.5)         # (1.10000-1.10100)/0.00200


def test_multiple_partial_exits_blend_to_single_record(tmp_path):
    sid = "1111222233334444"
    truth, _, memory, rec = _rig(
        [_facts_record(sid, 5003, "EURUSD", "LONG", 1.10000, 1.09800)],
        tmp_path=tmp_path)
    # two partial exits netting the 0.10 entry flat: weighted close = 1.10300
    truth.deals[5003] = [_deal(IN, 0.10, 1.10000),
                         _deal(OUT, 0.06, 1.10200),
                         _deal(OUT, 0.04, 1.10450)]

    written = rec.run(NOW)

    assert len(written) == 1
    c = written[0]
    assert c["closed_volume"] == pytest.approx(0.10)
    assert c["weighted_close"] == pytest.approx((0.06 * 1.10200 + 0.04 * 1.10450) / 0.10)
    assert c["deal_count"] == 3


# --------------------------------------------------------------------------- #
# Never mistake unavailable / open / partial state for a close
# --------------------------------------------------------------------------- #
def test_open_position_yields_no_outcome(tmp_path):
    sid = "0000111122223333"
    truth, _, memory, rec = _rig(
        [_facts_record(sid, 5004, "EURUSD", "LONG", 1.10000, 1.09800)],
        tmp_path=tmp_path)
    truth.open[5004] = _Pos(5004)                         # still live
    truth.deals[5004] = [_deal(IN, 0.10, 1.10000)]

    assert rec.run(NOW) == []
    assert _outcomes(memory) == []


def test_disconnected_terminal_never_infers_close(tmp_path):
    sid = "5555666677778888"
    truth, _, memory, rec = _rig(
        [_facts_record(sid, 5005, "EURUSD", "LONG", 1.10000, 1.09800)],
        connected=False, tmp_path=tmp_path)
    truth.deals[5005] = [_deal(IN, 0.10, 1.10000), _deal(OUT, 0.10, 1.10400)]

    assert rec.run(NOW) == []
    assert _outcomes(memory) == []


def test_unavailable_deal_history_never_infers_close(tmp_path):
    sid = "9999aaaabbbbcccc"
    truth, _, memory, rec = _rig(
        [_facts_record(sid, 5006, "EURUSD", "LONG", 1.10000, 1.09800)],
        tmp_path=tmp_path)
    # position absent AND deal history unavailable (None) -> unknown, not a close
    truth.deals[5006] = None

    assert rec.run(NOW) == []
    assert _outcomes(memory) == []


def test_entry_only_deals_not_treated_as_close(tmp_path):
    sid = "ddddeeeeffff0000"
    truth, _, memory, rec = _rig(
        [_facts_record(sid, 5007, "EURUSD", "LONG", 1.10000, 1.09800)],
        tmp_path=tmp_path)
    truth.deals[5007] = [_deal(IN, 0.10, 1.10000)]        # no exit leg yet

    assert rec.run(NOW) == []


def test_unbalanced_partial_not_treated_as_full_close(tmp_path):
    sid = "0f0f0f0f0f0f0f0f"
    truth, _, memory, rec = _rig(
        [_facts_record(sid, 5008, "EURUSD", "LONG", 1.10000, 1.09800)],
        tmp_path=tmp_path)
    # exit volume < entry volume -> not netted flat -> hold
    truth.deals[5008] = [_deal(IN, 0.10, 1.10000), _deal(OUT, 0.04, 1.10400)]

    assert rec.run(NOW) == []


# --------------------------------------------------------------------------- #
# R-undefined + idempotency + facts filtering
# --------------------------------------------------------------------------- #
def test_r_undefined_records_once_with_null_r(tmp_path):
    sid = "1212121212121212"
    truth, _, memory, rec = _rig(
        [_facts_record(sid, 5009, "EURUSD", "LONG", 1.10000, 1.10000)],  # entry == stop
        tmp_path=tmp_path)
    truth.deals[5009] = [_deal(IN, 0.10, 1.10000), _deal(OUT, 0.10, 1.10400)]

    written = rec.run(NOW)

    assert len(written) == 1
    c = written[0]
    assert c["status"] == "R_UNDEFINED"
    assert c["r_multiple"] is None
    assert c["won"] is None


def test_idempotent_single_record_across_runs(tmp_path):
    sid = "3434343434343434"
    truth, _, memory, rec = _rig(
        [_facts_record(sid, 5010, "EURUSD", "LONG", 1.10000, 1.09800)],
        tmp_path=tmp_path)
    truth.deals[5010] = [_deal(IN, 0.10, 1.10000), _deal(OUT, 0.10, 1.10400)]

    first = rec.run(NOW)
    second = rec.run(NOW)

    assert len(first) == 1
    assert second == []                                   # already recorded
    assert len(_outcomes(memory)) == 1


def test_idempotent_across_fresh_reconciler_instance(tmp_path):
    """Restart-safety: a brand-new reconciler over the SAME memory writes nothing
    more for an already-recorded signal_id."""
    sid = "5656565656565656"
    records = [_facts_record(sid, 5011, "EURUSD", "LONG", 1.10000, 1.09800)]
    truth, audit, memory, rec = _rig(records, tmp_path=tmp_path)
    truth.deals[5011] = [_deal(IN, 0.10, 1.10000), _deal(OUT, 0.10, 1.10400)]
    assert len(rec.run(NOW)) == 1

    truth2 = FakeTruth()
    truth2.deals[5011] = truth.deals[5011]
    rec2 = OutcomeReconciler(truth2, FakeAudit(records), memory, now_fn=lambda: NOW)
    assert rec2.run(NOW) == []
    assert len(_outcomes(memory)) == 1


def test_incomplete_facts_are_skipped(tmp_path):
    # missing initial_stop -> not a valid candidate, nothing written
    bad = {"signal_id": "7878787878787878", "ticket": 5012, "symbol": "EURUSD",
           "direction": "LONG", "entry_price": 1.10000, "reason_code": "PM_INITIAL"}
    truth, _, memory, rec = _rig([bad], tmp_path=tmp_path)
    truth.deals[5012] = [_deal(IN, 0.10, 1.10000), _deal(OUT, 0.10, 1.10400)]

    assert rec.run(NOW) == []


def test_malformed_audit_yields_no_candidates(tmp_path):
    class _Boom:
        def read_all(self):
            raise IOError("unreadable")

    memory = MemoryStore(str(tmp_path / "memory"))
    rec = OutcomeReconciler(FakeTruth(), _Boom(), memory, now_fn=lambda: NOW)
    assert rec.run(NOW) == []


# --------------------------------------------------------------------------- #
# Non-blocking / read-only guarantees
# --------------------------------------------------------------------------- #
def test_reconciler_never_calls_trading_methods(tmp_path):
    sid = "9a9a9a9a9a9a9a9a"
    truth, _, memory, rec = _rig(
        [_facts_record(sid, 5013, "EURUSD", "LONG", 1.10000, 1.09800)],
        tmp_path=tmp_path)
    truth.deals[5013] = [_deal(IN, 0.10, 1.10000), _deal(OUT, 0.10, 1.10400)]
    rec.run(NOW)

    # only the three read-only truth methods are ever invoked
    names = {c[0] if isinstance(c, tuple) else c for c in truth.calls}
    assert names <= {"terminal_connected", "position_by_ticket", "deals_for_position"}
    for forbidden in ("modify_stop", "position_close", "order_send", "position_modify"):
        assert not hasattr(truth, forbidden)


def test_service_reconcile_outcomes_swallows_reconciler_error(tmp_path):
    class _Explode:
        def run(self, now):
            raise RuntimeError("boom")

    svc = ManagerService.__new__(ManagerService)          # bypass full wiring
    svc._last_error = None
    svc._outcome_reconciler = _Explode()
    assert svc.reconcile_outcomes(NOW) == []
    assert "boom" in (svc._last_error or "")


def test_service_reconcile_outcomes_noop_when_unwired(tmp_path):
    svc = ManagerService.__new__(ManagerService)
    assert svc.reconcile_outcomes(NOW) == []


# --------------------------------------------------------------------------- #
# Client + truth read-only capability wiring
# --------------------------------------------------------------------------- #
def test_fake_client_history_and_truth_passthrough():
    client = mc.FakeMt5Client()
    client.add_deal(6001, IN, 0.10, 1.10000)
    client.add_deal(6001, OUT, 0.10, 1.10400)
    truth = Mt5TruthSource(client)

    deals = truth.deals_for_position(6001)
    assert isinstance(deals, list) and len(deals) == 2
    assert deals[0].entry == IN and deals[1].entry == OUT
    assert truth.deals_for_position(9999) == []           # query ok, no deals


def test_truth_deals_none_when_capability_absent():
    class _NoHistoryClient:
        def terminal_info(self):
            return type("T", (), {"connected": True})()

    truth = Mt5TruthSource(_NoHistoryClient())
    assert truth.deals_for_position(1) is None            # unknown, not "closed"


def test_consumer_contract_fields_present(tmp_path):
    """The record carries the fields downstream analytics read (signal_id/won/taken)."""
    sid = "cdcdcdcdcdcdcdcd"
    truth, _, memory, rec = _rig(
        [_facts_record(sid, 5014, "EURUSD", "LONG", 1.10000, 1.09800)],
        tmp_path=tmp_path)
    truth.deals[5014] = [_deal(IN, 0.10, 1.10000), _deal(OUT, 0.10, 1.10400)]
    rec.run(NOW)

    row = _outcomes(memory, "EURUSD")[0]
    content = row["content"]
    for key in ("signal_id", "won", "taken"):
        assert key in content
    assert row["correlation_id"] == sid
    assert row["source"] == "outcome_reconciler"
