"""H-1 — aggregate account-risk reservation: bridge outstanding-risk + runner fan-out.

Two layers:
  * observe_entry_bridge now sums the DECLARED risk_fraction of outstanding (pending +
    claimed) intents, deduped, and marks it UNVERIFIABLE (never the whole bridge
    unhealthy — H5 stays separate) when an intent's risk cannot be read;
  * the runner threads that reservation (+ open-position risk) into the compliance
    projection so a same-cycle multi-symbol fan-out cannot each pass against the same
    unreserved equity — the internal daily buffer cannot be bypassed.
Deterministic; no MT5.
"""

from __future__ import annotations

from datetime import datetime, timezone

from forex_swing_orb.bridge import serialize
from forex_swing_orb.bridge.paths import BridgePaths
from forex_swing_orb.compliance import ComplianceConfig, FtmoConfig, FtmoProfile
from forex_swing_orb.producer import ProducerRunner, RunnerConfig, RunnerMode
from forex_swing_orb.producer.bridge_health import observe_entry_bridge
from forex_swing_orb.producer.contract import CycleOutcome, RunnerReason
from forex_swing_orb.producer.mock_providers import (MockAccountProvider,
                                                     MockBrokerHealthProvider,
                                                     MockMarketDataProvider,
                                                     MockNewsProvider, StubEngine)
from forex_swing_orb.session.profiles import profiles_for

