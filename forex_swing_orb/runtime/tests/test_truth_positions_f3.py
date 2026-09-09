"""F3 — UNKNOWN position state must never collapse to KNOWN_EMPTY.

runtime.truth.Mt5TruthSource.positions() previously did ``positions_get() or ()``,
collapsing None/exception/malformed (UNKNOWN — query failed) into the SAME value as
() (KNOWN_EMPTY — a proven flat book). That is the M-1 semantic-collapse class. This
hardens the runtime position-truth contract to three distinct semantics:

    []/()               -> KNOWN_EMPTY
    [p, ...]            -> KNOWN_NONEMPTY
    None/exc/malformed  -> UNKNOWN  (positions() returns None)

Callers (adoption discover/market/open-times, position_by_ticket) handle UNKNOWN
explicitly (defer / hold / fail closed) and never treat it as flat. Deterministic;
FakeMt5Client; no networking.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from forex_swing_orb.live.mt5_client import FakeMt5Client                  # noqa: E402
from forex_swing_orb.runtime.truth import Mt5TruthSource                   # noqa: E402
from forex_swing_orb.runtime import adoption                              # noqa: E402

SID = "0123456789abcdef"


def _pos(ticket=5000001, comment=SID, symbol="EURUSD", price=1.10050, t=1700000000):
    return SimpleNamespace(ticket=ticket, symbol=symbol, comment=comment,
                           price_current=price, time=t, closed=False)


def _client(positions=None, unavailable=False):
    c = FakeMt5Client()
    c.positions = list(positions or [])
    c.positions_unavailable = unavailable
    return c


class _RaisingClient(FakeMt5Client):
    def positions_get(self, symbol=None):
        raise RuntimeError("simulated MT5 positions_get failure")


class _MalformedClient(FakeMt5Client):
    def positions_get(self, symbol=None):
        return {"not": "a list"}                       # malformed return type


# ============================================================================
# CORE CONTRACT (1-6)
# ============================================================================
def test_1_known_empty_tuple():
    assert Mt5TruthSource(_client([])).positions() == []      # KNOWN_EMPTY, not None


def test_3_known_nonempty():
    r = Mt5TruthSource(_client([_pos()])).positions()
    assert r is not None and len(r) == 1


def test_4_none_is_unknown():
    # REPRODUCTION: positions_get() -> None must be UNKNOWN (None), never [].
    assert Mt5TruthSource(_client(unavailable=True)).positions() is None


def test_5_exception_is_unknown():
    assert Mt5TruthSource(_RaisingClient()).positions() is None


def test_6_malformed_is_unknown():
    assert Mt5TruthSource(_MalformedClient()).positions() is None


def test_known_empty_distinct_from_unknown():
    assert Mt5TruthSource(_client([])).positions() is not None    # KNOWN_EMPTY
    assert Mt5TruthSource(_client(unavailable=True)).positions() is None  # UNKNOWN


# ============================================================================
# TRUTH CALLERS (7-10) — UNKNOWN never treated as flat
# ============================================================================
def test_7_position_by_ticket_unknown_returns_none_not_flat():
    # UNKNOWN -> position_by_ticket None -> the PM (M-6) requires deal-confirmation to
    # mark CLOSED, so UNKNOWN can never be read as flat here.
    t = Mt5TruthSource(_client(unavailable=True))
    assert t.position_by_ticket(5000001) is None


def test_9_known_empty_position_by_ticket():
    t = Mt5TruthSource(_client([]))
    assert t.position_by_ticket(5000001) is None                 # genuinely absent


def test_10_known_nonempty_position_by_ticket():
    p = _pos()
    t = Mt5TruthSource(_client([p]))
    assert t.position_by_ticket(5000001) is p


def test_8_adoption_defers_on_unknown():
    # discover/market/open-times must DEFER (empty) on UNKNOWN, never crash and never
    # assert a flat book.
    t = Mt5TruthSource(_client(unavailable=True))
    assert adoption.discover_positions(t) == []
    assert adoption.market_from_truth(t) == {}
    assert adoption.open_times_from_truth(t) == {}


def test_8b_adoption_known_empty_same_defer():
    t = Mt5TruthSource(_client([]))
    assert adoption.discover_positions(t) == []
    assert adoption.market_from_truth(t) == {}


def test_10b_adoption_known_nonempty_unchanged():
    t = Mt5TruthSource(_client([_pos()]))
    got = adoption.discover_positions(t)
    assert len(got) == 1 and got[0]["signal_id"] == SID
    assert adoption.market_from_truth(t) == {5000001: pytest.approx(1.10050)}
    assert adoption.open_times_from_truth(t) == {5000001: 1700000000}


# ============================================================================
# API ERROR DETAIL (K) — observational only
# ============================================================================
def test_last_error_captured_on_unknown():
    class _ErrClient(FakeMt5Client):
        def positions_get(self, symbol=None):
            return None
        def last_error(self):
            return (1, "no connection")
    t = Mt5TruthSource(_ErrClient())
    assert t.positions() is None
    # diagnostic captured but never authority
    assert t.last_positions_error() == (1, "no connection")


# ============================================================================
# SEARCH GUARD (25-27) — no reintroduced None->empty collapse; no dup authority
# ============================================================================
def test_25_no_none_empty_collapse_in_truth_and_adoption():
    for mod in ("runtime/truth.py", "runtime/adoption.py"):
        src = (REPO / "forex_swing_orb" / mod).read_text(encoding="utf-8")
        assert "positions_get() or (" not in src
        assert "positions_get() or [" not in src
        # positions() result must not be coerced with `or ()` / `or []`
        assert "positions() or (" not in src
        assert "positions() or [" not in src


def test_27_no_duplicate_position_state_helper():
    # runtime.truth exposes truth only; it must not compute risk or closure.
    src = (REPO / "forex_swing_orb" / "runtime" / "truth.py").read_text(encoding="utf-8")
    for banned in ("confirm_full_close", "risk_fraction", "allowable_volume",
                   "initial_risk", "def reconstruct"):
        assert banned not in src
