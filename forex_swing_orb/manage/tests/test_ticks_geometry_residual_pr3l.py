"""PR-3L — manage/ticks fallback-geometry residual closure.

The management transport no longer guesses executable price geometry. Per-symbol
point/digits come ONLY from the authoritative H6 geometry (position.geometry.resolve);
the PM-authorized stop is transported VERBATIM (never re-quantized onto a guessed
grid); and when authoritative geometry is unavailable the manage channel fails closed
(no modification, existing protective stop preserved, UNCERTAIN → PM reconciles).
Deterministic; mock terminal; no real MT5.
"""

from __future__ import annotations

import math
from datetime import timedelta
from pathlib import Path

import pytest

from forex_swing_orb.bridge import serialize
from forex_swing_orb.ea_mt5 import mock_mt5
from forex_swing_orb.manage import (ManageConsumer, ManagePaths, ManageStatus,
                                    build_instruction, initial_r_digest,
                                    write_manage_instruction)
from forex_swing_orb.manage import contract as MC
from forex_swing_orb.manage import ticks
from conftest import NOW

BUY, SELL = mock_mt5.ORDER_TYPE_BUY, mock_mt5.ORDER_TYPE_SELL
MANAGE_DIR = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# stubs for pure geometry unit tests (can carry trade_tick_size, unlike the mock)
# --------------------------------------------------------------------------- #
_UNSET = object()


class _Info:
    def __init__(self, digits, point, tick_size=_UNSET):
        self.digits = digits
        self.point = point
        if tick_size is not _UNSET:
            self.trade_tick_size = tick_size


class _MT5:
    def __init__(self, info):
        self._info = info

    def symbol_info(self, _symbol):
        if isinstance(self._info, Exception):
            raise self._info
        return self._info


def _geo_mt5(digits, point, **kw):
    return _MT5(_Info(digits, point, **kw))


# --------------------------------------------------------------------------- #
# E2E harness (manage consumer against a mock terminal)
# --------------------------------------------------------------------------- #
def _mt5(symbol="EURUSD", *, sl, entry, tp, side=BUY, digits=5, point=0.00001,
         ticket=5000001, add_symbol=True):
    m = mock_mt5.MockMT5()
    if add_symbol:
        m.add_symbol(symbol, digits=digits, point=point)
    m.positions[ticket] = mock_mt5.Position(ticket, symbol, side, 0.1, entry, sl, tp,
                                            "0123456789abcdef")
    return m


def _instr(*, symbol="EURUSD", direction="LONG", target_stop, expected_current_stop,
           entry, initial_stop, ticket=5000001, seq=1, **over):
    f = {"signal_id": "0123456789abcdef", "ticket": ticket, "symbol": symbol,
         "direction": direction, "action": MC.ManageAction.MODIFY_STOP,
         "target_stop": target_stop, "expected_current_stop": expected_current_stop,
         "prior_stop": expected_current_stop, "pm_phase": "INITIAL",
         "pm_reason": "PM_MODIFY@INITIAL", "structure_reference": None,
         "market_reference": None, "point": None, "digits": None,
         "broker_min_stop_distance": 0.0, "per_ticket_sequence": seq,
         "generated_timestamp": serialize.iso_utc(NOW),
         "expiration_timestamp": serialize.iso_utc(NOW + timedelta(seconds=120)),
         "initial_r_digest": initial_r_digest(direction, entry, initial_stop)}
    f.update(over)
    return build_instruction(f)


def _emit(mp, m, instr, now=NOW):
    write_manage_instruction(mp, instr, now)
    return ManageConsumer(m, mp).run_once(now)


