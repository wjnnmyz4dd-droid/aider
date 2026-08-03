"""Performance Attribution Engine (ADR-029 §5): one generic grouping
function, reused for all 13 named dimensions -- never 13 near-identical
implementations (CLAUDE.md §6). Every bucket's statistics come from
`titan_protocol.risk_engine.statistics`'s already-accepted pure functions,
never a second implementation (ADR-029 §0, Hard Rule 3)."""

from __future__ import annotations

from collections import defaultdict
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from titan_protocol.risk_engine.config import RiskEngineConfig
from titan_protocol.risk_engine.models import StatisticalMetrics, TradeHistory, TradeResult
from titan_protocol.risk_engine.statistics import compute_statistical_metrics

from .config import ResearchEngineConfig
from .models import AttributionBucket, AttributionDimension, ClosedTrade, PerformanceAttribution, executed_trades


def _to_trade_result(trade: ClosedTrade) -> TradeResult:
    return TradeResult(
        pair=trade.pair, strategy_id=trade.strategy_id, risk_r=trade.risk_r, r_multiple=trade.r_multiple,
        opened_at=trade.opened_at, closed_at=trade.closed_at, won=trade.won,
    )


def compute_bucket_statistics(trades: Sequence[ClosedTrade], config: ResearchEngineConfig) -> StatisticalMetrics:
    """Rejected candidates (no `r_multiple`) carry no P&L to attribute
    and are excluded before conversion (ADR-029 §3)."""

    executed = executed_trades(trades)
    history = TradeHistory(results=tuple(_to_trade_result(t) for t in executed))
    risk_config = RiskEngineConfig(
        min_trade_history_for_statistics=config.bucket_statistics_min_sample_size,
        statistics_window=max(len(executed), 1),
        risk_of_ruin_simulations=config.bucket_risk_of_ruin_simulations,
        monte_carlo_sequence_length=config.bucket_monte_carlo_sequence_length,
    )
    return compute_statistical_metrics(history, risk_config)


def attribute_by(
    trades: Sequence[ClosedTrade], key_func: Callable[[ClosedTrade], Optional[str]], config: ResearchEngineConfig,
) -> Tuple[AttributionBucket, ...]:
    """Groups executed trades by `key_func`'s result -- rejected
    candidates carry no P&L to attribute and are excluded up front;
    trades for which `key_func` returns `None` (the dimension doesn't
    apply) are excluded from that dimension's buckets entirely, never
    lumped into a fake "unknown" bucket."""

    groups: Dict[str, List[ClosedTrade]] = defaultdict(list)
    for trade in executed_trades(trades):
        key = key_func(trade)
        if key is not None:
            groups[key].append(trade)

    buckets = [
        AttributionBucket(
            key=key, sample_size=len(group), total_r=sum(t.r_multiple for t in group),
            statistics=compute_bucket_statistics(group, config),
        )
        for key, group in groups.items()
    ]
    return tuple(sorted(buckets, key=lambda b: b.key))


def _pair_key(t: ClosedTrade) -> Optional[str]:
    return t.pair


def _strategy_key(t: ClosedTrade) -> Optional[str]:
    return t.strategy_id.value if t.strategy_id else None


def _session_key(t: ClosedTrade) -> Optional[str]:
    return t.session.value if t.session else None


def _regime_key(t: ClosedTrade) -> Optional[str]:
    return t.market_regime.value if t.market_regime else None


def _trend_vs_range_key(t: ClosedTrade) -> Optional[str]:
    return t.trend_vs_range.value if t.trend_vs_range else None


def _news_category_key(t: ClosedTrade) -> Optional[str]:
    return t.news_category.value if t.news_category else None


def _volatility_bucket_key(t: ClosedTrade) -> Optional[str]:
    return t.volatility_bucket.value


def _candlestick_key(t: ClosedTrade) -> Optional[str]:
    return t.candlestick_pattern.value if t.candlestick_pattern else None


def _sr_interaction_key(t: ClosedTrade) -> Optional[str]:
    return t.support_resistance_interaction.value


def _liquidity_sweep_key(t: ClosedTrade) -> Optional[str]:
    return "SWEEP" if t.liquidity_sweep_occurred else "NO_SWEEP"


def _bos_fvg_key(t: ClosedTrade) -> Optional[str]:
    return "BOS_FVG" if t.bos_fvg_occurred else "NO_BOS_FVG"


def _time_of_day_key(t: ClosedTrade) -> Optional[str]:
    return f"{t.evaluated_at.hour:02d}:00"


def _day_of_week_key(t: ClosedTrade) -> Optional[str]:
    """Derived from `evaluated_at.weekday()`, never a stored field --
    one source of truth (ADR-029 §3). `evaluated_at` is used rather
    than `opened_at` since it is always present, even for a trade this
    dimension excludes for other reasons upstream."""

    return t.evaluated_at.strftime("%A")


DIMENSION_KEY_FUNCS: Dict[AttributionDimension, Callable[[ClosedTrade], Optional[str]]] = {
    AttributionDimension.PAIR: _pair_key,
    AttributionDimension.STRATEGY: _strategy_key,
    AttributionDimension.SESSION: _session_key,
    AttributionDimension.REGIME: _regime_key,
    AttributionDimension.TREND_VS_RANGE: _trend_vs_range_key,
    AttributionDimension.NEWS_CATEGORY: _news_category_key,
    AttributionDimension.VOLATILITY_BUCKET: _volatility_bucket_key,
    AttributionDimension.CANDLESTICK_PATTERN: _candlestick_key,
    AttributionDimension.SR_INTERACTION: _sr_interaction_key,
    AttributionDimension.LIQUIDITY_SWEEP: _liquidity_sweep_key,
    AttributionDimension.BOS_FVG: _bos_fvg_key,
    AttributionDimension.TIME_OF_DAY: _time_of_day_key,
    AttributionDimension.DAY_OF_WEEK: _day_of_week_key,
}


def attribute_all_dimensions(trades: Sequence[ClosedTrade], config: ResearchEngineConfig) -> Tuple[PerformanceAttribution, ...]:
    return tuple(
        PerformanceAttribution(dimension=dimension, buckets=attribute_by(trades, key_func, config))
        for dimension, key_func in DIMENSION_KEY_FUNCS.items()
    )


__all__ = ["compute_bucket_statistics", "attribute_by", "DIMENSION_KEY_FUNCS", "attribute_all_dimensions"]
