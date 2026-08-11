"""PR-2 closed-bar / time contract at the validation boundary (validate_bars).

Confirms the frozen fail-closed semantics hold at every timeframe boundary and
that timestamps are treated as true-UTC instants (no reinterpretation). No MT5."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from forex_swing_orb.producer.providers import Bars, validate_bars           # noqa: E402
from forex_swing_orb.producer.contract import RunnerReason                    # noqa: E402

STEP = timedelta(minutes=15)
ANCHOR = datetime(2025, 1, 6, 12, 0, 0, tzinfo=timezone.utc)   # M15-aligned Monday


def _rows(n, last_open=ANCHOR, step=STEP):
    start = last_open - step * (n - 1)
    return [{"open_time": start + step * i, "open": 1.1, "high": 1.1005,
             "low": 1.0995, "close": 1.1002} for i in range(n)]


def _bars(rows):
    return Bars("EURUSD.FX", "M15", rows)


def _validate(rows, now, max_age_sec=120, continuity_bars=10, min_bars=5):
    return validate_bars(_bars(rows), "M15", now, max_age_sec, continuity_bars, min_bars)


def test_exact_close_boundary_ok():
    rows = _rows(10)
    now = rows[-1]["open_time"] + STEP            # last_close == now
    assert _validate(rows, now) == (True, RunnerReason.OK)


def test_one_second_before_close_is_unclosed():
    rows = _rows(10)
    now = rows[-1]["open_time"] + STEP - timedelta(seconds=1)
    assert _validate(rows, now) == (False, RunnerReason.DATA_UNCLOSED_BAR)


def test_just_after_close_ok():
    rows = _rows(10)
    now = rows[-1]["open_time"] + STEP + timedelta(seconds=30)
    assert _validate(rows, now) == (True, RunnerReason.OK)


def test_future_open_rejected():
    rows = _rows(10)
    now = rows[-1]["open_time"] - timedelta(seconds=1)   # last_open > now
    ok, reason = _validate(rows, now)
    assert ok is False and reason in (RunnerReason.DATA_UNCLOSED_BAR,
                                      RunnerReason.DATA_FUTURE_BAR)


def test_stale_rejected():
    rows = _rows(10)
    now = rows[-1]["open_time"] + STEP + timedelta(hours=6)   # far past close+max_age
    assert _validate(rows, now) == (False, RunnerReason.DATA_STALE)


def test_duplicate_timestamp_rejected():
    rows = _rows(10)
    rows[-1]["open_time"] = rows[-2]["open_time"]             # duplicate (non-increasing)
    now = rows[-1]["open_time"] + STEP
    assert _validate(rows, now) == (False, RunnerReason.DATA_GAP)


def test_non_monotonic_rejected():
    rows = _rows(10)
    rows[-1]["open_time"] = rows[-2]["open_time"] - STEP      # decreasing
    now = ANCHOR + STEP
    assert _validate(rows, now) == (False, RunnerReason.DATA_GAP)


def test_weekend_gap_allowed():
    # Friday 21:45 close -> Monday 00:00 open is a permitted weekend gap
    fri = datetime(2025, 1, 3, 21, 45, tzinfo=timezone.utc)   # Friday
    mon = datetime(2025, 1, 6, 0, 0, tzinfo=timezone.utc)     # Monday
    rows = ([{"open_time": fri - STEP * i, "open": 1.1, "high": 1.1005,
              "low": 1.0995, "close": 1.1002} for i in range(5)][::-1]
            + [{"open_time": mon + STEP * i, "open": 1.1, "high": 1.1005,
                "low": 1.0995, "close": 1.1002} for i in range(5)])
    now = rows[-1]["open_time"] + STEP
    assert _validate(rows, now, max_age_sec=120, continuity_bars=10) == (True, RunnerReason.OK)


def test_insufficient_history_rejected():
    rows = _rows(3)
    now = rows[-1]["open_time"] + STEP
    assert _validate(rows, now, min_bars=5) == (False, RunnerReason.DATA_INSUFFICIENT)
