"""PR-4A — producer multi-session fan-out (integration; StubEngine per session).

Proves: independent per-session evaluation on shared bars, distinct session_id +
signal_id per session, config-order invariance, per-session eligibility windows,
and that one-position-per-symbol stays GLOBAL across sessions (no risk multiplication).
Deterministic; no MT5.
"""

from __future__ import annotations

from datetime import datetime, timezone

from forex_swing_orb.bridge.paths import BridgePaths
from forex_swing_orb.compliance import ComplianceConfig, FtmoConfig, FtmoProfile
from forex_swing_orb.producer import ProducerRunner, RunnerConfig, RunnerMode
from forex_swing_orb.producer.contract import CycleOutcome, RunnerReason
from forex_swing_orb.producer.mock_providers import (MockAccountProvider,
                                                     MockBrokerHealthProvider,
                                                     MockMarketDataProvider,
                                                     MockNewsProvider, StubEngine)
from forex_swing_orb.session.profiles import profiles_for
from conftest import _verified_config

# Winter time at which BOTH London and New York strategy windows are open:
# 14:00 UTC == London 14:00 (in [08,21)) and New York 09:00 (in [08,21)).
BOTH = datetime(2026, 1, 7, 14, 0, 0, tzinfo=timezone.utc)


def _compliance(one_per_symbol=True):
    return ComplianceConfig(
        profile=FtmoProfile(
            initial_balance=100000.0, account_currency="USD",
            rule_source="ftmo.com/en/trading-objectives (2-Step)",
            rule_source_verified_at="2026-08-05", profile_verified=True),
        ftmo=FtmoConfig(one_position_per_symbol=one_per_symbol))


def _runner(tmp_path, enabled, now=BOTH, symbols=("EURUSD.FX",), account=None,
            one_per_symbol=True):
    paths = BridgePaths(tmp_path / "bridge").ensure()
    profiles = profiles_for(enabled)
    cfg = RunnerConfig(symbols=symbols, mode=RunnerMode.DEMO,
                       ftmo_profile_verified=True,
                       compliance=_compliance(one_per_symbol),
                       session_profiles=profiles)
    by_session = {p.session_id: StubEngine(emit=True, session_id=p.session_id)
                  for p in profiles}
    runner = ProducerRunner(
        cfg, bridge_paths=paths,
        market=MockMarketDataProvider(symbols, now),
        account=account or MockAccountProvider(now),
        news=MockNewsProvider(now), broker=MockBrokerHealthProvider(),
        strategy_by_session=by_session,
        state_path=str(tmp_path / "state.json"),
        runner_audit_path=str(tmp_path / "ra.jsonl"),
        compliance_audit_path=str(tmp_path / "ca.jsonl"))
    return runner, paths


def _pending(paths):
    return sorted(p.name for p in paths.pending.glob("*.json"))


# --------------------------------------------------------------------------- #
# independent per-session candidates: distinct session_id + signal_id (§26)
# --------------------------------------------------------------------------- #
def test_london_and_new_york_produce_independent_candidates(tmp_path):
    # one_per_symbol OFF here so BOTH sessions may act on each symbol -> proves the
    # sessions are evaluated independently and mint independent identities.
    runner, paths = _runner(tmp_path, ("LONDON", "NEW_YORK"),
                            symbols=("EURUSD.FX", "GBPUSD.FX"), one_per_symbol=False)
    res = runner.run_cycle(BOTH)
    written = [r for r in res if r.outcome == CycleOutcome.INSTRUCTION_WRITTEN]
    sessions = {r.detail.get("session_id") for r in written}
    assert sessions == {"LONDON", "NEW_YORK"}
    sids = {r.signal_id for r in written}
    assert len(sids) == len(written) == 4                    # 2 symbols x 2 sessions, no collisions
    assert len(_pending(paths)) == 4


def test_same_symbol_two_sessions_distinct_signal_ids(tmp_path):
    # even for the SAME symbol the two sessions mint DIFFERENT signal_ids...
    runner, _ = _runner(tmp_path, ("LONDON", "NEW_YORK"), symbols=("EURUSD.FX",))
    res = runner.run_cycle(BOTH)
    sid_by_session = {}
    for r in res:
        if r.signal_id:
            sid_by_session.setdefault(r.detail.get("session_id"), r.signal_id)
    # London and New York evaluated the same bar/symbol -> different identities
    assert sid_by_session.get("LONDON") and sid_by_session.get("NEW_YORK")
    assert sid_by_session["LONDON"] != sid_by_session["NEW_YORK"]


