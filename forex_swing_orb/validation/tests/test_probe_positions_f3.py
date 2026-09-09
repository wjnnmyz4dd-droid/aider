"""F3 (validation tooling) — the MT5 outcome probe must distinguish "no open
positions" (KNOWN_EMPTY) from "could not query positions" (UNKNOWN), so it never
prints a false flat/absent state after an API failure. Deterministic; fake mt5."""

from __future__ import annotations

from types import SimpleNamespace

from forex_swing_orb.validation.mt5_outcome_probe import _positions_by_comment

SID = "0123456789abcdef"


class _Mt5:
    def __init__(self, ret=None, raises=False):
        self._ret, self._raises = ret, raises

    def positions_get(self, symbol=None):
        if self._raises:
            raise RuntimeError("simulated positions_get failure")
        return self._ret


def _pos(comment=SID):
    return SimpleNamespace(comment=comment, ticket=5000001, symbol="EURUSD")


def test_22_none_positions_reports_unknown():
    # UNKNOWN (API returned None) -> None, NEVER an empty list (false "no positions")
    assert _positions_by_comment(_Mt5(ret=None), SID) is None


def test_22b_exception_reports_unknown():
    assert _positions_by_comment(_Mt5(raises=True), SID) is None


def test_22c_malformed_reports_unknown():
    assert _positions_by_comment(_Mt5(ret={"bad": "type"}), SID) is None


def test_23_empty_positions_reports_known_empty():
    # KNOWN_EMPTY -> [] (a real, queryable, empty book), distinct from None
    assert _positions_by_comment(_Mt5(ret=()), SID) == []


def test_23b_matching_position_returned():
    got = _positions_by_comment(_Mt5(ret=(_pos(),)), SID)
    assert got is not None and len(got) == 1


def test_24_no_false_flat_after_failure():
    # the probe must not conflate a query failure with a flat book
    unknown = _positions_by_comment(_Mt5(ret=None), SID)
    known_empty = _positions_by_comment(_Mt5(ret=()), SID)
    assert unknown is None and known_empty == [] and unknown is not known_empty


def test_26_no_none_empty_collapse_in_probe_source():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "mt5_outcome_probe.py").read_text(encoding="utf-8")
    assert "positions_get() or (" not in src
    assert "positions_get() or [" not in src
