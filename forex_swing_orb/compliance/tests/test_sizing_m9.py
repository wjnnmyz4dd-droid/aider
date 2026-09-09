"""PR-3J / M9 — canonical sizing + monetary-risk primitives.

Pure, deterministic loss-at-stop and volume quantization used by BOTH the upstream
sizer and the compliance recompute. Cross-pair matrix (EURUSD/GBPUSD/USDJPY/EURJPY/
AUDUSD) with authoritatively-mocked metadata proves the same % risk yields correct
lot differences across stop distances, JPY/non-JPY, and tick values, and that
broker digit format (4/5, 2/3) is invariant when economic geometry is equivalent.
"""

from __future__ import annotations

import math

import pytest

from forex_swing_orb.compliance import sizing

BUDGET = 500.0            # 0.005 × 100_000


def _vol(entry, stop, budget=BUDGET, tick_size=0.00001, tick_value=1.0,
         vmin=0.01, vmax=100.0, vstep=0.01):
    return sizing.allowable_volume(entry, stop, budget, tick_size, tick_value,
                                   vmin, vmax, vstep)


# --------------------------------------------------------------------------- #
# §38 core sizing
# --------------------------------------------------------------------------- #
def test_1_eurusd_known_volume():
    # per_lot = 0.00500/1e-5 * 1.0 = 500 ; raw = 500/500 = 1.0
    assert _vol(1.10000, 1.09500) == pytest.approx(1.0)


def test_2_usdjpy_known_volume():
    # 3-digit JPY: tick_size 0.001, tick_value 1.0 (account currency). distance 0.50
    # per_lot = 0.50/0.001 * 1.0 = 500 ; raw = 1.0
    assert _vol(150.000, 149.500, tick_size=0.001, tick_value=1.0) == pytest.approx(1.0)


def test_3_five_vs_four_digit_invariance():
    five = _vol(1.10000, 1.09500, tick_size=0.00001, tick_value=1.0)
    four = _vol(1.1000, 1.0950, tick_size=0.0001, tick_value=10.0)   # equivalent economics
    assert five == four == pytest.approx(1.0)


def test_4_three_vs_two_digit_jpy_invariance():
    three = _vol(150.000, 149.500, tick_size=0.001, tick_value=1.0)
    two = _vol(150.00, 149.50, tick_size=0.01, tick_value=10.0)      # equivalent economics
    assert three == two == pytest.approx(1.0)


def test_5_volume_rounded_down_to_step():
    # per_lot for 0.00333 distance = 333 ; raw = 500/333 = 1.5015 -> floor to 0.01 step
    v = _vol(1.10000, 1.09667, vstep=0.01)
    assert v == pytest.approx(1.50) and math.isclose((v / 0.01) % 1, 0, abs_tol=1e-6)


def test_6_below_min_rejects():
    # wide stop: per_lot huge -> raw < vmin -> NO TRADE
    assert _vol(1.10000, 1.00000, vmin=0.10) is None


def test_7_above_max_capped_within_risk():
    # tight stop -> raw > vmax; vmax lots still within budget -> cap at vmax
    v = _vol(1.10000, 1.09999, vmax=5.0)
    assert v == pytest.approx(5.0)
    assert sizing.loss_at_stop(1.10000, 1.09999, v, 0.00001, 1.0) <= BUDGET + 1e-6


def test_8_missing_tick_value_blocks():
    assert sizing.allowable_volume(1.10, 1.095, BUDGET, 0.00001, None, 0.01, 100.0, 0.01) is None


def test_9_zero_tick_size_blocks():
    assert sizing.allowable_volume(1.10, 1.095, BUDGET, 0.0, 1.0, 0.01, 100.0, 0.01) is None


def test_10_malformed_volume_step_blocks():
    assert sizing.allowable_volume(1.10, 1.095, BUDGET, 0.00001, 1.0, 0.01, 100.0, 0.0) is None


def test_11_nan_inf_metadata_blocks():
    for bad in (float("nan"), float("inf")):
        assert sizing.allowable_volume(1.10, 1.095, BUDGET, bad, 1.0, 0.01, 100.0, 0.01) is None
        assert sizing.loss_at_stop(1.10, 1.095, 0.10, bad, 1.0) is None


