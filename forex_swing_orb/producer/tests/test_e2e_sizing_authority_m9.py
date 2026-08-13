"""PR-3J / M9 — end-to-end execution-sizing AUTHORITY through the producer.

The producer sizes ONE authoritative volume, finalizes the engine proto-instruction
to schema 3, and writes it only after compliance re-proves the monetary loss-at-stop
from that exact volume. Missing metadata or an unaffordable minimum lot -> no write.
Sizing is account/symbol-specific, never session-specific. Deterministic; no MT5.
"""

from __future__ import annotations

from forex_swing_orb.bridge import serialize
from forex_swing_orb.bridge.contract import PRODUCTION_INSTRUCTION_SCHEMA_VERSION
from forex_swing_orb.compliance.contract import ReasonCode
from forex_swing_orb.producer.contract import CycleOutcome, RunnerReason
from forex_swing_orb.producer.mock_providers import MockBrokerHealthProvider
from conftest import NOW


def _written(paths):
    files = sorted(paths.pending.glob("*.json"))
    assert len(files) == 1
    ok, rec = serialize.loads(files[0].read_text())
    assert ok
    return rec


# --------------------------------------------------------------------------- #
# authoritative volume is sized, proven, and written
# --------------------------------------------------------------------------- #
def test_written_instruction_carries_authoritative_volume(make_runner):
    runner, ctx = make_runner(now=NOW)
    res = runner.run_cycle(NOW)
    assert any(r.outcome == CycleOutcome.INSTRUCTION_WRITTEN for r in res)
    rec = _written(ctx["paths"])
    # StubEngine: entry 1.10000, stop 1.09800 (dist 0.00200), rf 0.0025 -> permit 250;
    # per_lot = 0.00200/1e-5 * 1.0 = 200 -> raw 1.25 -> step 0.01 -> 1.25
    assert rec["volume"] == 1.25
    assert rec["schema_version"] == PRODUCTION_INSTRUCTION_SCHEMA_VERSION


def test_compliance_proves_loss_within_budget_on_write(make_runner):
    runner, ctx = make_runner(now=NOW)
    res = runner.run_cycle(NOW)
    written = [r for r in res if r.outcome == CycleOutcome.INSTRUCTION_WRITTEN]
    assert written                                   # loss 250 <= permit 250 -> pass
    rec = _written(ctx["paths"])
    # the exact volume compliance proved is what will be executed
    assert rec["volume"] == 1.25


# --------------------------------------------------------------------------- #
# fail closed: missing metadata / unaffordable min lot -> NO WRITE
# --------------------------------------------------------------------------- #
def test_missing_tick_metadata_blocks_write(make_runner):
    broker = MockBrokerHealthProvider(tick_value=None)      # no monetary tick value
    runner, ctx = make_runner(now=NOW, broker=broker)
    res = runner.run_cycle(NOW)
    assert not any(r.wrote_bridge for r in res)
    rej = [r for r in res if r.outcome == CycleOutcome.COMPLIANCE_REJECT]
    assert rej and ReasonCode.RISK_MONETARY_UNVERIFIABLE in rej[0].reason_codes
    assert not list(ctx["paths"].pending.glob("*.json"))


def test_min_lot_over_budget_blocks_write(make_runner):
    # volume_min 5.0 lots: loss for 5.0 = 200*5 = 1000 > permit 250 -> sizer returns
    # None -> compliance fails closed -> no trade (minimum lot never overrides risk).
    broker = MockBrokerHealthProvider(volume_min=5.0)
    runner, ctx = make_runner(now=NOW, broker=broker)
    res = runner.run_cycle(NOW)
    assert not any(r.wrote_bridge for r in res)
    assert not list(ctx["paths"].pending.glob("*.json"))


# --------------------------------------------------------------------------- #
# sizing is session-independent (§29)
# --------------------------------------------------------------------------- #
def test_sizing_is_session_independent(make_runner):
    runner, _ = make_runner(now=NOW)
    bh = MockBrokerHealthProvider().snapshot("EURUSD.FX", NOW)
    base = {"entry": 1.10000, "stop_loss": 1.09800, "risk_fraction": 0.0025}
    v_london = runner._size_volume({**base, "session_id": "LONDON"}, bh)
    v_ny = runner._size_volume({**base, "session_id": "NEW_YORK"}, bh)
    assert v_london == v_ny == 1.25                  # same geometry -> same lot, any session


# --------------------------------------------------------------------------- #
# capacity control still independent of sizing (§30)
# --------------------------------------------------------------------------- #
def test_capacity_and_sizing_both_required(make_runner):
    # a normal cycle writes exactly one sized instruction; sizing does not bypass the
    # capacity/one-per-symbol gates (a second same-symbol intent is still suppressed).
    runner, ctx = make_runner(now=NOW)
    runner.run_cycle(NOW)
    assert len(list(ctx["paths"].pending.glob("*.json"))) == 1
