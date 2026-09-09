"""PR-3D / H6 — per-symbol pip & price geometry in the Position Manager.

Executable BE / profit-lock / trail / min-improvement geometry is derived from
AUTHORITATIVE per-symbol broker metadata (digits/point -> pip), never a universal
0.0001 pip or a guessed 5-digit fallback. JPY pairs (2/3-digit) use pip = 0.01;
majors (4/5-digit) use pip = 0.0001. Missing / malformed metadata fails closed:
the PM takes NO stop action and the existing protective stop is preserved.
Deterministic; mock MT5; no networking.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from forex_swing_orb.ea_mt5 import mock_mt5
from forex_swing_orb.ea_mt5 import position_manager as pmmod
from forex_swing_orb.ea_mt5.position_manager import PositionManager
from forex_swing_orb.position import spec, DEFAULT_PM_CONFIG, PositionConfig
from forex_swing_orb.position.contract import StopPhase, PMReason

NOW = datetime(2024, 1, 25, 12, 0, tzinfo=timezone.utc)
BUY, SELL = mock_mt5.ORDER_TYPE_BUY, mock_mt5.ORDER_TYPE_SELL
CFG = DEFAULT_PM_CONFIG


def rig(symbol="EURUSD", direction="LONG", entry=1.10000, sl=1.09800, tp=1.11000,
        digits=5, point=1e-5, cfg=CFG):
    m = mock_mt5.MockMT5()
    m.add_symbol(symbol, digits=digits, point=point, bid=entry, ask=entry)
    typ = BUY if direction == "LONG" else SELL
    res = m.order_send({"symbol": symbol, "volume": 0.10, "type": typ,
                        "price": entry, "sl": sl, "tp": tp, "comment": "sig"})
    pm = PositionManager(m, Path(tempfile.mkdtemp()) / "pm.jsonl", cfg)
    pm.register("sig", res.order, symbol, direction, entry, sl, tp, NOW)
    return pm, m, res.order


def be_trigger(direction, entry, sl, cfg=CFG):
    R = spec.initial_risk(direction, entry, sl)
    return spec.breakeven_trigger_price(direction, entry, R, cfg)


def pl_trigger(direction, entry, sl, cfg=CFG):
    R = spec.initial_risk(direction, entry, sl)
    return spec.profit_lock_trigger_price(direction, entry, R, cfg)


# --------------------------------------------------------------------------- #
# BE buffer is per-symbol pip (§10, §30.7-8)
# --------------------------------------------------------------------------- #
def test_be_buffer_eurusd_5digit():
    pm, m, tk = rig("EURUSD", entry=1.10000, sl=1.09800, digits=5, point=1e-5)
    r = pm.evaluate("sig", market_price=be_trigger("LONG", 1.10000, 1.09800), now=NOW)
    assert r["reason_code"] == PMReason.BREAKEVEN_SET
    assert abs(r["applied_stop"] - (1.10000 + 2 * 1e-4)) < 1e-9      # 1.10020


def test_be_buffer_usdjpy_3digit():
    pm, m, tk = rig("USDJPY", entry=150.000, sl=149.800, tp=151.0, digits=3, point=1e-3)
    r = pm.evaluate("sig", market_price=be_trigger("LONG", 150.000, 149.800), now=NOW)
    assert r["reason_code"] == PMReason.BREAKEVEN_SET
    assert abs(r["applied_stop"] - (150.000 + 2 * 1e-2)) < 1e-9      # 150.020, NOT 150.0002


def test_be_buffer_gbpjpy_3digit():
    pm, m, tk = rig("GBPJPY", entry=190.000, sl=189.600, tp=191.0, digits=3, point=1e-3)
    r = pm.evaluate("sig", market_price=be_trigger("LONG", 190.000, 189.600), now=NOW)
    assert abs(r["applied_stop"] - (190.000 + 2 * 1e-2)) < 1e-9      # 190.020


def test_be_buffer_suffixed_usdjpy():
    # a broker suffix must not change JPY geometry — it is derived from metadata
    pm, m, tk = rig("USDJPY.a", entry=150.000, sl=149.800, tp=151.0, digits=3, point=1e-3)
    r = pm.evaluate("sig", market_price=be_trigger("LONG", 150.000, 149.800), now=NOW)
    assert abs(r["applied_stop"] - 150.020) < 1e-9


# --------------------------------------------------------------------------- #
# quote-format invariance (§17, §28, §30.13-14)
# --------------------------------------------------------------------------- #
def test_quote_format_invariance_eurusd():
    a = rig("EURUSD", entry=1.1000, sl=1.0980, digits=5, point=1e-5)
    b = rig("EURUSD", entry=1.1000, sl=1.0980, digits=4, point=1e-4)
    ra = a[0].evaluate("sig", market_price=be_trigger("LONG", 1.1000, 1.0980), now=NOW)
    rb = b[0].evaluate("sig", market_price=be_trigger("LONG", 1.1000, 1.0980), now=NOW)
    assert abs(ra["applied_stop"] - 1.1002) < 1e-9
    assert abs(rb["applied_stop"] - 1.1002) < 1e-9      # 4/5-digit economically equal


def test_quote_format_invariance_usdjpy():
    a = rig("USDJPY", entry=150.00, sl=149.80, tp=151.0, digits=3, point=1e-3)
    b = rig("USDJPY", entry=150.00, sl=149.80, tp=151.0, digits=2, point=1e-2)
    ra = a[0].evaluate("sig", market_price=be_trigger("LONG", 150.00, 149.80), now=NOW)
    rb = b[0].evaluate("sig", market_price=be_trigger("LONG", 150.00, 149.80), now=NOW)
    assert abs(ra["applied_stop"] - 150.02) < 1e-9
    assert abs(rb["applied_stop"] - 150.02) < 1e-9      # 2/3-digit economically equal


# --------------------------------------------------------------------------- #
# min-improvement is per-symbol pip (§12, §30.11-12)
# --------------------------------------------------------------------------- #
def test_min_improvement_eurusd():
    pm, m, tk = rig("EURUSD", digits=5, point=1e-5)
    assert pm._improves_q("LONG", 1.10000, 1.10010, "EURUSD")       # +1.0 pip -> improves
    assert not pm._improves_q("LONG", 1.10000, 1.10009, "EURUSD")   # +0.9 pip -> no


def test_min_improvement_usdjpy():
    pm, m, tk = rig("USDJPY", entry=150.0, sl=149.8, tp=151.0, digits=3, point=1e-3)
    assert pm._improves_q("LONG", 150.000, 150.010, "USDJPY")       # +1.0 pip -> improves
    assert not pm._improves_q("LONG", 150.000, 150.009, "USDJPY")   # +0.9 pip -> no


# --------------------------------------------------------------------------- #
# trail offset is per-symbol pip (§11, §30.9-10)
# --------------------------------------------------------------------------- #
def _to_locked(pm, direction, entry, sl):
    pm.evaluate("sig", market_price=be_trigger(direction, entry, sl), now=NOW)
    pm.evaluate("sig", market_price=pl_trigger(direction, entry, sl), now=NOW)
    assert pm.states["sig"]["phase"] == StopPhase.LOCKED


def test_trail_offset_eurusd():
    pm, m, tk = rig("EURUSD", entry=1.1000, sl=1.0980, digits=5, point=1e-5)
    _to_locked(pm, "LONG", 1.1000, 1.0980)
    r = pm.evaluate("sig", market_price=1.1050, confirmed_swing=1.1040,
                    structure_reference="hl-1", bars_since_swing=1, now=NOW)
    assert r["reason_code"] == PMReason.TRAIL_ADVANCED
    assert abs(r["applied_stop"] - (1.1040 - 1 * 1e-4)) < 1e-9       # swing - 1 pip


def test_trail_offset_usdjpy():
    pm, m, tk = rig("USDJPY", entry=150.00, sl=149.80, tp=151.0, digits=3, point=1e-3)
    _to_locked(pm, "LONG", 150.00, 149.80)
    r = pm.evaluate("sig", market_price=150.50, confirmed_swing=150.40,
                    structure_reference="hl-1", bars_since_swing=1, now=NOW)
    assert r["reason_code"] == PMReason.TRAIL_ADVANCED
    assert abs(r["applied_stop"] - (150.40 - 1 * 1e-2)) < 1e-9       # swing - 1 pip = 150.39


# --------------------------------------------------------------------------- #
# directional validity: quantization never flips geometry across entry (§20-21)
# --------------------------------------------------------------------------- #
def test_long_be_stop_stays_between_entry_and_market():
    pm, m, tk = rig("USDJPY", entry=150.00, sl=149.80, tp=151.0, digits=3, point=1e-3)
    mp = be_trigger("LONG", 150.00, 149.80)
    r = pm.evaluate("sig", market_price=mp, now=NOW)
    assert 150.00 <= r["applied_stop"] < mp                          # not flipped below entry


def test_short_be_stop_stays_between_entry_and_market():
    pm, m, tk = rig("USDJPY", direction="SHORT", entry=150.00, sl=150.20, tp=149.0,
                    digits=3, point=1e-3)
    mp = be_trigger("SHORT", 150.00, 150.20)
    r = pm.evaluate("sig", market_price=mp, now=NOW)
    assert mp < r["applied_stop"] <= 150.00                          # not flipped above entry


# --------------------------------------------------------------------------- #
# fail-closed: missing / malformed metadata -> NO modification (§6, §22, §29)
# --------------------------------------------------------------------------- #
def _expect_hold_no_modify(pm, m, market_price):
    before = len(m.modify_log)
    r = pm.evaluate("sig", market_price=market_price, now=NOW)
    assert r["reason_code"] == PMReason.DATA_INSUFFICIENT
    assert r.get("reconciliation_status") == "symbol_geometry_unavailable"
    assert len(m.modify_log) == before                              # no broker modify call
    return r


def test_missing_symbol_info_no_modification():
    pm, m, tk = rig("USDJPY", entry=150.0, sl=149.8, tp=151.0, digits=3, point=1e-3)
    del m.symbols["USDJPY"]                                          # metadata vanishes
    _expect_hold_no_modify(pm, m, be_trigger("LONG", 150.0, 149.8))
    assert m.position_by_ticket(tk).sl == 149.8                     # protective stop intact


def test_malformed_point_no_modification():
    pm, m, tk = rig("USDJPY", entry=150.0, sl=149.8, tp=151.0, digits=3, point=1e-3)
    m.symbols["USDJPY"] = mock_mt5.SymbolInfo(name="USDJPY", digits=3, point=0.0)
    _expect_hold_no_modify(pm, m, be_trigger("LONG", 150.0, 149.8))


def test_malformed_tick_size_no_modification():
    pm, m, tk = rig("USDJPY", entry=150.0, sl=149.8, tp=151.0, digits=3, point=1e-3)
    info = mock_mt5.SymbolInfo(name="USDJPY", digits=3, point=1e-3)
    info.trade_tick_size = 5e-3                                      # exotic grid (tick != point)
    m.symbols["USDJPY"] = info
    _expect_hold_no_modify(pm, m, be_trigger("LONG", 150.0, 149.8))


def test_malformed_digits_no_modification():
    pm, m, tk = rig("USDJPY", entry=150.0, sl=149.8, tp=151.0, digits=3, point=1e-3)
    m.symbols["USDJPY"] = mock_mt5.SymbolInfo(name="USDJPY", digits=99, point=1e-99)
    _expect_hold_no_modify(pm, m, be_trigger("LONG", 150.0, 149.8))


def test_naninf_metadata_no_modification():
    pm, m, tk = rig("USDJPY", entry=150.0, sl=149.8, tp=151.0, digits=3, point=1e-3)
    m.symbols["USDJPY"] = mock_mt5.SymbolInfo(name="USDJPY", digits=3, point=float("nan"))
    _expect_hold_no_modify(pm, m, be_trigger("LONG", 150.0, 149.8))
    m.symbols["USDJPY"] = mock_mt5.SymbolInfo(name="USDJPY", digits=3, point=float("inf"))
    _expect_hold_no_modify(pm, m, be_trigger("LONG", 150.0, 149.8))


# --------------------------------------------------------------------------- #
# transient failure then recovery (§22-23)
# --------------------------------------------------------------------------- #
def test_transient_metadata_failure_then_recovery():
    pm, m, tk = rig("USDJPY", entry=150.0, sl=149.8, tp=151.0, digits=3, point=1e-3)
    good = m.symbols["USDJPY"]
    del m.symbols["USDJPY"]                                          # transient loss
    _expect_hold_no_modify(pm, m, be_trigger("LONG", 150.0, 149.8))
    assert pm.states["sig"]["phase"] == StopPhase.INITIAL           # no phase change
    m.symbols["USDJPY"] = good                                       # metadata returns
    r = pm.evaluate("sig", market_price=be_trigger("LONG", 150.0, 149.8), now=NOW)
    assert r["reason_code"] == PMReason.BREAKEVEN_SET               # resumes deterministically
    assert abs(r["applied_stop"] - 150.020) < 1e-9


# --------------------------------------------------------------------------- #
# restart determinism + session-independence (§16, §21, §30.23-24)
# --------------------------------------------------------------------------- #
def test_restart_deterministic_geometry():
    a = rig("USDJPY", entry=150.0, sl=149.8, tp=151.0, digits=3, point=1e-3)
    ra = a[0].evaluate("sig", market_price=be_trigger("LONG", 150.0, 149.8), now=NOW)
    b = rig("USDJPY", entry=150.0, sl=149.8, tp=151.0, digits=3, point=1e-3)   # fresh PM/state
    rb = b[0].evaluate("sig", market_price=be_trigger("LONG", 150.0, 149.8), now=NOW)
    assert ra["applied_stop"] == rb["applied_stop"]


def test_session_independent_pip_geometry():
    # pip is symbol-specific, not session-specific: different wall-clock -> same stop
    tokyo = datetime(2024, 1, 25, 1, 0, tzinfo=timezone.utc)
    london = datetime(2024, 1, 25, 9, 0, tzinfo=timezone.utc)
    a = rig("USDJPY", entry=150.0, sl=149.8, tp=151.0, digits=3, point=1e-3)
    b = rig("USDJPY", entry=150.0, sl=149.8, tp=151.0, digits=3, point=1e-3)
    ra = a[0].evaluate("sig", market_price=be_trigger("LONG", 150.0, 149.8), now=tokyo)
    rb = b[0].evaluate("sig", market_price=be_trigger("LONG", 150.0, 149.8), now=london)
    assert ra["applied_stop"] == rb["applied_stop"] == 150.020


# --------------------------------------------------------------------------- #
# unsupported non-FX price format fails closed (§15, §30.25)
# --------------------------------------------------------------------------- #
def test_non_fx_price_format_fails_closed():
    # an index-like 1-digit price format is not a supported FX geometry
    pm, m, tk = rig("US30", entry=38000.0, sl=37900.0, tp=38200.0, digits=5, point=1e-5)
    m.symbols["US30"] = mock_mt5.SymbolInfo(name="US30", digits=1, point=0.1)
    _expect_hold_no_modify(pm, m, 38050.0)


# --------------------------------------------------------------------------- #
# no guessed-fallback / no-hardcoded-pip in the executable path (§30.26-27)
# --------------------------------------------------------------------------- #
def test_no_fallback_digits_symbol_present():
    assert not hasattr(pmmod, "_FALLBACK_DIGITS")                   # constant removed


def test_scalar_cfg_pip_size_does_not_influence_executable_geometry():
    # even an absurd scalar cfg.pip_size must NOT reach executable stop math: the
    # PM derives pip from per-symbol metadata via _cfg_for(geometry).
    bad = PositionConfig(pip_size=999.0)
    pm, m, tk = rig("EURUSD", entry=1.1000, sl=1.0980, digits=5, point=1e-5, cfg=bad)
    r = pm.evaluate("sig", market_price=be_trigger("LONG", 1.1000, 1.0980, bad), now=NOW)
    assert r["reason_code"] == PMReason.BREAKEVEN_SET
    assert abs(r["applied_stop"] - 1.1002) < 1e-9                   # 2*0.0001, NOT 2*999
