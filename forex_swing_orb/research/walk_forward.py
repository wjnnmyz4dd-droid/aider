"""Walk-forward validation (Phase 9B) — deterministic, read-only.

Rolling out-of-sample windows over the FROZEN SignalEngine (loaded via the accepted
producer.strategy_adapter read-only load path — never copied/rewritten). The
strategy is not re-fit (its parameters are frozen); walk-forward here measures the
STABILITY of the frozen engine's behaviour across rolling regimes. Deterministic:
identical data + windows -> identical results. No randomness, no wall clock.
"""

from __future__ import annotations

import math


def load_frozen_engine(config=None):
    """The ONE frozen SignalEngine, via the accepted load path (read-only reuse)."""
    from ..producer.strategy_adapter import load_engine
    return load_engine(config or {})


def rolling_windows(n, window, step):
    """Deterministic list of (start, end) half-open index ranges of length
    ``window``, advancing by ``step``. Fails closed (empty) on invalid inputs."""
    if window <= 0 or step <= 0 or n < window:
        return []
    out = []
    start = 0
    while start + window <= n:
        out.append((start, start + window))
        start += step
    return out


def run_engine_on_window(engine, df_window, symbol):
    """Read-only single-window engine run. Returns instruction count + last weight
    for the window. Never mutates the engine's ownership of signal logic."""
    weights = engine.generate({symbol: df_window})
    instrs = engine.instructions.get(symbol) or []
    w = weights.get(symbol)
    last_w = None
    try:
        last_w = float(w.iloc[-1]) if w is not None and len(w) else None
    except Exception:
        last_w = None
    return {"instruction_count": len(instrs), "last_weight": last_w,
            "bars": int(len(df_window))}


def walk_forward(engine, df, symbol, *, window, step):
    """Run the engine over each rolling window of ``df`` (a pandas DataFrame with a
    monotonic index). Returns a list of per-window result dicts (deterministic)."""
    windows = rolling_windows(len(df), window, step)
    results = []
    for i, (a, b) in enumerate(windows):
        r = run_engine_on_window(engine, df.iloc[a:b], symbol)
        r["window_index"] = i
        r["start"] = a
        r["end"] = b
        results.append(r)
    return results


def stability(values):
    """Stability of a metric across windows: mean/stdev/min/max + a bounded
    consistency score in [0,1] (1 = perfectly stable). Deterministic."""
    xs = [float(v) for v in values
          if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)]
    if not xs:
        return {"count": 0, "mean": 0.0, "stdev": 0.0, "min": 0.0, "max": 0.0,
                "consistency": 0.0}
    mean = sum(xs) / len(xs)
    stdev = math.sqrt(sum((x - mean) ** 2 for x in xs) / (len(xs) - 1)) if len(xs) > 1 else 0.0
    denom = abs(mean) + stdev
    consistency = round(abs(mean) / denom, 6) if denom > 0 else 1.0
    return {"count": len(xs), "mean": round(mean, 6), "stdev": round(stdev, 6),
            "min": min(xs), "max": max(xs), "consistency": consistency}


def regime_validation(results, regime_of):
    """Bucket per-window results by a caller-supplied regime label and report the
    instruction-count stability within each regime. ``regime_of(window_result)``
    returns a hashable regime label. Deterministic (sorted output)."""
    buckets = {}
    for r in results:
        buckets.setdefault(regime_of(r), []).append(r)
    return {str(k): stability([r["instruction_count"] for r in v])
            for k, v in sorted(buckets.items(), key=lambda kv: str(kv[0]))}