def test_12_very_tight_stop_safe_no_divide_blowup():
    v = _vol(1.10000, 1.09999, vmax=100.0)          # tiny distance -> large but capped/valid
    assert v is not None and 0 < v <= 100.0


def test_13_wide_stop_below_min_rejects():
    # very wide stop: per_lot = 0.60/1e-5 = 60000, raw = 500/60000 = 0.0083 < vmin 0.01
    assert _vol(1.10000, 0.50000, vmin=0.01) is None


def test_14_exact_risk_boundary_deterministic():
    # distance chosen so raw is an exact multiple of step at the budget
    v = _vol(1.10000, 1.09500)                      # raw exactly 1.0
    assert v == pytest.approx(1.0)
    loss = sizing.loss_at_stop(1.10000, 1.09500, v, 0.00001, 1.0)
    assert loss <= BUDGET + 1e-6


def test_15_recomputed_risk_never_exceeds_limit():
    for stop in (1.09900, 1.09750, 1.09500, 1.09333, 1.08000):
        v = _vol(1.10000, stop)
        if v is None:
            continue
        assert sizing.loss_at_stop(1.10000, stop, v, 0.00001, 1.0) <= BUDGET + 1e-6


def test_13b_entry_equals_stop_blocks():
    assert _vol(1.10000, 1.10000) is None
    assert sizing.loss_at_stop(1.10000, 1.10000, 0.10, 0.00001, 1.0) is None


# --------------------------------------------------------------------------- #
# §22 cross-pair matrix — same % risk, correct lot differences
# --------------------------------------------------------------------------- #
_PAIRS = {
    "EURUSD": dict(entry=1.10000, tick_size=0.00001, tick_value=1.0),
    "GBPUSD": dict(entry=1.27000, tick_size=0.00001, tick_value=1.0),
    "USDJPY": dict(entry=150.000, tick_size=0.001, tick_value=1.0),
    "EURJPY": dict(entry=160.000, tick_size=0.001, tick_value=1.0),
    "AUDUSD": dict(entry=0.66000, tick_size=0.00001, tick_value=1.0),
}


@pytest.mark.parametrize("pair", list(_PAIRS))
def test_tighter_stop_gives_larger_lot(pair):
    m = _PAIRS[pair]
    pip = m["tick_size"] * 10
    wide = _vol(m["entry"], m["entry"] - 50 * pip, tick_size=m["tick_size"], tick_value=m["tick_value"])
    tight = _vol(m["entry"], m["entry"] - 25 * pip, tick_size=m["tick_size"], tick_value=m["tick_value"])
    assert wide is not None and tight is not None
    assert tight > wide                              # half the stop -> ~double the lot


def test_lower_tick_value_gives_larger_lot():
    base = _vol(1.10000, 1.09500, tick_value=1.0)
    cheaper = _vol(1.10000, 1.09500, tick_value=0.5)
    assert cheaper > base                            # cheaper tick -> larger affordable lot


# --------------------------------------------------------------------------- #
# property tests A/B/C
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("v1,v2", [(0.10, 0.20), (0.50, 2.0), (1.0, 1.01)])
def test_propA_more_volume_never_less_risk(v1, v2):
    r1 = sizing.loss_at_stop(1.10, 1.095, v1, 0.00001, 1.0)
    r2 = sizing.loss_at_stop(1.10, 1.095, v2, 0.00001, 1.0)
    assert r2 >= r1


@pytest.mark.parametrize("s1,s2", [(1.099, 1.095), (1.098, 1.090)])
def test_propB_wider_stop_never_less_risk(s1, s2):
    r1 = sizing.loss_at_stop(1.10, s1, 0.10, 0.00001, 1.0)
    r2 = sizing.loss_at_stop(1.10, s2, 0.10, 0.00001, 1.0)
    assert r2 >= r1                                  # s2 is farther from entry


@pytest.mark.parametrize("raw", [0.379, 1.5015, 2.999, 99.999])
def test_propC_quantize_never_exceeds_raw(raw):
    q = sizing.quantize_down(raw, 0.01, 100.0, 0.01)
    assert q is not None and q <= raw + 1e-12
