"""PR-3A.2: DailyAnchorTracker rollover semantics — a new day's anchor is captured
ONLY when the process provably observed the trading-day rollover within one producer
cadence. Cold-start / stalled / clock-jumped / concurrent producers FAIL CLOSED and
can never label post-rollover current account state as historical day-start state.

These tests validate the FTMO ACCOUNTING INVARIANT (the captured/blocked anchor and
the resulting ftmo_levels reference), not window membership. Deterministic; no MT5.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from forex_swing_orb.bridge import serialize                                 # noqa: E402
from forex_swing_orb.compliance.contract import FtmoConfig, ftmo_levels      # noqa: E402
from forex_swing_orb.live.providers import DailyAnchorTracker                 # noqa: E402

UTC = timezone.utc
CADENCE = 900                                            # production M15 cadence (s)
# cadence + min(cadence*0.5, 120) = 900 + 120 = 1020s (17 min) max observation gap.

# --- winter (Prague = UTC+1): trading day 2026-01-07 ------------------------ #
# prior-day observation at Prague 23:55 (day 01-06) then rollover at Prague 00:05
# (day 01-07) -> 10-min gap, within the 17-min bound -> a valid rollover capture.
W_PREV = datetime(2026, 1, 6, 22, 55, tzinfo=UTC)       # Prague 23:55 day 01-06
W_ROLL = datetime(2026, 1, 6, 23, 5, tzinfo=UTC)        # Prague 00:05 day 01-07 (gap 10m)
W_ROLL_LATE = datetime(2026, 1, 6, 23, 45, tzinfo=UTC)  # Prague 00:45 day 01-07 (gap 50m)
W_MIDDAY = datetime(2026, 1, 7, 11, 0, tzinfo=UTC)      # Prague 12:00 day 01-07
# fresh cold-start instants across the first Prague hour of day 01-07:
W_0001 = datetime(2026, 1, 6, 23, 1, tzinfo=UTC)        # Prague 00:01
W_0015 = datetime(2026, 1, 6, 23, 15, tzinfo=UTC)       # Prague 00:15
W_0045 = datetime(2026, 1, 6, 23, 45, tzinfo=UTC)       # Prague 00:45
W_0059 = datetime(2026, 1, 6, 23, 59, tzinfo=UTC)       # Prague 00:59
# --- summer (Prague = UTC+2, DST): trading day 2026-07-07 ------------------- #
S_PREV = datetime(2026, 7, 6, 21, 55, tzinfo=UTC)       # Prague 23:55 day 07-06
S_ROLL = datetime(2026, 7, 6, 22, 5, tzinfo=UTC)        # Prague 00:05 day 07-07 (gap 10m)

PROFILE = SimpleNamespace(initial_balance=100000.0, daily_loss_pct=0.05,
                          maximum_loss_pct=0.10)


def _tr(tmp_path, name="a.json"):
    return DailyAnchorTracker(str(tmp_path / name), cadence_sec=CADENCE)


def _rec(tr, now, bal=100000.0, eq=100000.0):
    return tr.record(now, bal, equity=eq, initial_balance=100000.0, daily_loss_pct=0.05)


def _prime_then_roll(tr, roll=W_ROLL, prev=W_PREV, roll_bal=100000.0, roll_eq=100000.0):
    """Observe the prior trading day, then observe the rollover -> returns the
    rollover record (a captured anchor when the gap is within bound)."""
    _rec(tr, prev)
    return _rec(tr, roll, bal=roll_bal, eq=roll_eq)


# --------------------------------------------------------------------------- #
# Fresh cold-start across the first Prague hour -> ALWAYS blocked (§22.1-4).
# Clock proximity to midnight is not proof of a rollover observation.
# --------------------------------------------------------------------------- #
def test_fresh_cold_start_blocked_at_every_post_rollover_minute(tmp_path):
    for i, now in enumerate((W_0001, W_0015, W_0045, W_0059, W_MIDDAY)):
        tr = _tr(tmp_path, f"a{i}.json")
        rec = _rec(tr, now, bal=48000.0, eq=48000.0)
        assert rec.get("anchor_unavailable") is True, now
        assert rec.get("anchor_reason") == DailyAnchorTracker.R_COLD_START
        assert "day_start_balance" not in rec
        assert not (tmp_path / f"a{i}.json").exists()     # nothing persisted


# --------------------------------------------------------------------------- #
# §22.5 — a healthy continuous rollover captures a complete balance+equity anchor.
# --------------------------------------------------------------------------- #
def test_healthy_continuous_rollover_captures_complete_anchor(tmp_path):
    tr = _tr(tmp_path)
    rec = _prime_then_roll(tr, roll_bal=99000.0, roll_eq=99500.0)
    assert rec["day_start_balance"] == 99000.0
    assert rec["day_start_equity"] == 99500.0
    assert rec["anchor_schema_version"] == 2
    assert rec["observation_gap_sec"] == 600.0            # 10 min, within 1020s bound
    # the captured anchor drives a correct FTMO reference (max of balance/equity):
    lv = ftmo_levels({"day_start_balance": rec["day_start_balance"],
                      "day_start_equity": rec["day_start_equity"]}, PROFILE, FtmoConfig())
    assert lv["day_start_reference"] == 99500.0


# --------------------------------------------------------------------------- #
# §22.6 / §15 — an excessive rollover gap (stall/sleep/disconnect) is blocked,
# proving the old fail-open arithmetic (capturing a late, lower value) cannot occur.
# --------------------------------------------------------------------------- #
def test_excessive_rollover_gap_blocked(tmp_path):
    tr = _tr(tmp_path)
    _rec(tr, W_PREV)                                      # last prior-day obs 23:55
    rec = _rec(tr, W_ROLL_LATE, bal=48000.0, eq=48000.0)  # 50-min gap -> blocked
    assert rec.get("anchor_unavailable") is True
    assert rec.get("anchor_reason") == DailyAnchorTracker.R_MISSED_ROLLOVER
    assert "day_start_balance" not in rec


def test_large_stall_hours_blocked(tmp_path):
    tr = _tr(tmp_path)
    _rec(tr, datetime(2026, 1, 6, 22, 30, tzinfo=UTC))    # Prague 23:30 day 01-06
    rec = _rec(tr, datetime(2026, 1, 7, 9, 0, tzinfo=UTC), bal=44000.0, eq=44000.0)  # Prague 10:00
    assert rec.get("anchor_unavailable") is True
    assert rec.get("anchor_reason") == DailyAnchorTracker.R_MISSED_ROLLOVER


# --------------------------------------------------------------------------- #
# §22.7 — backwards / non-monotonic host clock cannot establish an anchor.
# --------------------------------------------------------------------------- #
def test_backwards_clock_blocked(tmp_path):
    tr = _tr(tmp_path)
    _rec(tr, W_ROLL)                                      # observe day 01-07 first
    rec = _rec(tr, W_PREV, bal=48000.0, eq=48000.0)       # jump BACK to day 01-06
    assert rec.get("anchor_unavailable") is True
    assert rec.get("anchor_reason") == DailyAnchorTracker.R_CLOCK_BACKWARDS


def test_naive_datetime_fails_closed(tmp_path):
    # naive instants have no sound Prague trading-day identity -> None (caller blocks)
    assert _rec(_tr(tmp_path), datetime(2026, 1, 7, 0, 5)) is None


# --------------------------------------------------------------------------- #
# §22.8 — a multi-day (weekend) gap is NOT proof of a continuous rollover.
# --------------------------------------------------------------------------- #
def test_multi_day_gap_blocked(tmp_path):
    tr = _tr(tmp_path)
    _rec(tr, datetime(2026, 1, 9, 20, 0, tzinfo=UTC))     # Fri Prague 21:00 day 01-09
    rec = _rec(tr, datetime(2026, 1, 11, 23, 5, tzinfo=UTC), bal=50000.0, eq=50000.0)  # Mon Prague 00:05
    assert rec.get("anchor_unavailable") is True
    assert rec.get("anchor_reason") == DailyAnchorTracker.R_MISSED_ROLLOVER


# --------------------------------------------------------------------------- #
# §22.9 / §17 — restart with a valid persisted anchor reuses it (never recaptures).
# --------------------------------------------------------------------------- #
def test_midday_restart_reuses_persisted_anchor(tmp_path):
    tr = _tr(tmp_path)
    _prime_then_roll(tr, roll_bal=100000.0, roll_eq=100000.0)   # capture day 01-07
    tr2 = _tr(tmp_path)                                   # "restart" (reloads file)
    rec = _rec(tr2, W_MIDDAY, bal=77777.0, eq=88888.0)    # materially different mid-day
    assert rec["day_start_balance"] == 100000.0          # reused, not recaptured
    assert rec["day_start_equity"] == 100000.0


# --------------------------------------------------------------------------- #
# §22.10 — legacy anchor (no day_start_equity) stays fail-closed & is not rewritten.
# --------------------------------------------------------------------------- #
def _write_legacy_anchor(tmp_path, tday="2026-01-07", balance=100000.0):
    rec = {"trading_day": tday, "timezone": "Europe/Prague",
           "day_start_balance": balance}                 # NO day_start_equity (legacy)
    rec["integrity_digest"] = serialize.compute_integrity_digest(rec)
    (tmp_path / "a.json").write_text(
        serialize.canonical_json({"records": {tday: rec}}), encoding="utf-8")


def test_legacy_anchor_rejected_and_not_rewritten(tmp_path):
    _write_legacy_anchor(tmp_path)
    before = (tmp_path / "a.json").read_bytes()
    rec = _rec(_tr(tmp_path), W_MIDDAY, bal=55555.0, eq=66666.0)
    assert rec.get("day_start_equity") is None            # incomplete
    assert rec.get("anchor_reason") == DailyAnchorTracker.R_LEGACY
    # an incomplete anchor is not authorizable -> ftmo_levels fails closed
    assert ftmo_levels({"day_start_balance": rec["day_start_balance"],
                        "day_start_equity": rec.get("day_start_equity")},
                       PROFILE, FtmoConfig()) is None
    # legacy record survives diagnostics unchanged (not silently rewritten/migrated)
    assert (tmp_path / "a.json").read_bytes() == before


# --------------------------------------------------------------------------- #
# §22.11 — corrupt/tampered anchor digest -> flagged conflict (gate fails closed).
# --------------------------------------------------------------------------- #
def test_corrupt_anchor_flags_conflict(tmp_path):
    rec = {"trading_day": "2026-01-07", "timezone": "Europe/Prague",
           "day_start_balance": 100000.0, "day_start_equity": 100000.0,
           "integrity_digest": "deadbeef"}               # wrong digest
    (tmp_path / "a.json").write_text(
        serialize.canonical_json({"records": {"2026-01-07": rec}}), encoding="utf-8")
    got = _rec(_tr(tmp_path), W_MIDDAY)
    assert got["daily_anchor_conflict"] is True


# --------------------------------------------------------------------------- #
# §22.12 — two concurrent tracker instances: the FIRST valid anchor is preserved.
# --------------------------------------------------------------------------- #
def test_concurrent_writers_first_anchor_preserved(tmp_path):
    a, b = _tr(tmp_path), _tr(tmp_path)                   # same path, two "processes"
    _rec(a, W_PREV); _rec(b, W_PREV)                      # both observe the prior day
    ra = _rec(a, W_ROLL, bal=50000.0, eq=50000.0)         # A captures first
    rb = _rec(b, W_ROLL, bal=48000.0, eq=48000.0)         # B attempts later, same day
    assert ra["day_start_balance"] == 50000.0
    assert rb["day_start_balance"] == 50000.0             # B reuses A's anchor, not 48000
    persisted = serialize.loads((tmp_path / "a.json").read_text())[1]["records"]["2026-01-07"]
    assert persisted["day_start_balance"] == 50000.0      # 48000 NEVER replaces 50000


# --------------------------------------------------------------------------- #
# §22.13 — in-window LOSS scenario cannot create a lower FTMO floor.
# The exact fail-open case from the audit: true rollover 50000/50000; a fresh
# process at 00:45 sees 48000/48000. It must NOT anchor 48000.
# --------------------------------------------------------------------------- #
def test_in_window_loss_cannot_lower_ftmo_floor(tmp_path):
    fresh = _tr(tmp_path, "fresh.json")
    rec = _rec(fresh, W_0045, bal=48000.0, eq=48000.0)    # fresh cold start, no prior obs
    assert rec.get("anchor_unavailable") is True          # NO anchor
    # therefore NO FTMO authorization can be derived from that post-rollover state:
    assert ftmo_levels({"day_start_balance": rec.get("day_start_balance"),
                        "day_start_equity": rec.get("day_start_equity")},
                       PROFILE, FtmoConfig()) is None
    # a correctly OBSERVED rollover would instead anchor the true 50000 floor:
    good = _tr(tmp_path, "good.json")
    grec = _prime_then_roll(good, roll_bal=50000.0, roll_eq=50000.0)
    lv = ftmo_levels({"day_start_balance": grec["day_start_balance"],
                      "day_start_equity": grec["day_start_equity"]}, PROFILE, FtmoConfig())
    assert lv["day_start_reference"] == 50000.0
    assert lv["official_daily_level"] == 50000.0 - 0.05 * 100000.0   # 45000, the TRUE floor


# --------------------------------------------------------------------------- #
# §22.14 — overnight equity-winner scenario preserves the correct reference.
# --------------------------------------------------------------------------- #
def test_overnight_equity_winner_reference_preserved(tmp_path):
    good = _tr(tmp_path)
    rec = _prime_then_roll(good, roll_bal=100000.0, roll_eq=106000.0)   # floating winner held
    lv = ftmo_levels({"day_start_balance": rec["day_start_balance"],
                      "day_start_equity": rec["day_start_equity"]}, PROFILE, FtmoConfig())
    assert lv["day_start_reference"] == 106000.0
    assert lv["official_daily_level"] == 106000.0 - 5000.0             # 101000
    # a fresh cold start at 00:45 with a lower 49000 equity cannot approximate this:
    fresh = _tr(tmp_path, "fresh.json")
    frec = _rec(fresh, W_0045, bal=100000.0, eq=49000.0)
    assert frec.get("anchor_unavailable") is True


# --------------------------------------------------------------------------- #
# §22.15 — Prague DST: a summer continuous rollover captures correctly.
# --------------------------------------------------------------------------- #
def test_summer_dst_continuous_rollover_captures(tmp_path):
    tr = _tr(tmp_path)
    rec = _prime_then_roll(tr, roll=S_ROLL, prev=S_PREV, roll_bal=100000.0, roll_eq=100000.0)
    assert rec["trading_day"] == "2026-07-07"
    assert rec["day_start_balance"] == 100000.0 and rec["anchor_schema_version"] == 2


def test_summer_dst_cold_start_blocked(tmp_path):
    rec = _rec(_tr(tmp_path), datetime(2026, 7, 6, 22, 45, tzinfo=UTC), bal=48000.0, eq=48000.0)
    assert rec.get("anchor_unavailable") is True          # Prague 00:45 summer, no prior obs


# --------------------------------------------------------------------------- #
# §22.16 / §18 — weekend behavior: a continuous Sunday->Monday reopen rollover
# captures; a Friday->Monday market-closure gap does NOT fabricate an anchor.
# --------------------------------------------------------------------------- #
def test_weekend_sunday_to_monday_continuous_captures(tmp_path):
    tr = _tr(tmp_path)
    # market reopens Sun night; Prague Monday 2026-01-12 starts 2026-01-11 23:00 UTC.
    prev = datetime(2026, 1, 11, 22, 55, tzinfo=UTC)      # Prague Sun 23:55 day 01-11
    roll = datetime(2026, 1, 11, 23, 5, tzinfo=UTC)       # Prague Mon 00:05 day 01-12 (10m)
    _rec(tr, prev)
    rec = _rec(tr, roll, bal=100000.0, eq=100000.0)
    assert rec["trading_day"] == "2026-01-12"
    assert rec["day_start_balance"] == 100000.0


def test_weekend_friday_to_monday_closure_gap_blocked(tmp_path):
    tr = _tr(tmp_path)
    _rec(tr, datetime(2026, 1, 9, 21, 0, tzinfo=UTC))     # Fri Prague 22:00 day 01-09
    rec = _rec(tr, datetime(2026, 1, 11, 23, 5, tzinfo=UTC), bal=50000.0, eq=50000.0)  # Mon 00:05
    assert rec.get("anchor_unavailable") is True          # long closure -> no fabrication
    assert rec.get("anchor_reason") == DailyAnchorTracker.R_MISSED_ROLLOVER


# --------------------------------------------------------------------------- #
# §22.17 — a persisted valid anchor is immutable even if current state differs.
# --------------------------------------------------------------------------- #
def test_persisted_anchor_immutable_across_restart(tmp_path):
    tr = _tr(tmp_path)
    _prime_then_roll(tr, roll_bal=50000.0, roll_eq=50000.0)
    # a second, later "process" with a materially different account reuses the anchor
    tr2 = _tr(tmp_path)
    rec = _rec(tr2, W_MIDDAY, bal=30000.0, eq=31000.0)
    assert rec["day_start_balance"] == 50000.0
    assert rec["day_start_equity"] == 50000.0


# --------------------------------------------------------------------------- #
# §13 — an interrupted first-write (partial/temp) never becomes an authorizing
# anchor; the atomic claim only ever publishes a complete record.
# --------------------------------------------------------------------------- #
def test_partial_temp_never_authorizes(tmp_path):
    # simulate a crashed writer leaving a dot-prefixed temp beside the claim path.
    stray = tmp_path / (".a.json.2026-01-07.claim.tmp.9999")
    stray.write_text("{ partial", encoding="utf-8")
    tr = _tr(tmp_path)
    rec = _prime_then_roll(tr, roll_bal=50000.0, roll_eq=50000.0)  # a real observed rollover
    assert rec["day_start_balance"] == 50000.0            # capture succeeds cleanly
    # the stray temp is not a claim and did not authorize anything on its own
    assert (tmp_path / "a.json.2026-01-07.claim").exists()
