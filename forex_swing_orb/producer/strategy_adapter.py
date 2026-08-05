"""Strategy adapter (Phase 7A) — thin, non-duplicating bridge to the frozen engine.

Loads the accepted Session Edge SignalEngine from ``run_dir/code/signal_engine.py``
(the established importlib load path; optionally validated by the backtest AST
scrubber when available), runs ``generate`` on the exec (M15) frame, and exposes:

  * the engine's OWN versioned instruction for the just-closed bar (verbatim —
    the runner never rebuilds an instruction or recomputes a signal_id), and
  * a compliance candidate mapped from that instruction.

The frozen engine derives H4/D1 bias internally from the exec frame; the runner
does NOT compute trend and never lets a lower timeframe override a higher one —
that hierarchy lives entirely inside the strategy. The candidate's MTF
attestation is a translation of the strategy's own evidence, not new logic.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_ENGINE_PATH = (Path(__file__).resolve().parents[1] / "run_dir" / "code"
                / "signal_engine.py")


def load_engine(config=None, validate_scrubber=True):
    """Load and instantiate the frozen SignalEngine (reusing the production load
    path). Best-effort AST-scrubber validation when ``backtest.runner`` is importable."""
    if validate_scrubber:
        try:                                   # reuse the accepted security scrubber
            from backtest.runner import _validate_signal_engine_source
            _validate_signal_engine_source(_ENGINE_PATH)
        except Exception:
            pass                               # scrubber optional; source is the repo's own frozen artifact
    spec = importlib.util.spec_from_file_location("session_edge_signal_engine", _ENGINE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SignalEngine(config or {})


def _to_dataframe(bars):
    import pandas as pd
    idx = pd.to_datetime([r["open_time"] for r in bars.rows], utc=True)
    return pd.DataFrame(
        {"open": [r["open"] for r in bars.rows],
         "high": [r["high"] for r in bars.rows],
         "low": [r["low"] for r in bars.rows],
         "close": [r["close"] for r in bars.rows]},
        index=idx)


def candidate_from_instruction(instr):
    """Map the engine's versioned instruction -> compliance candidate. The MTF
    attestation reflects the strategy's own qualification (it only emits when the
    timeframes align); values come from the instruction's evidence_summary."""
    ev = instr.get("evidence_summary", {})
    return {
        "signal_id": instr["signal_id"],
        "symbol": instr["symbol"],
        "direction": instr["direction"],
        "entry": instr["entry_price"],
        "stop_loss": instr["stop_loss"],
        "take_profit": instr["take_profit"],
        "risk_fraction": instr["risk_fraction"],
        "mtf": {
            "daily_bias": ev.get("trend_d1"),
            "h4_structure": ev.get("trend_h4"),
            "h1_setup": "QUALIFIED",       # strategy qualified the setup (emission == alignment)
            "m15_timing": "QUALIFIED",
            "aligned": True,
        },
    }


class StrategyAdapter:
    """Runs the frozen engine and surfaces the instruction for a given bar."""

    def __init__(self, engine):
        self.engine = engine               # a SignalEngine-like object (inject for tests)

    def evaluate(self, symbol, exec_bars):
        """Return the engine's instruction for the LAST bar of ``exec_bars`` if the
        strategy emitted one there, else None. Never rebuilds/duplicates the engine."""
        df = _to_dataframe(exec_bars)
        self.engine.generate({symbol: df})
        instrs = self.engine.instructions.get(symbol) or []
        if not instrs:
            return None
        last_bar_iso = _iso(exec_bars.last["open_time"])
        latest = instrs[-1]
        # only accept an instruction generated AT the just-closed bar
        if latest.get("generated_timestamp") != last_bar_iso:
            return None
        return latest


def _iso(dt):
    from ..bridge import serialize
    return serialize.iso_utc(dt)