# --------------------------------------------------------------------------- #
# one-position-per-symbol stays GLOBAL across sessions (§18, §27 red team)
# --------------------------------------------------------------------------- #
def test_same_symbol_one_per_symbol_across_sessions(tmp_path):
    # SAME symbol, both sessions active: exactly ONE instruction is written; the
    # second session is suppressed by the account-global one-position-per-symbol rule.
    runner, paths = _runner(tmp_path, ("LONDON", "NEW_YORK"), symbols=("EURUSD.FX",))
    res = runner.run_cycle(BOTH)
    written = [r for r in res if r.outcome == CycleOutcome.INSTRUCTION_WRITTEN]
    suppressed = [r for r in res if RunnerReason.SESSION_SYMBOL_CLAIMED in r.reason_codes]
    assert len(written) == 1                                 # NOT two positions on EURUSD
    assert len(suppressed) == 1
    assert len(_pending(paths)) == 1                         # only one bridge instruction


def test_enabling_all_sessions_does_not_multiply_symbol_exposure(tmp_path):
    runner, paths = _runner(tmp_path, ("SYDNEY", "TOKYO", "LONDON", "NEW_YORK"),
                            symbols=("EURUSD.FX",))
    # 15:00 UTC: London (15:00) + New York (10:00) both active; Sydney/Tokyo checked too
    now = datetime(2026, 1, 7, 15, 0, 0, tzinfo=timezone.utc)
    runner, paths = _runner(tmp_path, ("SYDNEY", "TOKYO", "LONDON", "NEW_YORK"),
                            symbols=("EURUSD.FX",), now=now)
    res = runner.run_cycle(now)
    written = [r for r in res if r.outcome == CycleOutcome.INSTRUCTION_WRITTEN]
    assert len(written) == 1                                 # one symbol -> at most one position
    assert len(_pending(paths)) == 1


# --------------------------------------------------------------------------- #
# configuration ORDER must not change results (§24)
# --------------------------------------------------------------------------- #
def test_config_order_invariance(tmp_path):
    r1, p1 = _runner(tmp_path / "a", ("LONDON", "NEW_YORK"),
                     symbols=("EURUSD.FX", "GBPUSD.FX"))
    r2, p2 = _runner(tmp_path / "b", ("NEW_YORK", "LONDON"),
                     symbols=("EURUSD.FX", "GBPUSD.FX"))
    r1.run_cycle(BOTH)
    r2.run_cycle(BOTH)
    assert _pending(p1) == _pending(p2)                      # identical signal_id set


# --------------------------------------------------------------------------- #
# per-session eligibility windows (§8) — a session out of its window is skipped
# --------------------------------------------------------------------------- #
def test_session_outside_window_is_ineligible(tmp_path):
    # 10:00 UTC: London active (11:00), New York NOT (05:00, before its OR)
    now = datetime(2026, 1, 7, 10, 0, 0, tzinfo=timezone.utc)
    runner, paths = _runner(tmp_path, ("LONDON", "NEW_YORK"),
                            symbols=("EURUSD.FX",), now=now)
    res = runner.run_cycle(now)
    by_session = {r.detail.get("session_id"): r.outcome for r in res}
    assert by_session["NEW_YORK"] == CycleOutcome.SESSION_INELIGIBLE
    assert by_session["LONDON"] == CycleOutcome.INSTRUCTION_WRITTEN


def test_each_session_state_keyed_independently(tmp_path):
    runner, _ = _runner(tmp_path, ("LONDON", "NEW_YORK"),
                        symbols=("EURUSD.FX", "GBPUSD.FX"))
    runner.run_cycle(BOTH)
    keys = set(runner.state.last_processed)
    assert "EURUSD.FX|LONDON" in keys and "EURUSD.FX|NEW_YORK" in keys
    assert "GBPUSD.FX|LONDON" in keys and "GBPUSD.FX|NEW_YORK" in keys


def test_same_bar_not_reevaluated_per_session(tmp_path):
    runner, _ = _runner(tmp_path, ("LONDON", "NEW_YORK"), symbols=("EURUSD.FX",))
    runner.run_cycle(BOTH)
    res2 = runner.run_cycle(BOTH)                            # same bar
    assert all(r.outcome == CycleOutcome.NO_NEW_BAR for r in res2)
