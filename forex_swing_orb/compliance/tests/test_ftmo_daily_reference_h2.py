"""PR-3A H2: the FTMO daily-loss reference is the HIGHER of day-start balance and
day-start equity (a Swing account holding a floating winner across the Prague
rollover). Deterministic arithmetic proofs. No MT5.

Formulas (from compliance.contract.ftmo_levels):
  day_start_reference  = max(day_start_balance, day_start_equity)
  official_daily_level = day_start_reference - daily_loss_pct * initial_balance
  official_max_level   = initial_balance     - maximum_loss_pct * initial_balance
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from forex_swing_orb.compliance.contract import FtmoConfig, ftmo_levels      # noqa: E402
from conftest import verified_profile                                        # noqa: E402

CFG = FtmoConfig()
PROF = verified_profile()          # initial_balance=100000, 5% daily, 10% max


def _lv(**acct):
    return ftmo_levels(acct, PROF, CFG)


def test_equity_higher_than_balance_uses_equity():
    lv = _lv(day_start_balance=100000.0, day_start_equity=103000.0)
    assert lv["day_start_reference"] == 103000.0
    assert lv["official_daily_level"] == 103000.0 - 5000.0        # 98000
    assert lv["official_max_level"] == 100000.0 - 10000.0         # 90000 (static, unchanged)


def test_balance_higher_than_equity_uses_balance():
    lv = _lv(day_start_balance=100000.0, day_start_equity=98000.0)
    assert lv["day_start_reference"] == 100000.0
    assert lv["official_daily_level"] == 95000.0


def test_equal_balance_and_equity():
    lv = _lv(day_start_balance=100000.0, day_start_equity=100000.0)
    assert lv["day_start_reference"] == 100000.0
    assert lv["official_daily_level"] == 95000.0


def test_overnight_floating_winner_raises_reference():
    # winner carried across rollover: equity 106k > balance 100k -> level from 106k
    lv = _lv(day_start_balance=100000.0, day_start_equity=106000.0)
    assert lv["official_daily_level"] == 101000.0                  # 106000 - 5000


def test_floating_loser_uses_balance_not_lower_equity():
    # a floating loser at rollover must NOT lower the reference below balance
    lv = _lv(day_start_balance=100000.0, day_start_equity=96000.0)
    assert lv["day_start_reference"] == 100000.0
    assert lv["official_daily_level"] == 95000.0


def test_legacy_anchor_without_equity_falls_back_to_balance():
    lv = _lv(day_start_balance=100000.0)                           # no day_start_equity
    assert lv["day_start_reference"] == 100000.0
    assert lv["official_daily_level"] == 95000.0


def test_threshold_boundaries_one_unit_each_side():
    lv = _lv(day_start_balance=100000.0, day_start_equity=103000.0)
    level = lv["official_daily_level"]                             # 98000
    # breach iff equity < level (equality is safe) — proven by the numeric edge
    assert (98000.0 < level) is False                             # exactly at level: safe
    assert (97999.99 < level) is True                            # one unit below: breach
    assert (98000.01 < level) is False                          # one unit above: safe


def test_mid_day_cold_start_without_anchor_fails_closed():
    assert ftmo_levels({}, PROF, CFG) is None                     # no day_start_balance
    assert ftmo_levels({"day_start_balance": 0.0,
                        "day_start_equity": 100000.0}, PROF, CFG) is None


def test_nan_inf_balance_fails_closed():
    assert _lv(day_start_balance=float("nan"), day_start_equity=100000.0) is None
    assert _lv(day_start_balance=float("inf"), day_start_equity=100000.0) is None


def test_nan_equity_falls_back_to_balance_not_open():
    # a non-finite equity must not corrupt the reference — it falls back to balance
    lv = _lv(day_start_balance=100000.0, day_start_equity=float("nan"))
    assert lv is not None and lv["day_start_reference"] == 100000.0