NOW = datetime(2026, 1, 7, 14, 0, 0, tzinfo=timezone.utc)   # London strategy window open
GEN = datetime(2026, 1, 7, 13, 59, 0, tzinfo=timezone.utc)
EXP = datetime(2026, 1, 7, 14, 30, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# bridge_health: outstanding risk aggregation
# --------------------------------------------------------------------------- #
def _paths(tmp_path):
    return BridgePaths(tmp_path / "bridge").ensure()


def _write(paths, sid, *, rf=0.0025, symbol="EURUSD.FX", where="pending", omit_rf=False):
    body = {"signal_id": sid, "symbol": symbol,
            "generated_timestamp": serialize.iso_utc(GEN),
            "expiration_timestamp": serialize.iso_utc(EXP)}
    if not omit_rf:
        body["risk_fraction"] = rf
    d = {"pending": paths.pending, "claimed": paths.claimed}[where]
    (d / (sid + ".json")).write_text(serialize.canonical_json(body), encoding="utf-8")


def test_outstanding_risk_sums_pending_and_claimed(tmp_path):
    p = _paths(tmp_path)
    _write(p, "a" * 16, rf=0.0025, where="pending")
    _write(p, "b" * 16, rf=0.0075, symbol="GBPUSD.FX", where="claimed")
    obs = observe_entry_bridge(p, NOW)
    assert obs.healthy and not obs.outstanding_risk_unverifiable
    assert abs(obs.outstanding_risk_fraction - 0.01) < 1e-12


def test_missing_risk_fraction_marks_unverifiable_not_unhealthy(tmp_path):
    p = _paths(tmp_path)
    _write(p, "a" * 16, where="pending", omit_rf=True)
    obs = observe_entry_bridge(p, NOW)
    assert obs.healthy is True                       # H5/ACK health unchanged
    assert obs.outstanding_risk_unverifiable is True # but risk cannot be trusted


def test_duplicate_pending_and_claimed_counted_once(tmp_path):
    p = _paths(tmp_path)
    sid = "c" * 16
    _write(p, sid, rf=0.0025, where="pending")
    _write(p, sid, rf=0.0025, where="claimed")       # same signal in both (claimed wins)
    obs = observe_entry_bridge(p, NOW)
    assert abs(obs.outstanding_risk_fraction - 0.0025) < 1e-12   # not 0.005


def test_no_outstanding_is_zero(tmp_path):
    obs = observe_entry_bridge(_paths(tmp_path), NOW)
    assert obs.outstanding_risk_fraction == 0.0 and not obs.outstanding_risk_unverifiable


# --------------------------------------------------------------------------- #
# runner fan-out: multi-symbol same-cycle reservation
# --------------------------------------------------------------------------- #
def _runner(tmp_path, symbols, rf=0.01, account=None):
    paths = BridgePaths(tmp_path / "bridge").ensure()
    profiles = profiles_for(("LONDON",))
    profile = FtmoProfile(initial_balance=100000.0, account_currency="USD",
                          rule_source="ftmo.com/en/trading-objectives (2-Step)",
                          rule_source_verified_at="2026-08-05", profile_verified=True)
    cfg = RunnerConfig(symbols=symbols, mode=RunnerMode.DEMO, ftmo_profile_verified=True,
                       compliance=ComplianceConfig(profile=profile,
                                                   ftmo=FtmoConfig(one_position_per_symbol=True)),
                       session_profiles=profiles)
    engines = {"LONDON": StubEngine(emit=True, risk_fraction=rf, session_id="LONDON")}
    runner = ProducerRunner(
        cfg, bridge_paths=paths, market=MockMarketDataProvider(symbols, NOW),
        account=account or MockAccountProvider(NOW), news=MockNewsProvider(NOW),
        broker=MockBrokerHealthProvider(), strategy_by_session=engines,
        state_path=str(tmp_path / "state.json"),
        runner_audit_path=str(tmp_path / "ra.jsonl"),
        compliance_audit_path=str(tmp_path / "ca.jsonl"))
    return runner, paths


def test_fanout_cannot_bypass_internal_daily_buffer(tmp_path):
    # 5 symbols, 1% each: cumulative reservation means the 5th (5% > 4% internal buffer)
    # is REJECTED even though each is individually within per-trade risk.
    symbols = ("EURUSD.FX", "GBPUSD.FX", "AUDUSD.FX", "NZDUSD.FX", "USDCAD.FX")
    runner, paths = _runner(tmp_path, symbols, rf=0.01)
    res = runner.run_cycle(NOW)
    written = [r for r in res if r.outcome == CycleOutcome.INSTRUCTION_WRITTEN]
    rejected = [r for r in res if r.outcome == CycleOutcome.COMPLIANCE_REJECT]
    assert len(written) == 4, [r.outcome for r in res]      # 4% buffer holds exactly 4×1%
    assert len(rejected) >= 1
    assert any(RunnerReason.COMPLIANCE_REJECT in r.reason_codes for r in rejected)


def test_two_small_candidates_both_pass(tmp_path):
    # 2 symbols at 0.25% each -> cumulative 0.5% << 4% buffer -> both written
    runner, paths = _runner(tmp_path, ("EURUSD.FX", "GBPUSD.FX"), rf=0.0025)
    res = runner.run_cycle(NOW)
    written = [r for r in res if r.outcome == CycleOutcome.INSTRUCTION_WRITTEN]
    assert len(written) == 2, [(r.outcome, r.reason_codes) for r in res]


def test_open_risk_reduces_capacity(tmp_path):
    # a large pre-existing open-position risk (3.5%) leaves room for only part of a
    # 1%-each fan-out before the internal buffer is hit.
    acct = MockAccountProvider(NOW, open_risk_at_stop=3500.0, open_position_count=1,
                               open_symbols=("XAUUSD.FX",))  # non-traded symbol; risk only
    runner, paths = _runner(tmp_path, ("EURUSD.FX", "GBPUSD.FX"), rf=0.01, account=acct)
    res = runner.run_cycle(NOW)
    # committed starts at 3500; A(1000)->4500>4000 already? projected=100000-3500-1000=95500<96000
    rejected = [r for r in res if r.outcome == CycleOutcome.COMPLIANCE_REJECT]
    assert len(rejected) == 2, [(r.outcome, r.reason_codes) for r in res]  # both blocked


def test_restart_preserves_outstanding_reservation(tmp_path):
    # pre-seed pending instructions (as if written before a restart); a new cycle must
    # count their risk before authorizing more.
    runner, paths = _runner(tmp_path, ("EURUSD.FX",), rf=0.01)
    for i, sid in enumerate(("d" * 16, "e" * 16, "f" * 16, "0" * 16)):  # 4×1% already pending
        _write_bridge(paths, sid, rf=0.01, symbol=f"PRESEED{i}.FX")
    res = runner.run_cycle(NOW)
    # 4% already reserved -> the new EURUSD 1% candidate would make 5% -> REJECT
    assert all(r.outcome != CycleOutcome.INSTRUCTION_WRITTEN for r in res), \
        [(r.outcome, r.reason_codes) for r in res]


def _write_bridge(paths, sid, *, rf, symbol):
    body = {"signal_id": sid, "symbol": symbol, "risk_fraction": rf,
            "generated_timestamp": serialize.iso_utc(GEN),
            "expiration_timestamp": serialize.iso_utc(EXP)}
    (paths.pending / (sid + ".json")).write_text(serialize.canonical_json(body), encoding="utf-8")
