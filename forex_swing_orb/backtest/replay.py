"""Engine driving + the BLOCKING batch-vs-online parity gate (Tier 1).

Reuses the canonical production engine load path (``producer.strategy_adapter.
load_engine_module``) so there is exactly one strategy authority. This module
NEVER computes a signal, direction, entry, stop, target, session, or news
decision itself — it only calls ``SignalEngine.generate`` and compares the
engine's OWN emitted instructions produced two ways:

  * BATCH   — generate once over the full history.
  * ONLINE  — expanding-window walk-forward, mirroring the LIVE path
              (``producer.strategy_adapter.StrategyAdapter.evaluate``): at each
              bar, generate over data up to and including that bar and accept an
              instruction only when it was generated AT the just-closed bar.

If the two disagree on ANY field, parity FAILS and the caller must refuse to
produce performance statistics.
"""

from __future__ import annotations

from ..producer.strategy_adapter import load_engine_module


class ParityError(Exception):
    """Raised when batch and online strategy outputs diverge."""


def load_engine(config=None):
    """Return (engine_module, SignalEngine instance) from the production load path."""
    module = load_engine_module(validate_scrubber=False)
    return module, module.SignalEngine(config or {})


# --- signal identity used for parity (the strategy's OWN emitted fields) ------
_PARITY_FIELDS = (
    "signal_id", "generated_timestamp", "session_id", "symbol", "direction",
    "entry_price", "stop_loss", "take_profit",
)


def signal_key(instr):
    """Canonical comparable tuple for one engine instruction. Includes planned R
    (from the engine's OWN evidence_summary) so a geometry drift is caught too."""
    ev = instr.get("evidence_summary", {}) or {}
    return tuple(instr.get(f) for f in _PARITY_FIELDS) + (ev.get("rr_planned"),)


def batch_instructions(module, data_map, config):
    """Generate ONCE over the full history. Returns (per-symbol instruction lists,
    engine) so the caller can reuse the engine's audit for trade reconstruction."""
    engine = module.SignalEngine(config or {})
    engine.generate(data_map)
    out = {sym: list(engine.instructions.get(sym, [])) for sym in data_map}
    return out, engine


def online_instructions(module, data_map, config, *, start_index=None):
    """Expanding-window walk-forward. For each symbol, step bar by bar; at bar t
    generate over ``df.iloc[:t+1]`` and accept the last instruction ONLY when it
    was generated at bar t (identical acceptance rule to the live StrategyAdapter).

    ``start_index`` skips the leading warmup bars (all DATA_INSUFFICIENT) purely
    for speed — it can never change which signals are emitted, because a signal at
    bar i requires df.iloc[:i+1] and i is always >= min_history_bars anyway.
    """
    fmt = module.format_ts
    out = {}
    for sym, df in data_map.items():
        n = len(df)
        lo = 0 if start_index is None else max(0, int(start_index))
        engine = module.SignalEngine(config or {})
        collected = []
        for t in range(lo, n):
            window = df.iloc[: t + 1]
            engine.generate({sym: window})
            instrs = engine.instructions.get(sym, [])
            if not instrs:
                continue
            last = instrs[-1]
            if last.get("generated_timestamp") == fmt(window.index[-1]):
                collected.append(last)
        out[sym] = collected
    return out


def compare_parity(batch, online):
    """Compare batch vs online signal lists per symbol. Returns
    (ok, first_divergence_dict_or_None). Order-sensitive and exact."""
    for sym in sorted(set(batch) | set(online)):
        b = batch.get(sym, [])
        o = online.get(sym, [])
        bkeys = [signal_key(i) for i in b]
        okeys = [signal_key(i) for i in o]
        if len(bkeys) != len(okeys):
            return False, {
                "symbol": sym, "kind": "COUNT_MISMATCH",
                "batch_count": len(bkeys), "online_count": len(okeys),
                "batch_signal_ids": [i.get("signal_id") for i in b],
                "online_signal_ids": [i.get("signal_id") for i in o],
            }
        for idx, (bk, ok_) in enumerate(zip(bkeys, okeys)):
            if bk != ok_:
                diff = {f: (bv, ov) for f, bv, ov in
                        zip(_PARITY_FIELDS + ("rr_planned",), bk, ok_) if bv != ov}
                return False, {
                    "symbol": sym, "kind": "FIELD_MISMATCH", "position": idx,
                    "batch": dict(zip(_PARITY_FIELDS + ("rr_planned",), bk)),
                    "online": dict(zip(_PARITY_FIELDS + ("rr_planned",), ok_)),
                    "differing_fields": {k: {"batch": v[0], "online": v[1]}
                                         for k, v in diff.items()},
                }
    return True, None


def assert_parity(batch, online):
    """Raise ParityError with the exact first divergence if parity fails."""
    ok, first = compare_parity(batch, online)
    if not ok:
        raise ParityError(first)
    return True
