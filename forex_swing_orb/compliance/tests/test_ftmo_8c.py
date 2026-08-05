"""Phase 8C — FTMO 2-Step Swing rule-alignment tests (M1/M2/M3/M5 + profile).

Deterministic; injected time. Complements test_compliance_engine.py (which was
migrated to the corrected model)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from forex_swing_orb.compliance import (AccountType, ComplianceConfig, Decision,
                                        FtmoConfig, FtmoProfile, ProgramType,
                                        ReasonCode as RC, ftmo_levels,
                                        prague_trading_day)
from forex_swing_orb.compliance import gates
from forex_swing_orb.compliance.contract import candidate_risk_amount
from conftest import NOW, verified_config, verified_profile


def _acct(**over):
    a = {"day_start_balance": 100000.0, "initial_balance": 100000.0, "equity": 100000.0,
         "trading_day": None, "open_position_count": 0, "open_symbols": ()}
    a.update(over); return a


def _cand(**over):
    c = {"signal_id": "0123456789abcdef", "symbol": "EURUSD.FX", "direction": "LONG",
         "entry": 1.1, "stop_loss": 1.095, "take_profit": 1.11, "risk_fraction": 0.001,
         "mtf": {"daily_bias": "U", "h4_structure": "U", "h1_setup": "S",
                 "m15_timing": "T", "aligned": True}}
    c.update(over); return c


def _ftmo(account, profile=None, cfg=None, now=NOW):
    return gates.gate_ftmo(_cand(), account, profile or verified_profile(),
                           cfg or FtmoConfig(), None, now)


# ---- M1: daily-loss basis (initial capital, from day-start balance) --------
def test_official_amounts_from_initial():
    lv = ftmo_levels(_acct(), verified_profile(), FtmoConfig())
    assert lv["official_daily_amount"] == 5000.0     # 5% of INITIAL (not day equity)
    assert lv["official_max_amount"] == 10000.0
    assert lv["official_daily_level"] == 95000.0
    assert lv["official_max_level"] == 90000.0


def test_profit_growth_does_not_increase_daily_allowance():
    # account grew to 130k day-start; allowance stays 5000 (5% of 100k initial)
    lv = ftmo_levels(_acct(day_start_balance=130000.0), verified_profile(), FtmoConfig())
    assert lv["official_daily_amount"] == 5000.0
    assert lv["official_daily_level"] == 125000.0     # NOT 130000*0.95=123500


@pytest.mark.parametrize("equity,expected", [
    (100000.0, None),
    (96000.0, None),                                   # == internal level: safe (breach iff <)
    (95999.0, RC.INTERNAL_DAILY_BUFFER_TRIP),          # one unit below internal (96000)
    (95000.0, RC.INTERNAL_DAILY_BUFFER_TRIP),          # == official level: still < internal
    (94999.0, RC.FTMO_DAILY_LOSS_BREACH)])             # one unit below official (95000)
def test_daily_boundaries(equity, expected):
    # zero candidate risk isolates the current-equity boundary (projected == equity)
    v = gates.gate_ftmo(_cand(risk_fraction=0.0), _acct(equity=equity),
                        verified_profile(), FtmoConfig(), None, NOW)
    if expected is None:
        assert v.passed
    else:
        assert not v.passed and v.reason_codes[0] == expected


def test_floating_loss_counts_immediately():
    # equity reflects floating; a floating loss pushing equity below the level breaches
    v = _ftmo(_acct(equity=94000.0))
    assert not v.passed and v.reason_codes[0] == RC.FTMO_DAILY_LOSS_BREACH


def test_floating_profit_does_not_raise_allowance():
    # equity above day-start (floating profit) still uses the fixed 5% amount
    lv = ftmo_levels(_acct(day_start_balance=100000.0), verified_profile(), FtmoConfig())
    assert lv["official_daily_level"] == 95000.0


def test_candidate_risk_uses_initial_capital():
    assert candidate_risk_amount({"risk_fraction": 0.01}, verified_profile()) == 1000.0


# ---- M2: Prague reset timezone --------------------------------------------
def test_prague_winter_vs_summer_rollover():
    # winter: Prague 00:00 == 23:00 UTC ; summer: 22:00 UTC
    assert prague_trading_day(datetime(2026, 1, 14, 23, 30, tzinfo=timezone.utc)) == "2026-01-15"
    assert prague_trading_day(datetime(2026, 7, 14, 22, 30, tzinfo=timezone.utc)) == "2026-07-15"


def test_utc_midnight_does_not_reset_but_prague_midnight_does():
    # winter UTC 00:00 -> Prague 01:00 same day (no new day yet vs 23:00 UTC boundary)
    assert prague_trading_day(datetime(2026, 1, 15, 0, 0, tzinfo=timezone.utc)) == "2026-01-15"
    assert prague_trading_day(datetime(2026, 1, 14, 22, 59, tzinfo=timezone.utc)) == "2026-01-14"
    assert prague_trading_day(datetime(2026, 1, 14, 23, 0, tzinfo=timezone.utc)) == "2026-01-15"


def test_naive_time_fails_closed():
    assert prague_trading_day(datetime(2026, 1, 15, 0, 0)) is None    # naive -> None


def test_bad_reset_timezone_rejected_by_profile():
    p = verified_profile(reset_timezone="Not/AZone")
    assert p.verification_error() == RC.PRAGUE_ROLLOVER_FAILED


# ---- M3: anchor states -----------------------------------------------------
def test_missing_anchor_fails_closed():
    v = _ftmo(_acct(day_start_balance=None))
    assert not v.passed and v.reason_codes[0] == RC.FTMO_DAILY_ANCHOR_MISSING


def test_anchor_conflict_fails_closed():
    v = _ftmo(_acct(daily_anchor_conflict=True))
    assert not v.passed and v.reason_codes[0] == RC.FTMO_DAILY_ANCHOR_CONFLICT


def test_anchor_stale_fails_closed():
    v = _ftmo(_acct(trading_day="2020-01-01"), now=NOW)   # anchor day != Prague(now)
    assert not v.passed and v.reason_codes[0] == RC.FTMO_DAILY_ANCHOR_STALE


# ---- overall max loss: static ---------------------------------------------
def test_max_loss_static_from_initial_not_trailing():
    # profit (day-start 130k) does NOT trail the max level up; stays 90k
    lv = ftmo_levels(_acct(day_start_balance=130000.0), verified_profile(), FtmoConfig())
    assert lv["official_max_level"] == 90000.0


def test_internal_max_buffer_trips_before_official():
    # drawn-down day so max (not daily) is the binding constraint
    v = _ftmo(_acct(day_start_balance=91000.0, equity=91500.0))   # 91500<92000 internal max
    assert not v.passed and v.reason_codes[0] == RC.INTERNAL_MAXIMUM_LOSS_BUFFER_TRIP


# ---- profile verification --------------------------------------------------
def test_two_step_swing_accepted():
    assert verified_profile().verification_error() is None


def test_one_step_rejected():
    assert verified_profile(program=ProgramType.FTMO_ONE_STEP).verification_error() \
        == RC.FTMO_PROGRAM_UNSUPPORTED


def test_normal_account_rejected():
    assert verified_profile(account_type=AccountType.FTMO_NORMAL).verification_error() \
        == RC.FTMO_ACCOUNT_TYPE_UNSUPPORTED


def test_unverified_profile_rejected():
    assert FtmoProfile(initial_balance=100000.0, rule_source="x",
                       rule_source_verified_at="y", profile_verified=False)\
        .verification_error() == RC.FTMO_PROFILE_UNVERIFIED


def test_missing_source_metadata_rejected():
    assert verified_profile(rule_source=None).verification_error() == RC.FTMO_PROFILE_UNVERIFIED


def test_invalid_initial_balance_rejected():
    assert verified_profile(initial_balance=0).verification_error() == RC.FTMO_INITIAL_BALANCE_INVALID
    assert verified_profile(initial_balance=None).verification_error() == RC.FTMO_INITIAL_BALANCE_INVALID


def test_unverified_profile_blocks_ftmo_gate():
    v = gates.gate_ftmo(_cand(), _acct(),
                        FtmoProfile(initial_balance=100000.0),   # unverified
                        FtmoConfig(), None, NOW)
    assert not v.passed and v.reason_codes[0] == RC.FTMO_PROFILE_UNVERIFIED


# ---- M5: Swing news/weekend are internal overlays, not FTMO rules ----------
def test_no_ftmo_news_reason_for_swing():
    # the news gate emits INTERNAL_NEWS_LOCKOUT (an overlay), never an FTMO reason
    from forex_swing_orb.compliance.news import gate_news
    from forex_swing_orb.compliance import NewsLockoutConfig
    from forex_swing_orb.bridge import serialize
    ev = {"event_id": "E", "currency": "USD", "impact": "HIGH",
          "event_timestamp": serialize.iso_utc(NOW), "verification_state": "VERIFIED"}
    v = gate_news(_cand(), {"as_of": serialize.iso_utc(NOW), "events": [ev]},
                  NewsLockoutConfig(), NOW)
    assert RC.INTERNAL_NEWS_LOCKOUT in v.reason_codes
    assert not any(r.startswith("FTMO_") for r in v.reason_codes)


def test_weekend_flat_is_internal_only_default_off():
    from datetime import timedelta
    sat = NOW + timedelta(days=3)   # Saturday 2026-01-10
    assert gates.gate_ftmo(_cand(), _acct(), verified_profile(), FtmoConfig(), None, sat).passed
    v = gates.gate_ftmo(_cand(), _acct(), verified_profile(),
                        FtmoConfig(internal_weekend_flat=True),
                        _SessionCfg(), sat)
    assert not v.passed and v.reason_codes[0] == RC.INTERNAL_WEEKEND_POLICY


class _SessionCfg:
    weekend_isoweekdays = (6, 7)


# ---- determinism -----------------------------------------------------------
def test_deterministic_levels():
    a = ftmo_levels(_acct(), verified_profile(), FtmoConfig())
    b = ftmo_levels(_acct(), verified_profile(), FtmoConfig())
    assert a == b
