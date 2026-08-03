"""Integration: run the Swing-ORB SignalEngine through Vibe-Trading's ForexEngine.

Skipped automatically when the Vibe-Trading backtest package is not importable
(so the strategy's own suite stays self-contained on pandas/numpy). When present,
this proves the run-dir contract end-to-end: the runner's AST scrubber accepts
the file, the ForexEngine consumes the per-bar weight Series, and a trade
executes with the modeled forex costs.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

import synth

pytest.importorskip("backtest.engines.forex")
pytest.importorskip("backtest.runner")

ENGINE_PATH = Path(__file__).resolve().parents[1] / "run_dir" / "code" / "signal_engine.py"


def _fake_loader(df):
    dfn = df.copy()
    dfn.index = dfn.index.tz_convert("UTC").tz_localize(None)

    class FakeLoader:
        name = "local"
        markets = {"forex"}
        requires_auth = False

        def is_available(self):
            return True

        def fetch(self, codes, s, e, *, interval="15m", fields=None):
            return {c: dfn.copy() for c in codes}

    return FakeLoader()


def test_run_dir_source_passes_scrubber():
    from backtest.runner import _validate_signal_engine_source, _validate_signal_engine_class, _load_module_from_file
    _validate_signal_engine_source(ENGINE_PATH)
    mod = _load_module_from_file(ENGINE_PATH, "swing_orb_integ")
    _validate_signal_engine_class(mod.SignalEngine)


def test_forex_engine_executes_long():
    from backtest.runner import _load_module_from_file
    from backtest.engines.forex import ForexEngine

    se = _load_module_from_file(ENGINE_PATH, "swing_orb_integ2")
    df = synth.uptrend_frame(days=60)
    df2, _ = synth.inject_bullish_orb(df, "2024-01-25")
    cfg = {"codes": ["EURUSD.FX"], "interval": "15m", "initial_cash": 100000,
           "start_date": "2024-01-01", "end_date": "2024-03-01", "source": "local"}
    with tempfile.TemporaryDirectory() as tmp:
        eng = ForexEngine(cfg)
        metrics = eng.run_backtest(cfg, _fake_loader(df2), se.SignalEngine(), Path(tmp), bars_per_year=35040)
    assert len(eng.trades) == 1
    assert metrics.get("total_turnover", 0) > 0
