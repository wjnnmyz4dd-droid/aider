"""PR-3A.1: DailyAnchorTracker startup semantics — fail-closed mid-day cold start,
continuity across the Prague rollover, restart reuse, and legacy-anchor rejection.
Exercises the ACTUAL tracker (not just ftmo_levels). Deterministic; no MT5."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from forex_swing_orb.bridge import serialize                                 # noqa: E402
from forex_swing_orb.compliance.contract import FtmoConfig, ftmo_levels      # noqa: E402
from forex_swing_orb.live.providers import DailyAnchorTracker                 # noqa: E402

UTC = timezone.utc
# winter (Prague = UTC+1): trading day 2026-01-07
W_ROLL = datetime(2026, 1, 6, 23, 10, tzinfo=UTC)        # Prague 00:10 (within window)
W_MIDDAY = datetime(2026, 1, 7, 10, 0, tzinfo=UTC)       # Prague 11:00 (after window)
W_NEXT_MIDDAY = datetime(2026, 1, 8, 10, 0, tzinfo=UTC)  # Prague 11:00 next trading day
# summer (Prague = UTC+2): trading day 2026-07-07
S_ROLL = datetime(2026, 7, 6, 22, 10, tzinfo=UTC)        # Prague 00:10 (within window)
S_MIDDAY = datetime(2026, 7, 7, 10, 0, tzinfo=UTC)       # Prague 12:00 (after window)

PROFILE = SimpleNamespace(initial_balance=100000.0, daily_loss_pct=0.05,
                          maximum_loss_pct=0.10)


def _tr(tmp_path):
    return DailyAnchorTracker(str(tmp_path / "a.json"))


def _rec(tr, now, bal=100000.0, eq=100000.0):
    return tr.record(now, bal, equity=eq, initial_balance=100000.0, daily_loss_pct=0.05)


# --------------------------------------------------------------------------- #
# A — mid-day cold start without a valid anchor must NOT create an authorizing one
# --------------------------------------------------------------------------- #
def test_midday_cold_start_no_anchor_fails_closed(tmp_path):
    rec = _rec(_tr(tmp_path), W_MIDDAY)
    assert rec.get("anchor_unavailable") is True
    assert "day_start_balance" not in rec
    assert not (tmp_path / "a.json").exists()             # nothing persisted


# --------------------------------------------------------------------------- #
# B — continuous run crossing the rollover captures a complete balance+equity anchor
# --------------------------------------------------------------------------- #
def test_continuous_rollover_captures_complete_anchor(tmp_path):
    tr = _tr(tmp_path)
    _rec(tr, W_ROLL)                                      # observe day N (within window)
    rec = _rec(tr, W_NEXT_MIDDAY, bal=99000.0, eq=99500.0)   # cross to N+1 (continuity)
    assert rec["day_start_balance"] == 99000.0
    assert rec["day_start_equity"] == 99500.0
    assert rec["anchor_schema_version"] == 2


# --------------------------------------------------------------------------- #
# C — mid-day restart with a valid persisted anchor reuses it (never recaptures)
# --------------------------------------------------------------------------- #
def test_midday_restart_reuses_persisted_anchor(tmp_path):
    _rec(_tr(tmp_path), W_ROLL, bal=100000.0, eq=100000.0)   # capture at rollover
    tr2 = _tr(tmp_path)                                   # "restart" (reloads file)
    rec = _rec(tr2, W_MIDDAY, bal=77777.0, eq=88888.0)    # different current values
    assert rec["day_start_balance"] == 100000.0          # reused, not recaptured
    assert rec["day_start_equity"] == 100000.0


# --------------------------------------------------------------------------- #
# D/E/F — legacy anchor (no day_start_equity)
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
    tr = _tr(tmp_path)
    rec = _rec(tr, W_MIDDAY, bal=55555.0, eq=66666.0)     # reused legacy, mid-day
    assert rec.get("day_start_equity") is None            # incomplete
    # D: incomplete anchor is not authorizable -> ftmo_levels fails closed
    acct = {"day_start_balance": rec["day_start_balance"],
            "day_start_equity": rec.get("day_start_equity")}
    assert ftmo_levels(acct, PROFILE, FtmoConfig()) is None
    # E: legacy record survives diagnostics unchanged (not silently rewritten)
    assert (tmp_path / "a.json").read_bytes() == before


def test_next_rollover_after_legacy_creates_complete_anchor(tmp_path):
    _write_legacy_anchor(tmp_path)
    tr = _tr(tmp_path)
    _rec(tr, W_MIDDAY)                                    # observe legacy day (sets _last_seen)
    rec = _rec(tr, W_NEXT_MIDDAY, bal=101000.0, eq=101500.0)  # next day via continuity
    assert rec["day_start_equity"] == 101500.0            # complete new-format anchor
    assert rec["anchor_schema_version"] == 2


# --------------------------------------------------------------------------- #
# G — same-day repeated observations cannot replace the anchor
# --------------------------------------------------------------------------- #
def test_same_day_repeat_is_idempotent(tmp_path):
    tr = _tr(tmp_path)
    _rec(tr, W_ROLL, bal=100000.0, eq=100000.0)
    after_first = (tmp_path / "a.json").read_bytes()
    rec = _rec(tr, W_ROLL, bal=55555.0, eq=44444.0)       # attempt to replace
    assert rec["day_start_balance"] == 100000.0
    assert (tmp_path / "a.json").read_bytes() == after_first   # unchanged


# --------------------------------------------------------------------------- #
# H — corrupt/tampered anchor digest -> flagged conflict (gate fails closed)
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
# Prague / DST — capture window is correct across DST
# --------------------------------------------------------------------------- #
def test_capture_window_winter_and_summer(tmp_path):
    tr = _tr(tmp_path)
    assert tr._within_capture_window(W_ROLL) is True      # Prague 00:10 winter
    assert tr._within_capture_window(W_MIDDAY) is False   # Prague 11:00 winter
    assert tr._within_capture_window(S_ROLL) is True      # Prague 00:10 summer (DST)
    assert tr._within_capture_window(S_MIDDAY) is False   # Prague 12:00 summer


def test_summer_dst_rollover_capture(tmp_path):
    rec = _rec(_tr(tmp_path), S_ROLL)                     # within summer window -> captures
    assert rec["day_start_balance"] == 100000.0 and rec["anchor_schema_version"] == 2


def test_naive_datetime_never_within_window(tmp_path):
    assert _tr(tmp_path)._within_capture_window(datetime(2026, 1, 7, 0, 10)) is False
