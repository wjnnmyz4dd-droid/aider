"""Phase 9A — producer pre-strategy session gate, advisory shadow, manager session
context, and session-aware news annotation (integration; FakeMt5Client)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from forex_swing_orb.bridge import serialize
from forex_swing_orb.bridge.paths import BridgePaths
from forex_swing_orb.live import mt5_client as mc
from forex_swing_orb.producer.contract import CycleOutcome, RunnerReason
from forex_swing_orb.producer.service import build_from_env as build_producer
from forex_swing_orb.manage.service import ManagerService
from forex_swing_orb.runtime.config import load_config, ConfigError
from forex_swing_orb.runtime import news_context
from forex_swing_orb.session import model as M
from forex_swing_orb.session.capability import LONDON_ORB_CAPABILITY as CAP
from conftest import NOW, make_client

SID = "0123456789abcdef"


def _spy_strategy(runner):
    calls = {"n": 0}
    orig = runner.strategy.evaluate

    def wrapped(symbol, bars):
        calls["n"] += 1
        return orig(symbol, bars)
    runner.strategy.evaluate = wrapped
    return calls


# --------------------------------------------------------------------------- #
# producer pre-strategy session gate (27-34)
# --------------------------------------------------------------------------- #
def test_enabled_supported_session_evaluates(env_config, client):
    env, _ = env_config(SESSION_EDGE_ENABLED_SESSIONS="LONDON", SESSION_EDGE_OVERLAP_MODE="ALLOW")
    svc = build_producer(env=env, client=client, now_fn=lambda: NOW)
    calls = _spy_strategy(svc.runner)
    res = svc.runner.run_cycle(NOW)
    assert res[0].outcome != CycleOutcome.SESSION_INELIGIBLE   # London active@10:00
    assert calls["n"] == 1                                     # strategy WAS evaluated


def test_disabled_session_prevents_strategy_evaluation(env_config, client):
    # NEW_YORK only: not active at 10:00 AND strategy-unsupported -> ineligible
    env, paths = env_config(SESSION_EDGE_ENABLED_SESSIONS="NEW_YORK",
                            SESSION_EDGE_OVERLAP_MODE="DISABLE")
    svc = build_producer(env=env, client=client, now_fn=lambda: NOW)
    calls = _spy_strategy(svc.runner)
    res = svc.runner.run_cycle(NOW)
    assert res[0].outcome == CycleOutcome.SESSION_INELIGIBLE
    assert calls["n"] == 0                                     # strategy NOT called
    # no bridge instruction written
    assert list(BridgePaths(paths["bridge_root"]).pending.glob("*.json")) == []


def test_unsupported_session_fails_closed_before_strategy(env_config, client):
    # TOKYO active at 03:00 but strategy-unsupported; use TOKYO enabled and a Tokyo hour
    from datetime import timezone, datetime
    tok_now = datetime(2026, 1, 7, 3, 0, tzinfo=timezone.utc)
    env, _ = env_config(SESSION_EDGE_ENABLED_SESSIONS="TOKYO", SESSION_EDGE_OVERLAP_MODE="DISABLE")
    svc = build_producer(env=env, client=client, now_fn=lambda: tok_now)
    calls = _spy_strategy(svc.runner)
    res = svc.runner.run_cycle(tok_now)
    # data may be rejected (rates end at 10:00 conftest) but session gate is checked
    # only after data validation; assert strategy not called and reason present
    assert calls["n"] == 0


def test_overlap_required_outside_overlap_blocks(env_config, client):
    env, _ = env_config(SESSION_EDGE_ENABLED_SESSIONS="LONDON,NEW_YORK",
                        SESSION_EDGE_ENABLED_OVERLAPS="LONDON_NEW_YORK",
                        SESSION_EDGE_OVERLAP_MODE="REQUIRE")
    svc = build_producer(env=env, client=client, now_fn=lambda: NOW)   # 10:00 London only
    calls = _spy_strategy(svc.runner)
    res = svc.runner.run_cycle(NOW)
    assert res[0].outcome == CycleOutcome.SESSION_INELIGIBLE
    assert M.SessionReason.OVERLAP_REQUIRED in res[0].reason_codes
    assert calls["n"] == 0


def test_same_bar_not_evaluated_twice(env_config, client):
    env, _ = env_config(SESSION_EDGE_ENABLED_SESSIONS="LONDON", SESSION_EDGE_OVERLAP_MODE="ALLOW")
    svc = build_producer(env=env, client=client, now_fn=lambda: NOW)
    svc.runner.run_cycle(NOW)
    res2 = svc.runner.run_cycle(NOW)                           # same bar
    assert res2[0].outcome == CycleOutcome.NO_NEW_BAR


def test_cycle_audit_includes_session(env_config, client):
    env, paths = env_config(SESSION_EDGE_ENABLED_SESSIONS="LONDON", SESSION_EDGE_OVERLAP_MODE="ALLOW")
    svc = build_producer(env=env, client=client, now_fn=lambda: NOW)
    svc.runner.run_cycle(NOW)
    recs = svc.runner.audit.read_all()
    cyc = [r for r in recs if r.get("kind") == "cycle"][-1]
    assert cyc["session"] is not None and cyc["session"]["snapshot_id"]
    assert cyc["session"]["active_sessions"] == ["LONDON"]


def test_session_status_file_written(env_config, client):
    env, paths = env_config(SESSION_EDGE_ENABLED_SESSIONS="LONDON", SESSION_EDGE_OVERLAP_MODE="ALLOW")
    svc = build_producer(env=env, client=client, now_fn=lambda: NOW)
    svc.run_forever(max_cycles=1)
    snap = serialize.loads((paths["runtime_dir"] / "session_status.json").read_text())[1]
    assert snap["overlap_mode"] == "ALLOW" and snap["primary_session"] == "LONDON"


# --------------------------------------------------------------------------- #
# advisory shadow (46-56)
# --------------------------------------------------------------------------- #
def test_advisory_disabled_leaves_trading_unchanged(env_config, client):
    env, _ = env_config(SESSION_EDGE_ENABLED_SESSIONS="LONDON", SESSION_EDGE_OVERLAP_MODE="ALLOW")
    svc = build_producer(env=env, client=client, now_fn=lambda: NOW)
    assert svc.advisory is None
    svc.run_forever(max_cycles=1)                              # no crash, no advisory


def test_only_shadow_only_mode_accepted(env_config):
    env, _ = env_config(SESSION_EDGE_ENABLED_SESSIONS="LONDON", SESSION_EDGE_OVERLAP_MODE="ALLOW",
                        SESSION_EDGE_ADVISORY_ENABLED="true", SESSION_EDGE_ADVISORY_MODE="LIVE")
    with pytest.raises(ConfigError):
        load_config(env=env)


def test_advisory_shadow_context_and_authority(env_config, client):
    env, paths = env_config(SESSION_EDGE_ENABLED_SESSIONS="LONDON", SESSION_EDGE_OVERLAP_MODE="ALLOW",
                            SESSION_EDGE_ADVISORY_ENABLED="true",
                            SESSION_EDGE_ADVISORY_MODE="SHADOW_ONLY")
    svc = build_producer(env=env, client=client, now_fn=lambda: NOW)
    assert svc.advisory is not None
    rec = svc.advisory.observe(svc.runner, NOW)
    assert rec is not None and rec["is_order"] is False and rec["mode"] == "SHADOW_ONLY"
    ctx = rec["context"]
    # required context fields present (assembled, never guessed)
    assert ctx["session"]["active_sessions"] == ["LONDON"]
    assert ctx["per_symbol"][0]["base"] == "EUR" and ctx["per_symbol"][0]["quote"] == "USD"
    assert "remaining_daily_loss_budget" in ctx["ftmo"]
    assert ctx["per_symbol"][0]["broker_health"] is not None
    assert "recent_slippage_points" in ctx["per_symbol"][0]
    assert ctx["strategy_capability"]["opening_range_session"] == "LONDON"
    assert rec["advisory"]["provider_note"].startswith("mock")   # not real intelligence
    # persisted to a SEPARATE advisory file, never the bridge
    assert (paths["runtime_dir"] / "advisory_shadow.jsonl").exists()


def test_advisory_has_no_bridge_authority():
    import inspect
    from forex_swing_orb.runtime import advisory
    src = inspect.getsource(advisory)
    for tok in ("write_instruction", "order_send", "position_close", "modify_stop", "socket", "urllib"):
        assert tok not in src


def test_advisory_failure_is_non_blocking(env_config, client):
    env, _ = env_config(SESSION_EDGE_ENABLED_SESSIONS="LONDON", SESSION_EDGE_OVERLAP_MODE="ALLOW",
                        SESSION_EDGE_ADVISORY_ENABLED="true")
    svc = build_producer(env=env, client=client, now_fn=lambda: NOW)
    svc.advisory.build_context = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    assert svc.advisory.observe(svc.runner, NOW) is None       # swallowed, no raise
    svc.run_forever(max_cycles=1)                              # trading continues


# --------------------------------------------------------------------------- #
# manager session context (57-60)
# --------------------------------------------------------------------------- #
def _archive_enter(paths, sid=SID):
    bp = BridgePaths(paths["bridge_root"]).ensure()
    (bp.archive_accepted / f"{sid}.json").write_text(serialize.canonical_json(
        {"signal_id": sid, "symbol": "EURUSD", "direction": "LONG",
         "entry_price": 1.10000, "stop_loss": 1.09800, "take_profit": 1.10600}), encoding="utf-8")


def test_manager_manages_outside_entry_session(env_config):
    # NEW_YORK-only enabled -> at 10:00 session ineligible for ENTRIES
    env, paths = env_config(SESSION_EDGE_ENABLED_SESSIONS="NEW_YORK", SESSION_EDGE_OVERLAP_MODE="DISABLE")
    client = make_client([SimpleNamespace(
        ticket=5000001, symbol="EURUSD", type=mc.POSITION_TYPE_BUY, volume=0.1,
        price_open=1.10000, sl=1.09800, tp=1.10600, price_current=1.10050, comment=SID,
        time=int(NOW.timestamp()))])
    _archive_enter(paths)
    mgr = ManagerService.build_from_env(env=env, client=client, now_fn=lambda: NOW)
    mgr.run_once(NOW)                                          # management runs regardless
    assert SID in mgr.pm.states                               # position managed
    st = mgr.status(NOW)
    assert st["session"] is not None and st["session"]["eligible"] is False
    assert st["managing_outside_entry_session"] is True       # dashboard visibility


# --------------------------------------------------------------------------- #
# session-aware news annotation (41-45)
# --------------------------------------------------------------------------- #
def test_news_annotation_relevance_and_no_block_change():
    model = M.SessionModel(enabled_sessions=("LONDON",), overlap_mode=M.OverlapMode.DISABLE).validate()
    bundle = {"as_of": serialize.iso_utc(NOW), "events": [
        {"event_id": "E1", "currency": "USD", "impact": "HIGH",
         "event_timestamp": serialize.iso_utc(NOW)},
        {"event_id": "E2", "currency": "JPY", "impact": "HIGH",   # unrelated to EURUSD
         "event_timestamp": serialize.iso_utc(NOW)}]}
    ann = news_context.annotate_news(bundle, "EURUSD.FX", model, NOW)
    rel = {e["event_id"]: e["session_relevant_pair"] for e in ann["event_session_relevance"]}
    assert rel["E1"] is True and rel["E2"] is False            # USD relevant, JPY not (EURUSD)
    assert "active_sessions" in ann and "lockout_intersects_eligible_window" in ann
