"""PR-3D / H6 — canonical per-symbol FX price geometry (position/geometry.py).

pip is derived from AUTHORITATIVE broker digit/point metadata, never from the symbol
name and never from a universal 0.0001 assumption. Missing / malformed / inconsistent
/ non-FX metadata fails closed (resolve -> None). Deterministic; pure; no broker.
"""

from __future__ import annotations

import math

from forex_swing_orb.position import geometry as G


class _Info:
    """Minimal duck-typed symbol_info stand-in."""
    def __init__(self, digits=None, point=None, **kw):
        self.digits = digits
        self.point = point
        for k, v in kw.items():
            setattr(self, k, v)


# --------------------------------------------------------------------------- #
# canonical FX pip derivation (§3, §30.1-6)
# --------------------------------------------------------------------------- #
def test_eurusd_5digit_pip():
    g = G.resolve(_Info(digits=5, point=1e-5))
    assert g is not None and g.pip == 1e-4 and g.point == 1e-5 and g.digits == 5


def test_eurusd_4digit_pip():
    g = G.resolve(_Info(digits=4, point=1e-4))
    assert g is not None and g.pip == 1e-4 and g.point == 1e-4


def test_usdjpy_3digit_pip():
    g = G.resolve(_Info(digits=3, point=1e-3))
    assert g is not None and g.pip == 1e-2 and g.point == 1e-3


def test_usdjpy_2digit_pip():
    g = G.resolve(_Info(digits=2, point=1e-2))
    assert g is not None and g.pip == 1e-2 and g.point == 1e-2


def test_pips_to_price_per_symbol():
    eur = G.resolve(_Info(digits=5, point=1e-5))
    jpy = G.resolve(_Info(digits=3, point=1e-3))
    assert abs(eur.pips_to_price(10) - 0.0010) < 1e-15   # 10 pip EURUSD
    assert abs(jpy.pips_to_price(10) - 0.10) < 1e-12      # 10 pip USDJPY


# --------------------------------------------------------------------------- #
# tick_size (optional) — for FX must equal point (§14)
# --------------------------------------------------------------------------- #
def test_tick_size_equal_point_ok():
    g = G.resolve(_Info(digits=5, point=1e-5, trade_tick_size=1e-5))
    assert g is not None and g.point == 1e-5


def test_tick_size_diverges_fails_closed():
    # an exotic tradable grid (tick != point) is out of the FOREX-only scope
    assert G.resolve(_Info(digits=5, point=1e-5, trade_tick_size=5e-5)) is None


# --------------------------------------------------------------------------- #
# malformed / inconsistent metadata -> fail closed (§19, §30.16-19)
# --------------------------------------------------------------------------- #
def test_none_info_fails_closed():
    assert G.resolve(None) is None


def test_digits_none_fails_closed():
    assert G.resolve(_Info(digits=None, point=1e-5)) is None


def test_digits_negative_fails_closed():
    assert G.resolve(_Info(digits=-1, point=10.0)) is None


def test_digits_out_of_fx_range_fails_closed():
    assert G.resolve(_Info(digits=99, point=1e-99)) is None
    assert G.resolve(_Info(digits=1, point=0.1)) is None
    assert G.resolve(_Info(digits=6, point=1e-6)) is None   # not a standard FX format


def test_digits_bool_fails_closed():
    assert G.resolve(_Info(digits=True, point=0.1)) is None


def test_point_none_fails_closed():
    assert G.resolve(_Info(digits=5, point=None)) is None


def test_point_zero_fails_closed():
    assert G.resolve(_Info(digits=5, point=0.0)) is None


def test_point_negative_fails_closed():
    assert G.resolve(_Info(digits=5, point=-1e-5)) is None


def test_point_nan_fails_closed():
    assert G.resolve(_Info(digits=5, point=float("nan"))) is None


def test_point_inf_fails_closed():
    assert G.resolve(_Info(digits=5, point=float("inf"))) is None


def test_inconsistent_digits_point_fails_closed():
    # digits says 5 but point says 4-digit grid -> inconsistent -> fail closed
    assert G.resolve(_Info(digits=5, point=1e-4)) is None
    assert G.resolve(_Info(digits=3, point=1e-2)) is None


def test_missing_attrs_fails_closed():
    class Bare:
        pass
    assert G.resolve(Bare()) is None
