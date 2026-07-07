"""Probability of reaching a drawdown limit, and Risk of Ruin estimation
(`ADR-022` §1, capabilities 8, 9, 12).

Every probability here is read off the same Monte Carlo simulation
(`monte_carlo.simulate`) run against a specific drawdown threshold: the
fraction of simulated paths whose peak-to-trough drawdown reached that
threshold at least once. Risk of Ruin is the same computation against a
configured "ruin" threshold (`StatisticalRiskConfig.monte_carlo_ruin_threshold_pct`,
e.g. 50% equity loss) rather than a second, independent formula — one
simulation engine, three different threshold readings.
"""

from __future__ import annotations

from typing import Optional, Sequence

from . import monte_carlo
from .config import DEFAULT_CONFIG, StatisticalRiskConfig


def probability_of_reaching_daily_drawdown_limit(
    pnls: Sequence[float],
    starting_equity: float,
    seed: int,
    config: StatisticalRiskConfig = DEFAULT_CONFIG,
) -> Optional[float]:
    result = monte_carlo.simulate(pnls, starting_equity, config.daily_drawdown_limit_pct, seed, config)
    return result.probability_of_ruin if result is not None else None


def probability_of_reaching_total_drawdown_limit(
    pnls: Sequence[float],
    starting_equity: float,
    seed: int,
    config: StatisticalRiskConfig = DEFAULT_CONFIG,
) -> Optional[float]:
    result = monte_carlo.simulate(pnls, starting_equity, config.total_drawdown_limit_pct, seed, config)
    return result.probability_of_ruin if result is not None else None


def risk_of_ruin(
    pnls: Sequence[float],
    starting_equity: float,
    seed: int,
    config: StatisticalRiskConfig = DEFAULT_CONFIG,
) -> Optional[float]:
    result = monte_carlo.simulate(
        pnls, starting_equity, config.monte_carlo_ruin_threshold_pct, seed, config
    )
    return result.probability_of_ruin if result is not None else None


__all__ = [
    "probability_of_reaching_daily_drawdown_limit",
    "probability_of_reaching_total_drawdown_limit",
    "risk_of_ruin",
]