# ============================ 1-6 format preservation ====================== #
# each: a canonical target at that broker digit format is executed VERBATIM
# (never coarsened / re-quantized onto a guessed 5-digit grid).
_FMT = [
    ("EURUSD",   5, 0.00001, 1.10000, 1.09800, 1.10020),   # 5-digit
    ("EURUSD",   4, 0.0001,  1.1000,  1.0980,  1.1002),    # 4-digit
    ("USDJPY",   3, 0.001,   150.000, 149.800, 150.020),   # 3-digit JPY
    ("USDJPY",   2, 0.01,    150.00,  149.80,  150.02),    # 2-digit JPY
    ("GBPJPY",   3, 0.001,   190.000, 189.800, 190.020),   # 3-digit JPY
    ("USDJPY.a", 3, 0.001,   150.000, 149.800, 150.020),   # suffix -> metadata-driven
]


@pytest.mark.parametrize("sym,digits,point,entry,sl,target", _FMT)
def test_1_6_target_preserved_across_formats(tmp_path, sym, digits, point, entry, sl, target):
    mp = ManagePaths(tmp_path).ensure()
    m = _mt5(sym, sl=sl, entry=entry, tp=entry + 100 * point * 10, digits=digits, point=point)
    res = _emit(mp, m, _instr(symbol=sym, target_stop=target, expected_current_stop=sl,
                              entry=entry, initial_stop=sl))
    assert res["status"] == ManageStatus.APPLIED
    assert m.positions[5000001].sl == pytest.approx(target)   # exact, not re-gridded


# ============================ 7-8 never wrong-side ========================= #
def test_7_long_stop_cannot_move_to_wrong_side(tmp_path):
    mp = ManagePaths(tmp_path).ensure()
    m = _mt5("EURUSD", sl=1.09800, entry=1.10000, tp=1.10600)
    # LONG loosen (stop DOWN, away from price) must be rejected — never widened
    res = _emit(mp, m, _instr(target_stop=1.09700, expected_current_stop=1.09800,
                              entry=1.10000, initial_stop=1.09800))
    assert res["status"] == ManageStatus.REJECTED_LOOSEN
    assert m.positions[5000001].sl == pytest.approx(1.09800)   # untouched


def test_8_short_stop_cannot_move_to_wrong_side(tmp_path):
    mp = ManagePaths(tmp_path).ensure()
    m = _mt5("EURUSD", sl=1.10200, entry=1.10000, tp=1.09400, side=SELL)
    # SHORT loosen (stop UP, away from price) must be rejected
    res = _emit(mp, m, _instr(direction="SHORT", target_stop=1.10300,
                              expected_current_stop=1.10200, entry=1.10000, initial_stop=1.10200))
    assert res["status"] == ManageStatus.REJECTED_LOOSEN
    assert m.positions[5000001].sl == pytest.approx(1.10200)


# ============================ 9-10 verbatim fields ========================= #
def test_9_target_stop_transported_verbatim():
    # the adapter/transport does not re-quantize: an authoritative-grid target is the
    # exact value carried on the wire (proven here via the instruction the PM builds).
    ins = _instr(symbol="USDJPY", target_stop=150.023, expected_current_stop=149.800,
                 entry=150.000, initial_stop=149.800)
    assert ins["target_stop"] == 150.023


def test_10_expected_current_stop_transported_verbatim():
    ins = _instr(target_stop=1.10020, expected_current_stop=1.098765,
                 entry=1.10000, initial_stop=1.09800)
    assert ins["expected_current_stop"] == 1.098765


# ============================ 11-21 metadata handling ====================== #
def test_11_missing_metadata_fails_closed_no_modify(tmp_path):
    mp = ManagePaths(tmp_path).ensure()
    m = _mt5("EURUSD", sl=1.09800, entry=1.10000, tp=1.10600, digits=None)  # geometry gone
    res = _emit(mp, m, _instr(target_stop=1.10020, expected_current_stop=1.09800,
                              entry=1.10000, initial_stop=1.09800))
    assert res["status"] == ManageStatus.UNCERTAIN            # fail closed, reconcile
    assert m.positions[5000001].sl == pytest.approx(1.09800)  # protective stop intact


