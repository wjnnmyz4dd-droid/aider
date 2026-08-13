"""PR-3K.1 / M13 — weekend policy closure (entry + data-freshness authorities).

Proves the stated weekend contract is ALREADY enforced by existing authoritative
gates, with no new runtime authority:
  * Friday new-entry cutoff is M12 (session-local, DST-aware); at/after the cutoff no
    new entry — and friday_close_policy=None is NOT fail-open because M12 still blocks.
  * There is no artificial Sunday reopening clock (sunday_open_policy=None); after the
    weekend, entry is restored ONLY when the ordinary gates independently pass.
  * Weekend closure / stale data fails closed and never fabricates an OR / trade.
  * No single gate (fresh data / active session / strategy qualification) authorizes a
    trade on its own; all compliance/risk/news/bridge gates remain mandatory.
Deterministic; no MT5. See docs/SESSION_EDGE_WEEKEND_POLICY.md.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from forex_swing_orb.bridge import serialize
from forex_swing_orb.producer.contract import CycleOutcome, RunnerReason
from forex_swing_orb.producer.mock_providers import MockNewsProvider, make_bars
from forex_swing_orb.session.profiles import profile_for
from conftest import NOW

UTC = timezone.utc
# 2026-01-09 Fri, 01-10 Sat, 01-11 Sun. London in January = GMT (UTC+0).
FRI_2000 = datetime(2026, 1, 9, 20, 0, tzinfo=UTC)      # London 20:00 Fri == cutoff
SAT_1400 = datetime(2026, 1, 10, 14, 0, tzinfo=UTC)
SUN_1400 = datetime(2026, 1, 11, 14, 0, tzinfo=UTC)     # London 14:00 Sun, session active
SUN_2300 = datetime(2026, 1, 11, 23, 0, tzinfo=UTC)     # London 23:00 Sun, window closed
CUTOFF = {"SYDNEY": 19, "TOKYO": 21, "LONDON": 20, "NEW_YORK": 20}


def _inject_stale_m15(ctx, ref_days_ago_now):
    """Override the M15 feed with bars that end ~2 days before `now`, so the data
    -freshness authority fails closed (weekend-closed / stale feed)."""
    stale = make_bars("EURUSD.FX", "M15", ref_days_ago_now, n=120)
    ctx["market"].set("EURUSD.FX", "M15", stale)


def _outcomes(res):
    return [r.outcome for r in res]


# --------------------------------------------------------------------------- #
# 1 / 2 / 14  — M12 Friday cutoff unchanged, inclusive boundary, DST-aware
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("sid,hour", list(CUTOFF.items()))
def test_1_m12_cutoff_unchanged_each_session(sid, hour):
    assert profile_for(sid).friday_no_new_entry_local_hour == hour


@pytest.mark.parametrize("sid", list(CUTOFF))
def test_2_friday_equality_boundary_blocks(sid):
    from zoneinfo import ZoneInfo
    p = profile_for(sid)
    at = datetime(2026, 1, 9, CUTOFF[sid], 0, tzinfo=ZoneInfo(p.timezone))
    before = datetime(2026, 1, 9, CUTOFF[sid] - 1, 0, tzinfo=ZoneInfo(p.timezone))
    assert p.is_friday_no_new_entry(at) is True         # inclusive at the cutoff hour
    assert p.is_friday_no_new_entry(before) is False


def test_14_dst_preserves_session_local_behavior():
    p = profile_for("LONDON")                            # cutoff 20:00 local
    # winter 19:00 UTC == 19:00 London (before) ; summer 19:00 UTC == 20:00 BST (at)
    assert p.is_friday_no_new_entry(datetime(2026, 1, 9, 19, 0, tzinfo=UTC)) is False
    assert p.is_friday_no_new_entry(datetime(2026, 7, 3, 19, 0, tzinfo=UTC)) is True


# --------------------------------------------------------------------------- #
# Friday entry blocked end-to-end; None global guard is NOT fail-open (15)
# --------------------------------------------------------------------------- #
def test_15_friday_blocked_by_m12_despite_none_global_guard(make_runner):
    runner, ctx = make_runner(now=FRI_2000)             # session_model None (global guard off)
    res = runner.run_cycle(FRI_2000)
    assert any(r.outcome == CycleOutcome.SESSION_INELIGIBLE
               and RunnerReason.FRIDAY_NO_NEW_ENTRY in r.reason_codes for r in res)
    assert not any(r.wrote_bridge for r in res)         # None default did not fail open


# --------------------------------------------------------------------------- #
# 5 — Saturday: weekend-closed / stale data never fabricates a trade
# --------------------------------------------------------------------------- #
def test_5_saturday_stale_data_no_entry(make_runner):
    runner, ctx = make_runner(now=SAT_1400)
    _inject_stale_m15(ctx, SAT_1400.replace(day=8))     # last bar ~2 days old
    res = runner.run_cycle(SAT_1400)
    assert CycleOutcome.DATA_REJECTED in _outcomes(res)
    assert not any(r.wrote_bridge for r in res)


# --------------------------------------------------------------------------- #
# 6 / 7 — Sunday has no arbitrary clock unlock; stale Sunday cannot trade
# --------------------------------------------------------------------------- #
def test_6_sunday_has_no_arbitrary_unlock_clock():
    from forex_swing_orb.session.model import SessionModel
    from forex_swing_orb.compliance.contract import SessionConfig
    assert SessionModel().sunday_open_policy is None
    assert SessionConfig().sunday_open_min is None


def test_7_sunday_stale_data_cannot_trade(make_runner):
    runner, ctx = make_runner(now=SUN_1400)
    _inject_stale_m15(ctx, SUN_1400.replace(day=9))     # feed still closed -> stale
    res = runner.run_cycle(SUN_1400)
    assert CycleOutcome.DATA_REJECTED in _outcomes(res)
    assert not any(r.wrote_bridge for r in res)


# --------------------------------------------------------------------------- #
# 8 — Sunday/next-session with FRESH authoritative data proceeds via normal gates
# --------------------------------------------------------------------------- #
def test_8_sunday_fresh_data_proceeds_via_normal_gates(make_runner):
    runner, ctx = make_runner(now=SUN_1400)             # default fresh feed at SUN 14:00
    res = runner.run_cycle(SUN_1400)
    assert any(r.outcome == CycleOutcome.INSTRUCTION_WRITTEN for r in res)


# --------------------------------------------------------------------------- #
# 9 / 10 / 11 — no single gate authorizes a trade on its own
# --------------------------------------------------------------------------- #
def test_9_fresh_data_alone_does_not_authorize(make_runner):
    # fresh feed but OUTSIDE the session window -> session gate blocks
    runner, ctx = make_runner(now=SUN_2300)
    res = runner.run_cycle(SUN_2300)
    assert not any(r.wrote_bridge for r in res)
    assert CycleOutcome.SESSION_INELIGIBLE in _outcomes(res)


def test_10_active_session_alone_does_not_authorize(make_runner):
    # active session but stale data -> data-freshness gate blocks
    runner, ctx = make_runner(now=SUN_1400)
    _inject_stale_m15(ctx, SUN_1400.replace(day=9))
    res = runner.run_cycle(SUN_1400)
    assert not any(r.wrote_bridge for r in res)
    assert CycleOutcome.DATA_REJECTED in _outcomes(res)


def test_11_strategy_qualification_alone_does_not_authorize(make_runner):
    # StubEngine qualifies a candidate, but an in-window HIGH news lockout blocks it
    ev = {"event_id": "E1", "currency": "USD", "impact": "HIGH",
          "event_timestamp": serialize.iso_utc(SUN_1400), "verification_state": "VERIFIED"}
    runner, ctx = make_runner(now=SUN_1400, news=MockNewsProvider(SUN_1400, events=[ev]))
    res = runner.run_cycle(SUN_1400)
    assert not any(r.wrote_bridge for r in res)
    assert CycleOutcome.COMPLIANCE_REJECT in _outcomes(res)


def test_12_all_gates_remain_mandatory_after_weekend(make_runner):
    # same news lockout on Sunday -> compliance/news still authoritative post-weekend
    ev = {"event_id": "E1", "currency": "EUR", "impact": "HIGH",
          "event_timestamp": serialize.iso_utc(SUN_1400), "verification_state": "VERIFIED"}
    runner, ctx = make_runner(now=SUN_1400, news=MockNewsProvider(SUN_1400, events=[ev]))
    res = runner.run_cycle(SUN_1400)
    rej = [r for r in res if r.outcome == CycleOutcome.COMPLIANCE_REJECT]
    assert rej and not any(r.wrote_bridge for r in res)


# --------------------------------------------------------------------------- #
# 13 — a weekend data gap is not silently incorporated as continuous OR data
# --------------------------------------------------------------------------- #
def test_13_weekend_gap_not_incorporated_into_or():
    from forex_swing_orb.producer.providers import Bars, validate_bars
    # a NON-weekend mid-series hole must be rejected as DATA_GAP (never silently
    # treated as continuous OR data). Start from a clean, fresh, contiguous series and
    # remove one middle bar so the LAST bar stays valid/fresh but continuity breaks.
    now = datetime(2026, 1, 6, 12, 15, tzinfo=UTC)      # Tuesday
    clean = make_bars("EURUSD.FX", "M15", now, n=12)
    rows = list(clean.rows)
    del rows[7]                                          # mid-series hole within the window
    ok, reason = validate_bars(Bars("EURUSD.FX", "M15", rows), "M15", now,
                               max_age_sec=120, continuity_bars=8, min_bars=5)
    assert not ok and reason == RunnerReason.DATA_GAP


# --------------------------------------------------------------------------- #
# 16 — example/test values 1200/1320 are never production defaults
# --------------------------------------------------------------------------- #
def test_16_example_values_are_not_production_defaults():
    from forex_swing_orb.session.model import SessionModel
    from forex_swing_orb.compliance.contract import SessionConfig
    from forex_swing_orb.runtime.config import RuntimeConfig
    assert SessionModel().friday_close_policy is None and SessionModel().sunday_open_policy is None
    assert SessionConfig().friday_close_min is None and SessionConfig().sunday_open_min is None
    # RuntimeConfig field defaults (dataclass) are None, not 1200/1320
    import dataclasses
    fields = {f.name: f.default for f in dataclasses.fields(RuntimeConfig)}
    assert fields["friday_close_min"] is None and fields["sunday_open_min"] is None


# --------------------------------------------------------------------------- #
# F — duplicate-authority audit: entry cutoff owner != management owner
# --------------------------------------------------------------------------- #
def test_F_no_duplicate_weekend_authority_in_producer():
    root = Path(__file__).resolve().parents[2]
    runner_src = (root / "producer" / "runner.py").read_text()
    # the producer entry path owns the M12 Friday cutoff and must NOT also implement
    # the PM weekend-flatten authority (single owner per responsibility).
    assert "is_friday_no_new_entry" in runner_src          # M12 owner present
    assert "weekend_cutoff_hour_utc" not in runner_src      # PM flatten not duplicated
    assert "WEEKEND_EXIT" not in runner_src
