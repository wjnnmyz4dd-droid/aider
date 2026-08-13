"""PR-3I / M8 — account-snapshot freshness (single-observation authority).

A NEW ENTRY may use account state only from a single, sufficiently-fresh
observation. Freshness is enforced by the producer's ``validate_account`` against
the snapshot's ``as_of`` (the synchronous observation instant) using the existing
source-supported threshold ``RunnerConfig.max_account_age_sec`` (default 60s) — no
new TTL is invented. This PR hardens the edge cases (naive/future/clock-rollback)
and proves freshness cannot be bypassed. Deterministic; no networking.
"""

from __future__ import annotations

import pytest

from forex_swing_orb.bridge import serialize
from forex_swing_orb.compliance.contract import (FtmoConfig, FtmoProfile,
                                                 ftmo_levels)
from forex_swing_orb.producer.contract import CycleOutcome, RunnerReason
from forex_swing_orb.producer.mock_providers import MockAccountProvider
from forex_swing_orb.producer.providers import validate_account
from conftest import NOW

MAX = 60


def _iso(dt):
    return serialize.iso_utc(dt)


def _snap(now=NOW, **over):
    """A complete, valid account snapshot (fresh by default)."""
    s = {"balance": 100000.0, "equity": 100000.0, "initial_balance": 100000.0,
         "day_start_balance": 100000.0, "day_start_equity": 100000.0,
         "open_position_count": 0, "open_symbols": (), "terminal_connected": True,
         "as_of": _iso(now), "trading_day": None, "is_demo": True,
         "account_type": "DEMO"}
    s.update(over)
    return s


def _after(sec):
    from datetime import timedelta
    return NOW + timedelta(seconds=sec)


# --------------------------------------------------------------------------- #
# 1-8 direct freshness invariants
# --------------------------------------------------------------------------- #
def test_1_fresh_snapshot_passes():
    assert validate_account(_snap(), NOW, MAX) == (True, RunnerReason.OK)


def test_2_stale_snapshot_blocks():
    ok, reason = validate_account(_snap(as_of=_iso(_after(-120))), NOW, MAX)
    assert not ok and reason == RunnerReason.ACCOUNT_STALE


def test_3_future_timestamp_blocks():
    ok, reason = validate_account(_snap(as_of=_iso(_after(120))), NOW, MAX)
    assert not ok and reason == RunnerReason.ACCOUNT_FUTURE


def test_4_naive_timestamp_blocks():
    # naive (offset-less) as_of is not a trustworthy observation instant
    ok, reason = validate_account(_snap(as_of="2026-01-07T10:00:00"), NOW, MAX)
    assert not ok and reason == RunnerReason.ACCOUNT_UNAVAILABLE


def test_5_missing_timestamp_blocks():
    ok, reason = validate_account(_snap(as_of=None), NOW, MAX)
    assert not ok and reason == RunnerReason.ACCOUNT_UNAVAILABLE


def test_6_trading_day_none_cannot_bypass_freshness():
    # trading_day=None must NOT skip the as_of freshness gate
    fresh = validate_account(_snap(trading_day=None), NOW, MAX)
    stale = validate_account(_snap(trading_day=None, as_of=_iso(_after(-120))), NOW, MAX)
    assert fresh == (True, RunnerReason.OK)
    assert stale == (False, RunnerReason.ACCOUNT_STALE)


def test_7_cached_disconnect_state_blocks():
    # a broker disconnect that returns cached/old account state -> stale as_of blocks
    ok, reason = validate_account(_snap(as_of=_iso(_after(-3600))), NOW, MAX)
    assert not ok and reason == RunnerReason.ACCOUNT_STALE


def test_8_malformed_timestamp_blocks():
    ok, reason = validate_account(_snap(as_of="not-a-timestamp"), NOW, MAX)
    assert not ok and reason == RunnerReason.ACCOUNT_UNAVAILABLE


# --------------------------------------------------------------------------- #
# 9 FTMO accounting unchanged when snapshot is fresh
# --------------------------------------------------------------------------- #
def test_9_ftmo_levels_unchanged_when_fresh():
    prof = FtmoProfile(initial_balance=100000.0, daily_loss_pct=0.05,
                       maximum_loss_pct=0.10)
    lv = ftmo_levels(_snap(), prof, FtmoConfig(safety_buffer_fraction=0.20))
    assert lv["official_daily_level"] == 95000.0        # 100000 - 0.05*100000
    assert lv["internal_daily_level"] == 96000.0        # 100000 - 0.05*100000*0.8
    assert lv["official_max_level"] == 90000.0          # static 10%


# --------------------------------------------------------------------------- #
# 10 freshness failure blocks ALL enabled sessions/symbols
# --------------------------------------------------------------------------- #
def test_10_freshness_failure_blocks_all_symbols(make_runner):
    acct = MockAccountProvider(NOW)
    acct.set(as_of=_iso(_after(-3600)))                 # stale
    runner, _ = make_runner(symbols=("EURUSD.FX", "GBPUSD.FX"), account=acct, now=NOW)
    results = runner.run_cycle(NOW)
    rejected = [r for r in results if r.outcome == CycleOutcome.ACCOUNT_REJECTED]
    assert {r.symbol for r in rejected} == {"EURUSD.FX", "GBPUSD.FX"}
    assert all(RunnerReason.ACCOUNT_STALE in r.reason_codes for r in rejected)
    assert not any(r.wrote_bridge for r in results)


# --------------------------------------------------------------------------- #
# property A — older account state never authorizes more permissively
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("age_sec", [0, 30, 59, 60, 61, 120, 3600])
def test_propA_older_never_more_permissive(age_sec):
    ok, _ = validate_account(_snap(as_of=_iso(_after(-age_sec))), NOW, MAX)
    assert ok == (age_sec <= MAX)


def test_propA_monotone_block_beyond_threshold():
    ages = [0, 60, 61, 120, 600, 3600]
    oks = [validate_account(_snap(as_of=_iso(_after(-a))), NOW, MAX)[0] for a in ages]
    # once blocked, never becomes permissive again as the snapshot gets older
    blocked_from = next(i for i, ok in enumerate(oks) if not ok)
    assert all(not ok for ok in oks[blocked_from:])


# --------------------------------------------------------------------------- #
# property F — restart cannot rejuvenate stale account state
# --------------------------------------------------------------------------- #
def test_propF_restart_does_not_rejuvenate():
    stale = _snap(as_of=_iso(_after(-120)))
    # validate_account is stateless: an independent re-invocation (as after a
    # process restart) reaches the SAME verdict from the same snapshot + now.
    first = validate_account(stale, NOW, MAX)
    second = validate_account(dict(stale), NOW, MAX)
    assert first == second == (False, RunnerReason.ACCOUNT_STALE)
