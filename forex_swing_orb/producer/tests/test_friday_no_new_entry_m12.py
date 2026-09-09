"""PR-3I / M12 — per-session Friday no-new-entry cutoff BLOCKS new entries.

Old finding: the Friday cutoff only forced an exit and never blocked entry. Fix:
the producer's per-session eligibility now blocks NEW ENTRY authorization at/after
each session's own ``friday_no_new_entry_local_hour`` (session-local, DST-aware).
Open-position MANAGEMENT (a separate service) is untouched. This enforces the
profile's already-declared cutoff — no ORB math, frozen engine, or profile hours
are changed. Deterministic; no networking.

Derived per-session cutoffs (local): SYDNEY 19, TOKYO 21, LONDON 20, NEW_YORK 20.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from forex_swing_orb.producer.contract import CycleOutcome, RunnerReason
from forex_swing_orb.session.profiles import profile_for

UTC = timezone.utc
CUTOFF = {"SYDNEY": 19, "TOKYO": 21, "LONDON": 20, "NEW_YORK": 20}
FRIDAY = (2026, 1, 9)          # a Friday; THURSDAY 2026-01-08; SATURDAY 2026-01-10


def _local(profile, y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=ZoneInfo(profile.timezone))


# --------------------------------------------------------------------------- #
# per-session cutoff correctness (session-local)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("sid", ["SYDNEY", "TOKYO", "LONDON", "NEW_YORK"])
def test_before_cutoff_not_blocked(sid):
    p = profile_for(sid)
    assert p.is_friday_no_new_entry(_local(p, *FRIDAY, CUTOFF[sid] - 1)) is False


@pytest.mark.parametrize("sid", ["SYDNEY", "TOKYO", "LONDON", "NEW_YORK"])
def test_exact_cutoff_blocks(sid):
    p = profile_for(sid)
    assert p.is_friday_no_new_entry(_local(p, *FRIDAY, CUTOFF[sid])) is True


@pytest.mark.parametrize("sid", ["SYDNEY", "TOKYO", "LONDON", "NEW_YORK"])
def test_after_cutoff_blocks(sid):
    p = profile_for(sid)
    assert p.is_friday_no_new_entry(_local(p, *FRIDAY, CUTOFF[sid] + 1, 15)) is True


@pytest.mark.parametrize("sid", ["SYDNEY", "TOKYO", "LONDON", "NEW_YORK"])
def test_thursday_at_cutoff_hour_not_blocked(sid):
    p = profile_for(sid)                      # Thursday same clock -> Friday gate silent
    assert p.is_friday_no_new_entry(_local(p, 2026, 1, 8, CUTOFF[sid])) is False


def test_no_session_uses_another_sessions_cutoff():
    # a single instant = Friday 20:00 UTC (London's cutoff). Only LONDON is blocked;
    # each other profile evaluates its OWN clock -> different day/hour, not blocked.
    inst = datetime(2026, 1, 9, 20, 0, tzinfo=UTC)
    assert profile_for("LONDON").is_friday_no_new_entry(inst) is True
    assert profile_for("NEW_YORK").is_friday_no_new_entry(inst) is False   # 15:00 Fri NY
    assert profile_for("SYDNEY").is_friday_no_new_entry(inst) is False      # Sat 07:00 Sydney
    assert profile_for("TOKYO").is_friday_no_new_entry(inst) is False       # Sat 05:00 Tokyo


def test_naive_now_fails_closed():
    assert profile_for("LONDON").is_friday_no_new_entry(None) is True
    assert profile_for("LONDON").is_friday_no_new_entry(
        datetime(2026, 1, 9, 20, 0)) is True                # naive -> block


# --------------------------------------------------------------------------- #
# DST correctness — same UTC instant, different verdict across the DST boundary
# --------------------------------------------------------------------------- #
def test_dst_conversion_correct_london():
    p = profile_for("LONDON")
    # winter (GMT): 19:00 UTC == 19:00 London (before 20:00 cutoff) -> not blocked
    assert p.is_friday_no_new_entry(datetime(2026, 1, 9, 19, 0, tzinfo=UTC)) is False
    # summer (BST=UTC+1): 19:00 UTC == 20:00 London (AT cutoff) -> blocked
    assert p.is_friday_no_new_entry(datetime(2026, 7, 3, 19, 0, tzinfo=UTC)) is True


# --------------------------------------------------------------------------- #
# integration through the runner (default implicit LONDON profile)
# --------------------------------------------------------------------------- #
def test_runner_blocks_entry_at_friday_cutoff(make_runner):
    at_cutoff = datetime(2026, 1, 9, 20, 0, tzinfo=UTC)      # London 20:00 Fri
    runner, _ = make_runner(now=at_cutoff)
    results = runner.run_cycle(at_cutoff)
    assert any(r.outcome == CycleOutcome.SESSION_INELIGIBLE
               and RunnerReason.FRIDAY_NO_NEW_ENTRY in r.reason_codes for r in results)
    assert not any(r.wrote_bridge for r in results)          # no new entry authorized


def test_runner_allows_before_friday_cutoff(make_runner):
    before = datetime(2026, 1, 9, 19, 0, tzinfo=UTC)         # London 19:00 Fri
    runner, _ = make_runner(now=before)
    results = runner.run_cycle(before)
    assert not any(RunnerReason.FRIDAY_NO_NEW_ENTRY in r.reason_codes for r in results)


def test_armed_before_triggered_after_cutoff_blocked(make_runner):
    # a setup that would confirm AFTER the cutoff is never evaluated: the runner
    # skips strategy evaluation for the session once the Friday gate fires.
    after = datetime(2026, 1, 9, 20, 30, tzinfo=UTC)
    runner, _ = make_runner(now=after)
    results = runner.run_cycle(after)
    assert not any(r.wrote_bridge for r in results)
    assert any(RunnerReason.FRIDAY_NO_NEW_ENTRY in r.reason_codes for r in results)


# --------------------------------------------------------------------------- #
# management is unaffected — the M12 gate lives ONLY in the producer entry path
# --------------------------------------------------------------------------- #
def test_management_path_has_no_friday_entry_gate():
    root = Path(__file__).resolve().parents[2]
    for rel in ("manage/service.py", "ea_mt5/position_manager.py"):
        src = (root / rel).read_text()
        assert "friday_no_new_entry" not in src        # managers never block entries


# --------------------------------------------------------------------------- #
# property D — moving Friday time before -> after cutoff cannot create an entry
# --------------------------------------------------------------------------- #
def test_propD_after_cutoff_never_authorizes():
    p = profile_for("LONDON")
    blocked = [p.is_friday_no_new_entry(_local(p, *FRIDAY, h)) for h in (17, 18, 19, 20, 21, 22)]
    # monotone non-decreasing: once the cutoff blocks, later hours stay blocked
    assert blocked == [False, False, False, True, True, True]
    assert all(blocked[i] <= blocked[i + 1] for i in range(len(blocked) - 1))
