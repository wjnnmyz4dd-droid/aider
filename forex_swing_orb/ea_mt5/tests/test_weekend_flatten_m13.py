"""PR-3K.1 / M13 — position-management weekend authority (independent of entry policy).

The Friday 20:00 UTC weekend flatten is the AUTHORITATIVE, unchanged management-side
policy (position/contract.py defaults; ea_mt5/position_manager._weekend_due). It is a
separate owner from the M12 entry cutoff: existing-position management continues (and
protectively flattens) regardless of whether NEW entries are weekend-ineligible.
Deterministic; MockMT5; no MT5. See docs/SESSION_EDGE_WEEKEND_POLICY.md.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

from forex_swing_orb.ea_mt5 import mock_mt5
from forex_swing_orb.ea_mt5.position_manager import PositionManager
from forex_swing_orb.position import DEFAULT_PM_CONFIG, spec
from forex_swing_orb.position.contract import PMReason, StopPhase, WeekendPolicy

CFG = DEFAULT_PM_CONFIG
BUY = mock_mt5.ORDER_TYPE_BUY
UTC = timezone.utc
FRI_2000_UTC = datetime(2026, 1, 9, 20, 0, tzinfo=UTC)   # Friday 20:00 UTC (== cutoff)
FRI_1800_UTC = datetime(2026, 1, 9, 18, 0, tzinfo=UTC)   # Friday, before the flatten
SAT_1000_UTC = datetime(2026, 1, 10, 10, 0, tzinfo=UTC)  # Saturday (after Friday)


def _rig(entry=1.1000, sl=1.0980, tp=1.1100):
    m = mock_mt5.MockMT5(); m.add_symbol("EURUSD")
    res = m.order_send({"symbol": "EURUSD", "volume": 0.10, "type": BUY,
                        "price": entry, "sl": sl, "tp": tp, "comment": "sig"})
    pm = PositionManager(m, Path(tempfile.mkdtemp()) / "pm.jsonl", CFG)
    pm.register("sig", res.order, "EURUSD", "LONG", entry, sl, tp, FRI_1800_UTC)
    return pm, m


def _be_price():
    R = spec.initial_risk("LONG", 1.1000, 1.0980)
    return 1.1000 + CFG.breakeven_trigger_r * R


# --------------------------------------------------------------------------- #
# 3 — Friday 20:00 UTC weekend flatten is unchanged and authoritative
# --------------------------------------------------------------------------- #
def test_3_pm_weekend_flatten_defaults_unchanged():
    assert CFG.weekend_policy == WeekendPolicy.FLATTEN
    assert CFG.weekend_cutoff_dow == 4            # Friday (Mon=0), UTC
    assert CFG.weekend_cutoff_hour_utc == 20      # 20:00 UTC, DST-immune


def test_3_pm_flattens_at_friday_2000_utc():
    pm, m = _rig()
    r = pm.evaluate("sig", market_price=1.1005, now=FRI_2000_UTC)
    assert r["reason_code"] == PMReason.WEEKEND_EXIT       # inclusive at 20:00 UTC


def test_3_pm_flattens_on_saturday():
    pm, m = _rig()
    r = pm.evaluate("sig", market_price=1.1005, now=SAT_1000_UTC)
    assert r["reason_code"] == PMReason.WEEKEND_EXIT       # any day after Friday


def test_3_pm_does_not_flatten_before_cutoff():
    pm, m = _rig()
    r = pm.evaluate("sig", market_price=1.1005, now=FRI_1800_UTC)
    assert r["reason_code"] != PMReason.WEEKEND_EXIT       # 18:00 UTC < cutoff


# --------------------------------------------------------------------------- #
# 4 — existing-position management continues while entries may be blocked
# --------------------------------------------------------------------------- #
def test_4_management_active_before_weekend_cutoff():
    pm, m = _rig()
    n = len(m.modify_log)
    r = pm.evaluate("sig", market_price=_be_price(), now=FRI_1800_UTC)
    assert r["reason_code"] != PMReason.WEEKEND_EXIT
    assert r["reason_code"] != PMReason.DATA_STALE
    assert len(m.modify_log) > n                          # a management stop move occurred
    assert pm.states["sig"]["phase"] != StopPhase.CLOSED


def test_4_management_acts_when_entries_are_blocked():
    # at/after the weekend cutoff (when NEW entries are M12-blocked upstream), the PM
    # still ACTS on the open position (protective flatten) — management is not disabled.
    pm, m = _rig()
    r = pm.evaluate("sig", market_price=1.1005, now=FRI_2000_UTC)
    assert r["reason_code"] == PMReason.WEEKEND_EXIT


# --------------------------------------------------------------------------- #
# F — single owner: the PM does not implement the M12 entry cutoff
# --------------------------------------------------------------------------- #
def test_F_pm_has_no_entry_cutoff_authority():
    src = (Path(__file__).resolve().parents[1] / "position_manager.py").read_text()
    for banned in ("is_friday_no_new_entry", "FRIDAY_NO_NEW_ENTRY",
                   "friday_no_new_entry_local_hour", "_session_trade_eligible"):
        assert banned not in src                          # entry authority stays in the producer
