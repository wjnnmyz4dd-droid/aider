"""Statistical analysis over `TradeHistory` (ADR-027 §3): rolling
expectancy, win/loss distribution, risk of ruin, VaR, CVaR, max drawdown
estimate, recovery factor, profit factor, rolling Sharpe/Sortino, Calmar
ratio, Ulcer Index, R-multiple analysis.

Every metric here is `None` and `sufficient_data=False` when
`trade_history` is absent or below `config.min_trade_history_for_statistics`
-- the fail-closed rule from ADR-027 §0a: unknown statistical state is
never reported as favorable.
"""

from __future__ import annotations

import statistics as pystats
from typing import List, Optional, Sequence

from .config import RiskEngineConfig
from .models import RMultipleSummary, StatisticalMetrics, TradeHistory
from .monte_carlo import percentile, simulate_equity_paths


def _windowed_results(trade_history: TradeHistory, config: RiskEngineConfig):
    ordered = sorted(trade_history.results, key=lambda r: r.closed_at)
    return ordered[-config.statistics_window:] if config.statistics_window else ordered


def _equity_curve(r_multiples: Sequence[float]) -> List[float]:
    curve = []
    cumulative = 0.0
    for r in r_multiples:
        cumulative += r
        curve.append(cumulative)
    return curve


def _max_drawdown(equity_curve: Sequence[float]) -> float:
    peak = 0.0
    max_dd = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        max_dd = max(max_dd, peak - value)
    return max_dd


def _ulcer_index(equity_curve: Sequence[float]) -> float:
    if not equity_curve:
        return 0.0
    peak = 0.0
    squared_drawdowns = []
    for value in equity_curve:
        peak = max(peak, value)
        squared_drawdowns.append((peak - value) ** 2)
    return pystats.mean(squared_drawdowns) ** 0.5


def compute_statistical_metrics(trade_history: Optional[TradeHistory], config: RiskEngineConfig) -> StatisticalMetrics:
    sample_size = len(trade_history.results) if trade_history is not None else 0
    if trade_history is None or sample_size < config.min_trade_history_for_statistics:
        return StatisticalMetrics(sufficient_data=False, sample_size=sample_size)

    results = _windowed_results(trade_history, config)
    r_multiples = [r.r_multiple for r in results]
    n = len(r_multiples)

    wins = [r for r in r_multiples if r > 0]
    losses = [r for r in r_multiples if r < 0]
    win_rate = len(wins) / n
    loss_rate = len(losses) / n

    expectancy = pystats.mean(r_multiples)
    std_dev = pystats.pstdev(r_multiples) if n > 1 else 0.0
    downside = [r for r in r_multiples if r < 0]
    downside_std = pystats.pstdev(downside) if len(downside) > 1 else (abs(downside[0]) if downside else 0.0)

    rolling_sharpe = expectancy / std_dev if std_dev > 0 else None
    rolling_sortino = expectancy / downside_std if downside_std > 0 else None

    equity_curve = _equity_curve(r_multiples)
    total_return = equity_curve[-1] if equity_curve else 0.0
    max_dd = _max_drawdown(equity_curve)
    recovery_factor = total_return / max_dd if max_dd > 0 else None

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else None

    elapsed_days = (results[-1].closed_at - results[0].closed_at).days
    elapsed_years = elapsed_days / 365.25 if elapsed_days > 0 else None
    if elapsed_years and max_dd > 0:
        calmar_ratio = (total_return / elapsed_years) / max_dd
    elif max_dd > 0:
        calmar_ratio = total_return / max_dd
    else:
        calmar_ratio = None

    ulcer_index = _ulcer_index(equity_curve)

    sorted_r = sorted(r_multiples)
    var_pct = (1.0 - config.var_confidence) * 100.0
    var_95 = -percentile(sorted_r, var_pct)
    tail = [r for r in sorted_r if r <= percentile(sorted_r, var_pct)]
    cvar_95 = -pystats.mean(tail) if tail else var_95

    paths = simulate_equity_paths(
        r_multiples, config.monte_carlo_seed, config.risk_of_ruin_simulations, config.monte_carlo_sequence_length,
    )
    ruined = sum(1 for path in paths if any(v <= config.risk_of_ruin_ruin_threshold_r for v in path))
    risk_of_ruin = ruined / len(paths) if paths else None

    r_multiple_summary = RMultipleSummary(
        mean=expectancy, std_dev=std_dev, best=max(r_multiples), worst=min(r_multiples), count=n,
    )

    avg_win = pystats.mean(wins) if wins else 0.0
    avg_loss = abs(pystats.mean(losses)) if losses else 0.0
    payoff_ratio = avg_win / avg_loss if avg_loss > 0 else None
    kelly_fraction = win_rate - (loss_rate / payoff_ratio) if payoff_ratio else None

    return StatisticalMetrics(
        sufficient_data=True,
        sample_size=sample_size,
        rolling_expectancy=expectancy,
        win_rate=win_rate,
        loss_rate=loss_rate,
        risk_of_ruin=risk_of_ruin,
        var_95=var_95,
        cvar_95=cvar_95,
        max_drawdown_estimate=max_dd,
        recovery_factor=recovery_factor,
        profit_factor=profit_factor,
        rolling_sharpe=rolling_sharpe,
        rolling_sortino=rolling_sortino,
        calmar_ratio=calmar_ratio,
        ulcer_index=ulcer_index,
        r_multiple_summary=r_multiple_summary,
        kelly_fraction=kelly_fraction,
    )


__all__ = ["compute_statistical_metrics"]