@pytest.mark.parametrize("digits,point,kw", [
    (None, 0.00001, {}),                    # 12 digits=None
    (6, 0.000001, {}),                      # 13 invalid (non-FX) digits
    ("5", 0.00001, {}),                     # 13 invalid digits type
    (5, None, {}),                          # 14 missing point
    (5, 0.0, {}),                           # 15 point=0
    (5, float("nan"), {}),                  # 16 NaN metadata
    (5, float("inf"), {}),                  # 16 Inf metadata
    (5, 0.00001, {"tick_size": 0.00002}),   # 17 tick_size != point (H6 boundary)
])
def test_12_17_bad_metadata_no_authoritative_geometry(digits, point, kw):
    mt5 = _geo_mt5(digits, point, **kw)
    assert ticks.point(mt5, "EURUSD") is None
    assert ticks.digits(mt5, "EURUSD") is None
    # eq_stop cannot assume equality on an unknown grid -> fail closed (not equal)
    assert ticks.eq_stop(1.10000, 1.10000, mt5, "EURUSD") is False


def test_17_tick_equals_point_is_valid():
    mt5 = _geo_mt5(5, 0.00001, tick_size=0.00001)             # tick == point -> FX OK
    assert ticks.point(mt5, "EURUSD") == 0.00001 and ticks.digits(mt5, "EURUSD") == 5


def test_18_metadata_lost_between_authorization_and_transport(tmp_path):
    # instruction was authorized with a valid target, but by the time the consumer
    # runs the broker metadata has vanished -> fail closed (no modify, stop intact).
    mp = ManagePaths(tmp_path).ensure()
    m = _mt5("EURUSD", sl=1.09800, entry=1.10000, tp=1.10600, digits=None)
    res = _emit(mp, m, _instr(target_stop=1.10020, expected_current_stop=1.09800,
                              entry=1.10000, initial_stop=1.09800))
    assert res["status"] == ManageStatus.UNCERTAIN
    assert m.positions[5000001].sl == pytest.approx(1.09800)


def test_19_transient_metadata_failure_then_recovery(tmp_path):
    mp = ManagePaths(tmp_path).ensure()
    m = _mt5("EURUSD", sl=1.09800, entry=1.10000, tp=1.10600, digits=None)
    assert _emit(mp, m, _instr(target_stop=1.10020, expected_current_stop=1.09800,
                               entry=1.10000, initial_stop=1.09800, seq=1)
                 )["status"] == ManageStatus.UNCERTAIN               # geometry gone -> no modify
    assert m.positions[5000001].sl == pytest.approx(1.09800)         # stop preserved
    # metadata returns; the PM reconciles and re-issues next cycle (new sequence)
    m.symbols["EURUSD"].digits = 5
    m.symbols["EURUSD"].point = 0.00001
    res2 = _emit(mp, m, _instr(target_stop=1.10020, expected_current_stop=1.09800,
                               entry=1.10000, initial_stop=1.09800, seq=2))
    assert res2["status"] == ManageStatus.APPLIED
    assert m.positions[5000001].sl == pytest.approx(1.10020)


def test_20_21_no_modify_and_stop_intact_on_geometry_loss(tmp_path):
    mp = ManagePaths(tmp_path).ensure()
    m = _mt5("USDJPY", sl=149.800, entry=150.000, tp=150.600, digits=None, point=0.001)
    before = m.positions[5000001].sl
    res = _emit(mp, m, _instr(symbol="USDJPY", target_stop=150.020,
                              expected_current_stop=149.800, entry=150.000, initial_stop=149.800))
    assert res["status"] == ManageStatus.UNCERTAIN
    assert m.positions[5000001].sl == before                          # exactly preserved


