"""Integration: a REAL Session Edge engine instruction flows through the bridge.

Skipped when pandas/numpy (the engine's deps) are unavailable, so the bridge's
own suite stays stdlib-only. Proves the producer accepts the engine's actual
instruction dict and the consumer validates+accepts it (transport only).
"""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest

pytest.importorskip("pandas")
pytest.importorskip("numpy")

ENGINE = Path(__file__).resolve().parents[2] / "run_dir" / "code" / "signal_engine.py"
SYNTH = Path(__file__).resolve().parents[2] / "tests"


def _load_engine():
    spec = importlib.util.spec_from_file_location("se_bridge_integ", ENGINE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_engine_instruction_flows_through_bridge(bridge):
    import sys
    if str(SYNTH) not in sys.path:
        sys.path.insert(0, str(SYNTH))
    import synth

    se = _load_engine()
    df = synth.uptrend_frame(days=60)
    df2, _ = synth.inject_bullish_orb(df, "2024-01-25")
    eng = se.SignalEngine({"news_events": [], "news_asof": "2024-01-25T11:15:00Z"})
    eng.generate({"EURUSD.FX": df2})
    instrs = eng.instructions["EURUSD.FX"]
    assert len(instrs) == 1
    # M9: the frozen engine emits a pre-sizing schema-2 proto-instruction; the producer
    # FINALIZES it to the on-wire schema (3) by attaching the sized authoritative volume.
    from forex_swing_orb.bridge.contract import PRODUCTION_INSTRUCTION_SCHEMA_VERSION
    instrs = [{**i, "volume": 0.10,
               "schema_version": PRODUCTION_INSTRUCTION_SCHEMA_VERSION} for i in instrs]

    import tempfile
    now = datetime(2024, 1, 25, 11, 30, tzinfo=timezone.utc)   # between generated & expiry
    with tempfile.TemporaryDirectory() as tmp:
        paths, ledger, audit, consumer = bridge.open_bridge(tmp)
        bridge.write_instructions(paths, instrs, now, audit=audit)
        sid = consumer.claim_next(now)
        assert sid == instrs[0]["signal_id"]
        result = consumer.process(sid, now)
        assert result["status"] == bridge.ResultState.ACCEPTED
        assert (paths.archive_accepted / f"{sid}.json").exists()
