"""PR-4A — SessionProfile contract: exact OR windows, strategy entry windows,
Friday cutoffs, DST-aware windowing, canonical ordering, and (critically) the
London profile reproducing the frozen engine's DEFAULT_CONFIG exactly. No MT5."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from forex_swing_orb.session import profiles as P                            # noqa: E402

UTC = timezone.utc


def _p(sid):
    return P.profile_for(sid)


# --------------------------------------------------------------------------- #
# exact OR windows / entry windows / Friday cutoffs (§2, §3, §4)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("sid,tz,or_start,or_end,entry_end,friday", [
    ("SYDNEY",   "Australia/Sydney",  7,  8, 20, 19),
    ("TOKYO",    "Asia/Tokyo",        9, 10, 22, 21),
    ("LONDON",   "Europe/London",     8,  9, 21, 20),
    ("NEW_YORK", "America/New_York",  8,  9, 21, 20),
])
def test_profile_windows_exact(sid, tz, or_start, or_end, entry_end, friday):
    p = _p(sid)
    assert p.timezone == tz
    assert (p.or_start_local_hour, p.or_start_local_minute) == (or_start, 0)
    assert p.or_end_local_hour == or_end
    assert p.strategy_entry_end_local_hour == entry_end       # OR end + 12h
    assert p.friday_no_new_entry_local_hour == friday          # entry end - 1h


def test_all_four_supported_in_canonical_order():
    assert P.SUPPORTED_SESSION_IDS == ("SYDNEY", "TOKYO", "LONDON", "NEW_YORK")


# --------------------------------------------------------------------------- #
# London GOLDEN: the profile's engine overrides == the frozen DEFAULT_CONFIG (§8)
# --------------------------------------------------------------------------- #
def test_london_overrides_match_frozen_default_config():
    import importlib.util
    path = REPO_ROOT / "forex_swing_orb" / "run_dir" / "code" / "signal_engine.py"
    spec = importlib.util.spec_from_file_location("se_golden", path)
    se = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(se)
    dc = se.DEFAULT_CONFIG
    ov = _p("LONDON").engine_overrides()
    for key in ("session_id", "session_tz", "or_start_local_hour",
                "or_start_local_minute", "or_window_minutes",
                "session_end_local_hour", "friday_no_new_entry_local_hour"):
        assert ov[key] == dc[key], key


def test_engine_overrides_carry_no_geometry():
    # geometry (breakout/stop/RR/width) is SHARED, never per-session in v1
    ov = _p("TOKYO").engine_overrides()
    for forbidden in ("breakout_min_pips", "stop_atr_mult", "rr_target",
                      "min_width_atr", "risk_pct"):
        assert forbidden not in ov


# --------------------------------------------------------------------------- #
# strategy-window membership is DST-aware and per-session (§21, §22)
# --------------------------------------------------------------------------- #
def test_london_window_membership_winter():
    p = _p("LONDON")
    # winter (GMT): London local == UTC
    assert p.is_within_strategy_window(datetime(2026, 1, 7, 8, 0, tzinfo=UTC)) is True   # 08:00
    assert p.is_within_strategy_window(datetime(2026, 1, 7, 7, 59, tzinfo=UTC)) is False # 07:59
    assert p.is_within_strategy_window(datetime(2026, 1, 7, 20, 59, tzinfo=UTC)) is True # 20:59
    assert p.is_within_strategy_window(datetime(2026, 1, 7, 21, 0, tzinfo=UTC)) is False # 21:00


def test_london_window_membership_summer_bst():
    p = _p("LONDON")
    # summer (BST = UTC+1): 08:00 London == 07:00 UTC
    assert p.is_within_strategy_window(datetime(2026, 7, 7, 7, 0, tzinfo=UTC)) is True
    assert p.is_within_strategy_window(datetime(2026, 7, 7, 6, 59, tzinfo=UTC)) is False


def test_tokyo_non_dst_stable():
    p = _p("TOKYO")     # Asia/Tokyo never observes DST -> stable year-round
    # 09:00 Tokyo == 00:00 UTC; window [09:00,22:00) Tokyo == [00:00,13:00) UTC
    for month in (1, 7):
        assert p.is_within_strategy_window(datetime(2026, month, 7, 0, 0, tzinfo=UTC)) is True
        assert p.is_within_strategy_window(datetime(2026, month, 7, 12, 59, tzinfo=UTC)) is True
        assert p.is_within_strategy_window(datetime(2026, month, 7, 13, 0, tzinfo=UTC)) is False


def test_new_york_us_dst_shift():
    p = _p("NEW_YORK")
    # winter (EST=UTC-5): 08:00 NY == 13:00 UTC ; summer (EDT=UTC-4): 08:00 NY == 12:00 UTC
    assert p.is_within_strategy_window(datetime(2026, 1, 7, 13, 0, tzinfo=UTC)) is True
    assert p.is_within_strategy_window(datetime(2026, 1, 7, 12, 59, tzinfo=UTC)) is False
    assert p.is_within_strategy_window(datetime(2026, 7, 7, 12, 0, tzinfo=UTC)) is True
    assert p.is_within_strategy_window(datetime(2026, 7, 7, 11, 59, tzinfo=UTC)) is False


def test_sydney_southern_hemisphere_dst():
    p = _p("SYDNEY")
    # Sydney DST is opposite phase: AEDT (UTC+11) in Jan, AEST (UTC+10) in Jul.
    # 07:00 Sydney == 20:00 UTC (Jan, +11) vs 21:00 UTC (Jul, +10)
    assert p.is_within_strategy_window(datetime(2026, 1, 6, 20, 0, tzinfo=UTC)) is True
    assert p.is_within_strategy_window(datetime(2026, 1, 6, 19, 59, tzinfo=UTC)) is False
    assert p.is_within_strategy_window(datetime(2026, 7, 6, 21, 0, tzinfo=UTC)) is True
    assert p.is_within_strategy_window(datetime(2026, 7, 6, 20, 59, tzinfo=UTC)) is False


def test_naive_now_fails_closed():
    assert _p("LONDON").is_within_strategy_window(datetime(2026, 1, 7, 10, 0)) is False
    assert _p("LONDON").is_within_strategy_window(None) is False


# --------------------------------------------------------------------------- #
# profiles_for: validation, dedup, canonical order (§11, §24)
# --------------------------------------------------------------------------- #
def test_profiles_for_canonical_order_regardless_of_input_order():
    a = tuple(p.session_id for p in P.profiles_for(("LONDON", "NEW_YORK")))
    b = tuple(p.session_id for p in P.profiles_for(("NEW_YORK", "LONDON")))
    assert a == b == ("LONDON", "NEW_YORK")


def test_profiles_for_dedup():
    got = tuple(p.session_id for p in P.profiles_for(("LONDON", "LONDON")))
    assert got == ("LONDON",)


def test_profiles_for_all():
    got = tuple(p.session_id for p in P.profiles_for(P.SUPPORTED_SESSION_IDS))
    assert got == ("SYDNEY", "TOKYO", "LONDON", "NEW_YORK")


def test_profiles_for_unknown_fails_closed():
    with pytest.raises(P.SessionProfileError):
        P.profiles_for(("ATLANTIS",))


def test_profiles_for_empty_fails_closed():
    with pytest.raises(P.SessionProfileError):
        P.profiles_for(())


def test_profile_for_unknown_fails_closed():
    with pytest.raises(P.SessionProfileError):
        P.profile_for("MARS")
