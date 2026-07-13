"""Monte Carlo simulation: trade-sequence randomization, expected
drawdown, expected equity range, confidence intervals, worst-case
scenarios (ADR-027 §3). Advisory only -- attached to `RiskSnapshot` for
explanation, never consumed by the sizing arithmetic itself.

Uses a **seeded** `random.Random` instance, never the shared global
`random` module -- the same seed and the same historical R-multiples
always reproduce the same simulated distribution (ADR-027 Hard Rule 7),
and a fresh `random.Random()` instance per call is itself thread-safe
(no shared mutable RNG state across concurrent `evaluate()` calls).
"""

from __future__ import annotations

import random
import statistics as pystats
from typing import List, Optional, Sequence, Tuple

from .config import RiskEngineConfig
from .models import MonteCarloResult, TradeHistory


def simulate_equity_paths(
    r_multiples: Sequence[float], seed: int, num_simulations: int, path_length: int,
) -> List[List[float]]:
    """Resamples-with-replacement from the historical R-multiple
    distribution to build `num_simulations` synthetic equity curves,
    each `path_length` trades long. Shared by `statistics.py`'s risk-of-
    ruin estimate so that concept is never computed a second, divergent
    way."""

    if not r_multiples:
        return []
    rng = random.Random(seed)
    paths: List[List[float]] = []
    for _ in range(num_simulations):
        cumulative = 0.0
        path: List[float] = []
        for _ in range(path_length):
            cumulative += rng.choice(r_multiples)
            path.append(cumulative)
        paths.append(path)
    return paths


def _max_drawdown_of_path(path: Sequence[float]) -> float:
    peak = 0.0
    max_dd = 0.0
    for value in path:
        peak = max(peak, value)
        max_dd = max(max_dd, peak - value)
    return max_dd


def percentile(sorted_values: Sequence[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = rank - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * fraction


def run_monte_carlo(trade_history: Optional[TradeHistory], config: RiskEngineConfig) -> Optional[MonteCarloResult]:
    if trade_history is None or len(trade_history.results) < config.min_trade_history_for_statistics:
        return None

    r_multiples = [r.r_multiple for r in sorted(trade_history.results, key=lambda r: r.closed_at)]
    paths = simulate_equity_paths(r_multiples, config.monte_carlo_seed, config.monte_carlo_simulations, config.monte_carlo_sequence_length)
    final_equities = sorted(path[-1] for path in paths)
    drawdowns = [_max_drawdown_of_path(path) for path in paths]

    expected_drawdown = pystats.mean(drawdowns)
    worst_case_drawdown = max(drawdowns)
    percentiles: Tuple[Tuple[int, float], ...] = tuple((p, percentile(final_equities, p)) for p in (5, 25, 50, 75, 95))
    percentile_map = dict(percentiles)

    summary = (
        f"{config.monte_carlo_simulations} seeded simulations (seed={config.monte_carlo_seed}) over "
        f"{config.monte_carlo_sequence_length} trades: median equity {percentile_map[50]:.2f}R, "
        f"5th-95th percentile [{percentile_map[5]:.2f}R, {percentile_map[95]:.2f}R], "
        f"expected drawdown {expected_drawdown:.2f}R, worst-case drawdown {worst_case_drawdown:.2f}R."
    )

    return MonteCarloResult(
        simulations_run=config.monte_carlo_simulations,
        seed=config.monte_carlo_seed,
        expected_drawdown=expected_drawdown,
        expected_equity_low=percentile_map[5],
        expected_equity_high=percentile_map[95],
        confidence_intervals=percentiles,
        worst_case_drawdown=worst_case_drawdown,
        risk_distribution_summary=summary,
    )


__all__ = ["simulate_equity_paths", "percentile", "run_monte_carlo"]
