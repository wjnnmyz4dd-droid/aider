"""PR-2 B2: time-base field diagnostic (pure logic). Proves the diagnostic
correctly reports whether MT5 rate timestamps behave as true UTC, applies NO
guessed offset, and gives the operator an evidence path to field-verify on
Windows. No MT5 required."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from forex_swing_orb.validation import mt5_timebase_probe as TB              # noqa: E402

M15 = TB.M15_SECONDS


def test_expected_last_closed_open():
    # now at 12:07:00 -> forming M15 opened 12:00 -> last closed opened 11:45
    now = 1_700_000_000
    now = (now // M15) * M15 + 7 * 60           # 7 min into a bar
    exp = TB.expected_last_closed_open_epoch(now)
    assert exp == (now // M15) * M15 - M15


def test_classify_true_utc():
    now = (1_700_000_000 // M15) * M15 + 300     # 5 min into forming bar
    reported = TB.expected_last_closed_open_epoch(now)
    r = TB.classify_timebase(reported, now)
    assert r["class"] == TB.TB_SOURCE_APPEARS_UTC
    assert r["offset_sec"] == 0 and r["production_assumption_holds"] is True


def test_classify_within_tolerance_still_utc():
    now = (1_700_000_000 // M15) * M15 + 300
    reported = TB.expected_last_closed_open_epoch(now) + 60     # 60s < 90s tolerance
    assert TB.classify_timebase(reported, now)["class"] == TB.TB_SOURCE_APPEARS_UTC


def test_classify_broker_offset_detected():
    now = (1_700_000_000 // M15) * M15 + 300
    reported = TB.expected_last_closed_open_epoch(now) + 2 * 3600   # +2h server skew
    r = TB.classify_timebase(reported, now)
    assert r["class"] == TB.TB_APPARENT_BROKER_OFFSET
    assert r["offset_hours"] == 2.0 and r["production_assumption_holds"] is False


def test_classify_unknown_on_missing_data():
    assert TB.classify_timebase(None, 1_700_000_000)["class"] == TB.TB_UNKNOWN
    assert TB.classify_timebase(1_700_000_000, None)["class"] == TB.TB_UNKNOWN


def test_server_utc_skew():
    now = 1_700_000_000
    assert TB.server_utc_skew(now, now)["within_tolerance"] is True
    off = TB.server_utc_skew(now + 3 * 3600, now)
    assert off["skew_hours"] == 3.0 and off["within_tolerance"] is False


def test_diagnostic_applies_no_offset_to_production():
    """The diagnostic is evidence-only: it never returns an instruction to shift
    timestamps, and the module never mutates production bar arithmetic."""
    r = TB.classify_timebase(TB.expected_last_closed_open_epoch(
        (1_700_000_000 // M15) * M15 + 300) + 7200,
        (1_700_000_000 // M15) * M15 + 300)
    assert "apply_offset" not in r and "correction" not in r
    src = (Path(__file__).resolve().parents[1] / "mt5_timebase_probe.py").read_text()
    # no guessed broker constants, no production-provider mutation
    for banned in ("UTC+2", "UTC+3", "+7200", "+10800", "Mt5MarketDataProvider"):
        assert banned not in src
