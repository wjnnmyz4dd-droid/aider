"""Currency/pair/rolling correlation, clusters, highly/negatively
correlated positions, cross-currency exposure (ADR-027 §3, Hard Rule 6).

Two independent sources feed the coefficient between any two pairs:

1. **Measured rolling correlation** -- when `TradeHistory` has at least
   `config.min_samples_for_rolling_correlation` closed trades for
   *both* pairs, the Pearson correlation of their most recent
   `config.rolling_correlation_window` R-multiples (aligned by trade
   sequence, not wall-clock time -- documented limitation) is used.
2. **Static same-currency estimate** -- otherwise, a documented,
   config-driven heuristic: pairs sharing a currency correlate at
   `config.shared_currency_correlation_estimate`; a pair that is the
   other's currency-inverse (`EURUSD` vs `USDEUR`-shaped) correlates at
   its negative; otherwise `0.0`.

Neither source is ever silently treated as "no correlation, all clear"
when the truth is unknown -- when portfolio state itself is unknown
(`PortfolioState is None`), there are no open positions to correlate
against in the first place, so this module reports that honestly
(`data_quality=UNKNOWN`, `limit_exceeded=False` because there is
nothing to compare against) rather than fabricating a confident-looking
zero (ADR-027 Hard Rule 6).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from .config import RiskEngineConfig
from .exposure import split_currency_pair
from .models import CorrelationStatus, DataQuality, PortfolioState, TradeHistory


def _pair_r_multiple_series(trade_history: TradeHistory) -> Dict[str, List[float]]:
    by_pair: Dict[str, List[Tuple[object, float]]] = defaultdict(list)
    for result in trade_history.results:
        by_pair[result.pair].append((result.closed_at, result.r_multiple))
    return {pair: [r for _, r in sorted(entries, key=lambda e: e[0])] for pair, entries in by_pair.items()}


def _pearson(xs: List[float], ys: List[float]) -> Optional[float]:
    n = min(len(xs), len(ys))
    if n < 2:
        return None
    xs, ys = xs[-n:], ys[-n:]
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x == 0.0 or var_y == 0.0:
        return None
    return cov / (var_x * var_y) ** 0.5


def _static_estimate(pair_a: str, pair_b: str, config: RiskEngineConfig) -> float:
    """Same-currency heuristic, sign-aware: if the shared currency sits
    on the same side (both base or both quote) of each pair, a long
    position in one implies the same directional exposure to that
    currency as a long position in the other -- positive estimate
    (e.g. `EURUSD`/`GBPUSD`, both quoted in USD). If it sits on
    opposite sides, the exposures offset -- negative estimate (e.g.
    `EURUSD`/`USDCHF`, USD is quote in one and base in the other,
    matching these pairs' well-known real-world negative correlation).
    `sorted()`, not raw set iteration, picks the shared currency when a
    pair shares both -- `set` iteration order depends on `PYTHONHASHSEED`
    and must never leak into a "deterministic" result (ADR-027 Hard Rule 7).
    """

    if pair_a == pair_b:
        return 1.0
    base_a, quote_a = split_currency_pair(pair_a)
    base_b, quote_b = split_currency_pair(pair_b)
    shared = {base_a, quote_a} & {base_b, quote_b}
    if not shared:
        return 0.0
    currency = sorted(shared)[0]
    direction_a = 1 if currency == base_a else -1
    direction_b = 1 if currency == base_b else -1
    sign = 1 if direction_a == direction_b else -1
    return sign * config.shared_currency_correlation_estimate


def estimate_pair_correlation(
    pair_a: str, pair_b: str, trade_history: Optional[TradeHistory], config: RiskEngineConfig,
) -> float:
    if pair_a == pair_b:
        return 1.0
    if trade_history is not None:
        series = _pair_r_multiple_series(trade_history)
        series_a, series_b = series.get(pair_a, []), series.get(pair_b, [])
        if len(series_a) >= config.min_samples_for_rolling_correlation and len(series_b) >= config.min_samples_for_rolling_correlation:
            window = config.rolling_correlation_window
            measured = _pearson(series_a[-window:], series_b[-window:])
            if measured is not None:
                return measured
    return _static_estimate(pair_a, pair_b, config)


def _cluster(pairs: Tuple[str, ...], trade_history: Optional[TradeHistory], config: RiskEngineConfig) -> Tuple[Tuple[str, ...], ...]:
    """Greedy clustering: two pairs join a cluster if their estimated
    correlation is at or above the high-correlation threshold."""

    clusters: List[List[str]] = []
    for pair in pairs:
        placed = False
        for cluster in clusters:
            if any(estimate_pair_correlation(pair, member, trade_history, config) >= config.high_correlation_threshold for member in cluster):
                cluster.append(pair)
                placed = True
                break
        if not placed:
            clusters.append([pair])
    return tuple(tuple(cluster) for cluster in clusters)


def compute_correlation_status(
    pair: str,
    portfolio_state: Optional[PortfolioState],
    trade_history: Optional[TradeHistory],
    config: RiskEngineConfig,
) -> CorrelationStatus:
    if portfolio_state is None:
        return CorrelationStatus(
            pair_correlations=(),
            correlation_clusters=(),
            highly_correlated_pairs=(),
            negatively_correlated_pairs=(),
            cross_currency_exposure_r=0.0,
            limit_exceeded=False,
            reason="Portfolio state unknown -- no open positions to correlate against.",
            data_quality=DataQuality.UNKNOWN,
        )

    open_pairs = tuple(sorted({p.pair for p in portfolio_state.open_positions}))
    correlations = tuple(
        (other, estimate_pair_correlation(pair, other, trade_history, config))
        for other in open_pairs if other != pair
    )
    highly_correlated = tuple(other for other, coeff in correlations if coeff >= config.high_correlation_threshold)
    negatively_correlated = tuple(other for other, coeff in correlations if coeff <= config.negative_correlation_threshold)

    base, quote = split_currency_pair(pair)
    cross_currency_exposure = sum(
        p.size_r for p in portfolio_state.open_positions
        if p.pair != pair and set(split_currency_pair(p.pair)) & {base, quote}
    )

    all_pairs = tuple(sorted(set(open_pairs) | {pair}))
    clusters = _cluster(all_pairs, trade_history, config)

    correlated_risk_r = sum(
        p.size_r for p in portfolio_state.open_positions if p.pair in highly_correlated
    )
    limit_exceeded = correlated_risk_r > config.max_correlated_risk_r
    reason = (
        f"Correlated risk {correlated_risk_r:.2f}R exceeds max_correlated_risk_r={config.max_correlated_risk_r:.2f}R"
        if limit_exceeded else "Within configured correlation limits."
    )

    return CorrelationStatus(
        pair_correlations=correlations,
        correlation_clusters=clusters,
        highly_correlated_pairs=highly_correlated,
        negatively_correlated_pairs=negatively_correlated,
        cross_currency_exposure_r=cross_currency_exposure,
        limit_exceeded=limit_exceeded,
        reason=reason,
        data_quality=DataQuality.KNOWN,
    )


__all__ = ["estimate_pair_correlation", "compute_correlation_status"]