# ============================ 22-25 static / EA audit ====================== #
def test_22_no_guessed_five_digit_in_executable_path(tmp_path):
    # a JPY (3-digit) target executes verbatim; nothing coerces it toward a 5-digit grid
    mp = ManagePaths(tmp_path).ensure()
    m = _mt5("USDJPY", sl=149.800, entry=150.000, tp=150.600, digits=3, point=0.001)
    res = _emit(mp, m, _instr(symbol="USDJPY", target_stop=150.023,
                              expected_current_stop=149.800, entry=150.000, initial_stop=149.800))
    assert res["status"] == ManageStatus.APPLIED
    assert m.positions[5000001].sl == pytest.approx(150.023)


def test_23_no_fallback_digits_constant_in_manage_ticks():
    import ast
    assert not hasattr(ticks, "_FALLBACK_DIGITS")            # runtime: constant gone
    tree = ast.parse((MANAGE_DIR / "ticks.py").read_text())  # source: no such assignment
    assigned = {t.id for node in ast.walk(tree) if isinstance(node, ast.Assign)
                for t in node.targets if isinstance(t, ast.Name)}
    assert "_FALLBACK_DIGITS" not in assigned
    # and no module constant is bound to a guessed digit count / point
    assert not any(isinstance(getattr(ticks, n, None), (int, float))
                   for n in dir(ticks) if n.isupper())


def test_24_no_independent_pip_or_geometry_derivation_in_manage_ticks():
    src = (MANAGE_DIR / "ticks.py").read_text()
    assert "pip_size" not in src
    # no bare guessed FX geometry literals in the transport helper
    assert "0.0001" not in src and "0.00001" not in src and "0.01" not in src
    # geometry comes from the ONE authority
    assert "geometry" in src and "resolve" in src


def test_25_ea_manage_handler_normalizes_with_live_symbol_digits():
    ea = (MANAGE_DIR.parent / "ea_mt5" / "SessionEdgeManageHandler.mqh").read_text()
    assert "NormalizeDouble(target" in ea
    assert "SYMBOL_DIGITS" in ea


# ============================ 26-28 protocol / idempotency / reconcile ===== #
def test_26_manage_protocol_schema_unchanged():
    # no protocol migration: schema version + instruction field set preserved
    assert "point" in MC.INSTRUCTION_FIELDS and "digits" in MC.INSTRUCTION_FIELDS
    assert "target_stop" in MC.INSTRUCTION_FIELDS
    ins = _instr(target_stop=1.10020, expected_current_stop=1.09800,
                 entry=1.10000, initial_stop=1.09800)
    ok, reason = MC.validate_instruction(ins)
    assert ok, reason


def test_27_repeated_management_is_idempotent(tmp_path):
    mp = ManagePaths(tmp_path).ensure()
    m = _mt5("EURUSD", sl=1.09800, entry=1.10000, tp=1.10600)
    ins = _instr(target_stop=1.10020, expected_current_stop=1.09800,
                 entry=1.10000, initial_stop=1.09800)
    r1 = _emit(mp, m, ins)
    assert r1["status"] == ManageStatus.APPLIED and m.positions[5000001].sl == pytest.approx(1.10020)
    # re-delivering the SAME manage_id does not re-modify (dedup / terminal evidence)
    r2 = ManageConsumer(m, mp).run_once(NOW)
    assert m.positions[5000001].sl == pytest.approx(1.10020)   # unchanged; no double move


def test_28_readback_mismatch_stays_uncertain_not_silent_accept(tmp_path):
    mp = ManagePaths(tmp_path).ensure()
    m = _mt5("EURUSD", sl=1.09800, entry=1.10000, tp=1.10600)

    real_modify = m.modify_stop
    def _distorting_modify(ticket, sl):          # broker stores a DIFFERENT stop
        r = real_modify(ticket, sl)
        m.positions[ticket].sl = sl + 0.00050     # off-grid distortion on read-back
        return r
    m.modify_stop = _distorting_modify
    res = _emit(mp, m, _instr(target_stop=1.10020, expected_current_stop=1.09800,
                              entry=1.10000, initial_stop=1.09800))
    assert res["status"] == ManageStatus.UNCERTAIN            # never silently APPLIED
