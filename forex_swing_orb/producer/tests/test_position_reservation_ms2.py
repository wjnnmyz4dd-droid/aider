"""PR-4A.1 MS-2 — same-cycle AND cross-cycle account-capacity reservation.

Outstanding entry intents (instructions written but not yet filled/terminal) consume
max_open_positions / one-position-per-symbol capacity BEFORE MT5 reports a fill, so
multi-session/multi-symbol fan-out cannot exceed the account position budget. Broker
truth stays immutable; reservation is derived from bridge pending/claimed files.
Deterministic; no MT5.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from forex_swing_orb.bridge import serialize
from forex_swing_orb.bridge.paths import BridgePaths
from forex_swing_orb.compliance import ComplianceConfig, FtmoConfig, FtmoProfile
from forex_swing_orb.producer import ProducerRunner, RunnerConfig, RunnerMode
from forex_swing_orb.producer.contract import CycleOutcome
from forex_swing_orb.producer.mock_providers import (MockAccountProvider,
                                                     MockBrokerHealthProvider,
                                                     MockMarketDataProvider,
                                                     MockNewsProvider, StubEngine)
from forex_swing_orb.session.profiles import profiles_for

BOTH = datetime(2026, 1, 7, 14, 0, 0, tzinfo=timezone.utc)   # London+NY both active
FOUR = ("EURUSD.FX", "GBPUSD.FX", "USDJPY.FX", "AUDUSD.FX")


def _compliance(max_open=5, one_per_symbol=True):
    return ComplianceConfig(
        profile=FtmoProfile(
            initial_balance=100000.0, account_currency="USD",
            rule_source="ftmo.com/en/trading-objectives (2-Step)",
            rule_source_verified_at="2026-08-05", profile_verified=True),
        ftmo=FtmoConfig(max_open_positions=max_open, one_position_per_symbol=one_per_symbol))


def _build(tmp_path, enabled=("LONDON",), symbols=FOUR, now=BOTH, max_open=5,
           open_count=0, open_symbols=(), one_per_symbol=True, paths=None,
           state_dir=None):
    paths = paths or BridgePaths(tmp_path / "bridge").ensure()
    state_dir = state_dir or tmp_path
    Path(state_dir).mkdir(parents=True, exist_ok=True)
    profiles = profiles_for(enabled)
    cfg = RunnerConfig(symbols=symbols, mode=RunnerMode.DEMO, ftmo_profile_verified=True,
                       compliance=_compliance(max_open, one_per_symbol),
                       session_profiles=profiles)
    account = MockAccountProvider(now, open_position_count=open_count,
                                  open_symbols=tuple(open_symbols))
    by_session = {p.session_id: StubEngine(emit=True, session_id=p.session_id)
                  for p in profiles}
    runner = ProducerRunner(
        cfg, bridge_paths=paths, market=MockMarketDataProvider(symbols, now),
        account=account, news=MockNewsProvider(now), broker=MockBrokerHealthProvider(),
        strategy_by_session=by_session,
        state_path=str(state_dir / "state.json"),
        runner_audit_path=str(state_dir / "ra.jsonl"),
        compliance_audit_path=str(state_dir / "ca.jsonl"))
    return runner, paths


def _written(res):
    return [r for r in res if r.outcome == CycleOutcome.INSTRUCTION_WRITTEN]


def _pending(paths):
    return sorted(p.name for p in paths.pending.glob("*.json"))


# --------------------------------------------------------------------------- #
# same-cycle count reservation (§24.1-3, §10-12)
# --------------------------------------------------------------------------- #
def test_one_slot_four_candidates_one_write(tmp_path):
    # max 3, broker already holds 2 -> exactly ONE new instruction may take the slot
    runner, paths = _build(tmp_path, max_open=3, open_count=2)
    res = runner.run_cycle(BOTH)
    assert len(_written(res)) == 1
    assert len(_pending(paths)) == 1


def test_two_slots_four_candidates_two_writes(tmp_path):
    runner, paths = _build(tmp_path, max_open=3, open_count=1)
    res = runner.run_cycle(BOTH)
    assert len(_written(res)) == 2
    assert len(_pending(paths)) == 2


def test_zero_slots_no_writes(tmp_path):
    runner, paths = _build(tmp_path, max_open=3, open_count=3)
    res = runner.run_cycle(BOTH)
    assert len(_written(res)) == 0
    assert _pending(paths) == []


def test_all_sessions_cannot_multiply_capacity(tmp_path):
    # ALL four sessions enabled + four symbols, but only ONE slot free -> ONE write
    runner, paths = _build(tmp_path, enabled=("SYDNEY", "TOKYO", "LONDON", "NEW_YORK"),
                           max_open=3, open_count=2,
                           now=datetime(2026, 1, 7, 15, 0, tzinfo=timezone.utc))
    res = runner.run_cycle(datetime(2026, 1, 7, 15, 0, tzinfo=timezone.utc))
    assert len(_written(res)) == 1                       # not 4; session count never adds budget
    assert len(_pending(paths)) == 1


# --------------------------------------------------------------------------- #
# same-symbol + no-reservation-on-non-write (§24.4-7)
# --------------------------------------------------------------------------- #
def test_same_symbol_across_sessions_one_write(tmp_path):
    runner, paths = _build(tmp_path, enabled=("LONDON", "NEW_YORK"),
                           symbols=("EURUSD.FX",), max_open=5)
    res = runner.run_cycle(BOTH)
    assert len(_written(res)) == 1
    assert len(_pending(paths)) == 1


def test_rejected_candidate_does_not_reserve(tmp_path):
    # broker at max -> every candidate rejected -> nothing reserved, nothing written
    runner, paths = _build(tmp_path, max_open=2, open_count=2)
    res = runner.run_cycle(BOTH)
    assert _pending(paths) == []
    assert all(r.outcome != CycleOutcome.INSTRUCTION_WRITTEN for r in res)


def test_duplicate_does_not_double_reserve(tmp_path):
    runner, paths = _build(tmp_path, symbols=("EURUSD.FX",), max_open=5)
    runner.run_cycle(BOTH)
    assert len(_pending(paths)) == 1
    res2 = runner.run_cycle(BOTH)                         # same bar -> NO_NEW_BAR/dup
    assert len(_pending(paths)) == 1                      # not doubled


# --------------------------------------------------------------------------- #
# cross-cycle pending intent + restart (§17, §18, §20, §24.8-9)
# --------------------------------------------------------------------------- #
def test_unresolved_pending_counts_next_cycle(tmp_path):
    # max 1: cycle 1 writes EURUSD (unfilled). Next cycle (new bar) must NOT write
    # another symbol while the first entry intent is still pending.
    runner, paths = _build(tmp_path, symbols=("EURUSD.FX", "GBPUSD.FX"), max_open=1)
    r1 = runner.run_cycle(BOTH)
    assert len(_written(r1)) == 1 and len(_pending(paths)) == 1
    later = datetime(2026, 1, 7, 14, 15, 0, tzinfo=timezone.utc)   # next M15 bar
    r2 = runner.run_cycle(later)
    assert len(_written(r2)) == 0                         # pending intent consumes the only slot
    assert len(_pending(paths)) == 1


def test_restart_with_unresolved_pending_remains_reserved(tmp_path):
    paths = BridgePaths(tmp_path / "bridge").ensure()
    runner, _ = _build(tmp_path, symbols=("EURUSD.FX", "GBPUSD.FX"), max_open=1,
                       paths=paths, state_dir=tmp_path / "s1")
    runner.run_cycle(BOTH)
    assert len(_pending(paths)) == 1
    # restart: brand-new runner, SAME bridge (pending persists), fresh state
    later = datetime(2026, 1, 7, 14, 15, 0, tzinfo=timezone.utc)
    runner2, _ = _build(tmp_path, symbols=("EURUSD.FX", "GBPUSD.FX"), max_open=1,
                        now=later, paths=paths, state_dir=tmp_path / "s2")
    r2 = runner2.run_cycle(later)
    assert len(_written(r2)) == 0                         # pending survives restart -> reserved
    assert len(_pending(paths)) == 1


# --------------------------------------------------------------------------- #
# terminal results release capacity; broker fill does not double count (§19, §24.10-12)
# --------------------------------------------------------------------------- #
def _archive_reject(paths, sid):
    src = paths.pending / f"{sid}.json"
    (paths.archive_rejected / f"{sid}.json").write_text(src.read_text(), encoding="utf-8")
    src.unlink()


def test_terminal_rejection_releases_capacity(tmp_path):
    runner, paths = _build(tmp_path, symbols=("EURUSD.FX", "GBPUSD.FX"), max_open=1)
    runner.run_cycle(BOTH)
    sid = _pending(paths)[0][:16]
    _archive_reject(paths, sid)                           # simulate EXECUTION_FAILED/EXPIRED
    later = datetime(2026, 1, 7, 14, 15, 0, tzinfo=timezone.utc)
    runner.account.set(as_of=serialize.iso_utc(later))
    r2 = runner.run_cycle(later)
    assert len(_written(r2)) == 1                         # capacity released -> a new entry allowed


def test_broker_fill_not_double_counted(tmp_path):
    # a pending intent that FILLS leaves pending/ (archived) AND appears in broker
    # open_count. The effective count must stay 1 (broker 1 + pending 0), NOT 2.
    runner, paths = _build(tmp_path, symbols=("EURUSD.FX",), max_open=1)
    runner.run_cycle(BOTH)                                # writes EURUSD -> pending 1
    base = {"open_position_count": 0, "open_symbols": ()}
    obs1 = runner._observe_bridge(BOTH)
    assert runner._effective_account_state(base, obs1)["open_position_count"] == 1  # 0 + pending
    # fill: EURUSD leaves pending (archived) and becomes a broker position
    sid = _pending(paths)[0][:16]
    (paths.archive_accepted / f"{sid}.json").write_text(
        (paths.pending / f"{sid}.json").read_text(), encoding="utf-8")
    (paths.pending / f"{sid}.json").unlink()
    filled = {"open_position_count": 1, "open_symbols": ("EURUSD.FX",)}
    eff = runner._effective_account_state(filled, runner._observe_bridge(BOTH))
    assert eff["open_position_count"] == 1               # broker 1 + pending 0 (NOT double)
    assert set(eff["open_symbols"]) == {"EURUSD.FX"}


# --------------------------------------------------------------------------- #
# determinism (§16)
# --------------------------------------------------------------------------- #
def test_capacity_award_order_deterministic(tmp_path):
    r1, p1 = _build(tmp_path / "a", enabled=("LONDON", "NEW_YORK"), max_open=3, open_count=2)
    r2, p2 = _build(tmp_path / "b", enabled=("NEW_YORK", "LONDON"), max_open=3, open_count=2)
    r1.run_cycle(BOTH)
    r2.run_cycle(BOTH)
    assert _pending(p1) == _pending(p2)                   # same winner regardless of config order
