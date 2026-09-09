"""PR-3I / M13 — weekend guards (BLOCKED: weekend policy specification required).

Three distinct mechanisms exist:
  A. per-session Friday no-new-entry cutoff — session-local, now ENFORCED (see M12);
  B. a global weekend gap guard (``friday_close_policy``, UTC minute-of-day);
  C. a Sunday reopening delay (``sunday_open_policy``, UTC minute-of-day).

B and C exist as machinery but DEFAULT to None (disabled), and the repository
defines NO authoritative values for them (the only numbers, 1200/1320, are "e.g."
comments and test fixtures). Per the task's "do not invent arbitrary minute
values" rule, M13 is BLOCKED — WEEKEND POLICY SPECIFICATION REQUIRED. These tests
PROVE (1) the machinery is correct WHEN configured, (2) the defaults disable it
(the reason it is blocked), and (3) weekend-closed market data cannot fabricate an
opening range regardless. No production change is made for M13.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from forex_swing_orb.session.model import (LONDON, OverlapMode, SessionModel,
                                           SessionReason, eligibility)
from forex_swing_orb.compliance.contract import SessionConfig
from forex_swing_orb.producer.providers import Bars, validate_bars
from forex_swing_orb.producer.contract import RunnerReason

UTC = timezone.utc


def _model(friday=None, sunday=None):
    return SessionModel(enabled_sessions=(LONDON,), overlap_mode=OverlapMode.DISABLE,
                        friday_close_policy=friday, sunday_open_policy=sunday,
                        strategy_session_policy="REPORT_ONLY").validate()


FRI_1500 = datetime(2026, 1, 9, 15, 0, tzinfo=UTC)     # Fri, London active (winter GMT)
SUN_1000 = datetime(2026, 1, 11, 10, 0, tzinfo=UTC)    # Sun, London window active


# --------------------------------------------------------------------------- #
# the finding: default guards are INERT (this is why M13 is blocked)
# --------------------------------------------------------------------------- #
def test_default_config_disables_the_global_guard():
    m = _model()                                        # both policies None (defaults)
    assert eligibility(m, FRI_1500)["eligible"] is True    # not blocked on Friday
    assert eligibility(m, SUN_1000)["eligible"] is True    # not blocked on Sunday


def test_source_defines_no_authoritative_weekend_values():
    # compliance + canonical model both default to None -> no authoritative policy
    assert SessionConfig().friday_close_min is None
    assert SessionConfig().sunday_open_min is None
    assert SessionModel().friday_close_policy is None
    assert SessionModel().sunday_open_policy is None


# --------------------------------------------------------------------------- #
# the machinery IS correct when configured (Friday close boundary, >=)
# --------------------------------------------------------------------------- #
def test_friday_close_boundary_when_configured():
    m = _model(friday=14 * 60)                          # 14:00 UTC cutoff
    before = eligibility(m, datetime(2026, 1, 9, 13, 59, tzinfo=UTC))
    at = eligibility(m, datetime(2026, 1, 9, 14, 0, tzinfo=UTC))
    after = eligibility(m, datetime(2026, 1, 9, 14, 30, tzinfo=UTC))
    assert before["eligible"] is True
    assert at["reason"] == SessionReason.FRIDAY_CLOSED and at["eligible"] is False   # >= blocks
    assert after["reason"] == SessionReason.FRIDAY_CLOSED


def test_sunday_open_boundary_when_configured():
    m = _model(sunday=13 * 60)                          # reopen 13:00 UTC
    before = eligibility(m, datetime(2026, 1, 11, 12, 0, tzinfo=UTC))
    just_before = eligibility(m, datetime(2026, 1, 11, 12, 59, tzinfo=UTC))
    at = eligibility(m, datetime(2026, 1, 11, 13, 0, tzinfo=UTC))
    assert before["reason"] == SessionReason.SUNDAY_CLOSED and before["eligible"] is False
    assert just_before["reason"] == SessionReason.SUNDAY_CLOSED       # < blocks
    assert at["eligible"] is True                                     # equality reopens


# --------------------------------------------------------------------------- #
# the global guard is UTC-anchored (NOT session-local) — distinct from M12
# --------------------------------------------------------------------------- #
def test_global_guard_is_utc_anchored_independent_of_enabled_sessions():
    inst = datetime(2026, 1, 9, 14, 30, tzinfo=UTC)     # Fri 14:30 UTC
    for sids in ((LONDON,), ("SYDNEY",), ("TOKYO",), ("NEW_YORK",)):
        m = SessionModel(enabled_sessions=sids, overlap_mode=OverlapMode.DISABLE,
                         friday_close_policy=14 * 60, strategy_session_policy="REPORT_ONLY").validate()
        assert eligibility(m, inst)["reason"] == SessionReason.FRIDAY_CLOSED


def test_global_guard_no_dst_shift():
    # UTC-minute anchored: the same UTC minute blocks in winter AND summer (unlike
    # M12's session-local cutoff, which shifts with DST).
    m = _model(friday=14 * 60)
    winter = eligibility(m, datetime(2026, 1, 9, 14, 0, tzinfo=UTC))
    summer = eligibility(m, datetime(2026, 7, 3, 14, 0, tzinfo=UTC))
    assert winter["reason"] == summer["reason"] == SessionReason.FRIDAY_CLOSED


# --------------------------------------------------------------------------- #
# weekend-closed market data cannot fabricate an opening range
# --------------------------------------------------------------------------- #
def test_stale_weekend_data_blocks_entry_no_or_fabrication():
    # market closed over the weekend -> the latest closed bar is stale -> DATA_STALE,
    # so no strategy evaluation / no OR is ever constructed from a weekend gap.
    last_open = datetime(2026, 1, 9, 20, 45, tzinfo=UTC)          # last Friday M15 bar
    rows = [{"open_time": last_open - timedelta(minutes=15 * i),
             "open": 1.10, "high": 1.1002, "low": 1.0998, "close": 1.1001}
            for i in range(9, -1, -1)]
    bars = Bars("EURUSD.FX", "M15", rows)
    now = datetime(2026, 1, 11, 10, 0, tzinfo=UTC)               # Sunday, market still closed
    ok, reason = validate_bars(bars, "M15", now, max_age_sec=120,
                               continuity_bars=8, min_bars=5)
    assert not ok and reason == RunnerReason.DATA_STALE


# --------------------------------------------------------------------------- #
# restart over the weekend: policy is deterministic from (config, now)
# --------------------------------------------------------------------------- #
def test_restart_over_weekend_is_deterministic():
    m = _model(friday=14 * 60, sunday=13 * 60)
    inst = datetime(2026, 1, 11, 12, 0, tzinfo=UTC)              # Sunday pre-reopen
    a = eligibility(m, inst)
    b = eligibility(m, inst)                                     # independent re-eval (restart)
    assert a["reason"] == b["reason"] == SessionReason.SUNDAY_CLOSED


# --------------------------------------------------------------------------- #
# property E — removing weekend-policy evidence is MORE permissive when required
# (documents WHY a specification is required: None default disables the guard)
# --------------------------------------------------------------------------- #
def test_propE_removing_policy_is_more_permissive():
    inst = datetime(2026, 1, 9, 14, 30, tzinfo=UTC)             # Fri after a 14:00 cutoff
    configured = eligibility(_model(friday=14 * 60), inst)
    removed = eligibility(_model(friday=None), inst)            # policy evidence removed
    assert configured["eligible"] is False                     # guard blocks when set
    assert removed["eligible"] is True                         # None default -> more permissive
