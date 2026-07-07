"""Monte Carlo simulation over historical Phantom trades (`ADR-022` §1,
capability 1).

Every simulation seeds its own `random.Random` instance (`ADR-022` Hard
Rule 6) — never Python's global `random` module state — so two calls with
the same historical trade sequence and the same `seed` produce byte-
identical `MonteCarloResult`s. `derive_seed()` uses `hashlib` (not the
builtin `hash()`, which is randomized per-process via `PYTHONHASHSEED`
unless explicitly fixed) so a given `trace_id` always derives the same
seed across processes and across time — a genuine determinism
requirement, not a performance choice.

Each simulated path resamples (bootstraps, with replacement) from the
supplied historical P/L distribution — the only historically-grounded way
to project a forward P/L path without fabricating a new distribution
(`ADR-022` Hard Rule 7).
"""

from __future__ import annotations

import hashlib
import random
from typing import Optional, Sequence

from .config import DEFAULT_CONFIG, StatisticalRiskConfig
from .models import MonteCarloResult


def derive_seed(trace_id: str, config: StatisticalRiskConfig = DEFAULT_CONFIG) -> int:
    digest = hashlib.sha256(trace_id.encode("utf-8")).hexdigest()
    return config.monte_carlo_seed_base ^ int(digest[:8], 16)


def simulate(
    pnls: Sequence[float],
    starting_equity: float,
    drawdown_threshold_pct: float,
    seed: int,
    config: StatisticalRiskConfig = DEFAULT_CONFIG,
) -> Optional[MonteCarloResult]:
    """`None` when there is no honest basis to simulate from (Hard Rule
    7) — an empty P/L sample or a non-positive starting equity."""
    if not pnls or starting_equity <= 0:
        return None

    rng = random.Random(seed)
    iterations = config.monte_carlo_iterations
    path_length = len(pnls)

    final_equities = []
    max_drawdowns_pct = []
    breach_count = 0

    for _ in range(iterations):
        equity = starting_equity
        peak = starting_equity
        path_max_drawdown_pct = 0.0
        breached = False
        for _ in range(path_length):
            equity += rng.choice(pnls)
            peak = max(peak, equity)
            drawdown_pct = ((peak - equity) / peak * 100.0) if peak > 0 else 0.0
            path_max_drawdown_pct = max(path_max_drawdown_pct, drawdown_pct)
            if drawdown_pct >= drawdown_threshold_pct:
                breached = True
        final_equities.append(equity)
        max_drawdowns_pct.append(path_max_drawdown_pct)
        if breached:
            breach_count += 1

    final_equities.sort()
    n = len(final_equities)

    return MonteCarloResult(
        iterations=iterations,
        seed=seed,
        starting_equity=starting_equity,
        mean_final_equity=sum(final_equities) / n,
        median_final_equity=final_equities[n // 2],
        worst_final_equity=final_equities[0],
        best_final_equity=final_equities[-1],
        probability_of_ruin=breach_count / iterations,
        mean_max_drawdown_pct=sum(max_drawdowns_pct) / n,
    )


__all__ = ["derive_seed", "simulate"]
