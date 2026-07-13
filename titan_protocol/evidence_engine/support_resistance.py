"""Support/resistance context (ADR-024 Amendment 1).

Concepts that did not exist anywhere in this package before this
amendment: Previous Day/Week/Month High/Low, Session High/Low,
Psychological Levels, Confluence Score, Break Quality Score, False
Break Probability. Every function here either derives a genuinely new
fact from raw bars (multi-timeframe highs/lows, round-number levels) or
re-expresses an already-computed fact from `structure.py`/`liquidity.py`/
`volatility.py` into this new shape (confluence, break quality, false
break probability) -- it never recomputes swings, structure events, or
liquidity sweeps itself.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .config import EvidenceEngineConfig
from .models import (
    Bar,
    ConfluenceZone,
    LiquidityResult,
    MarketStructureResult,
    PriceLevel,
    PsychologicalLevel,
    SessionName,
    SupportResistanceContext,
    VolatilityState,
)
from .session import session_for_hour
from .volatility import atr_series


def _day_key(ts: datetime):
    return (ts.year, ts.month, ts.day)


def _week_key(ts: datetime):
    iso = ts.isocalendar()
    return (iso[0], iso[1])


def _month_key(ts: datetime):
    return (ts.year, ts.month)


def _previous_period_high_low(
    bars: Sequence[Bar], now: datetime, key_func: Callable[[datetime], tuple]
) -> Optional[Tuple[float, float]]:
    """The high/low of the most recent *prior* period represented in the
    data (not necessarily literally "yesterday" -- if a period has no
    bars, e.g. a weekend, the previous period with data is used)."""
    current_key = key_func(now)
    prior_keys = {key_func(b.timestamp) for b in bars if key_func(b.timestamp) < current_key}
    if not prior_keys:
        return None
    prev_key = max(prior_keys)
    period_bars = [b for b in bars if key_func(b.timestamp) == prev_key]
    return max(b.high for b in period_bars), min(b.low for b in period_bars)


def previous_day_high_low(bars: Sequence[Bar], now: datetime) -> Optional[Tuple[float, float]]:
    return _previous_period_high_low(bars, now, _day_key)


def previous_week_high_low(bars: Sequence[Bar], now: datetime) -> Optional[Tuple[float, float]]:
    return _previous_period_high_low(bars, now, _week_key)


def previous_month_high_low(bars: Sequence[Bar], now: datetime) -> Optional[Tuple[float, float]]:
    return _previous_period_high_low(bars, now, _month_key)


def session_high_low(bars: Sequence[Bar], now: datetime, config: EvidenceEngineConfig) -> Tuple[float, float]:
    """High/low of the current session so far (same calendar day, same
    session name, up to and including `now`). Falls back to the most
    recent bar's own high/low if no session bars are found."""
    current_session = session_for_hour(now.hour, config)
    session_bars = [
        b for b in bars
        if b.timestamp.date() == now.date()
        and b.timestamp <= now
        and session_for_hour(b.timestamp.hour, config) == current_session
    ]
    if not session_bars:
        if not bars:
            return (0.0, 0.0)
        return (bars[-1].high, bars[-1].low)
    return max(b.high for b in session_bars), min(b.low for b in session_bars)


def psychological_levels(
    current_price: float, config: EvidenceEngineConfig
) -> Tuple[PsychologicalLevel, ...]:
    """Round-number levels around the current price -- a well-known
    technical concept (traders cluster orders around round numbers),
    deterministic and config-driven (increment + level count), never
    randomly sampled."""
    if config.psychological_level_increment <= 0 or current_price <= 0:
        return ()
    increment = config.psychological_level_increment
    base = round(current_price / increment) * increment
    levels: List[PsychologicalLevel] = []
    for offset in range(-config.psychological_level_count, config.psychological_level_count + 1):
        price = base + offset * increment
        if price <= 0:
            continue
        distance_pct = abs(price - current_price) / current_price * 100.0
        levels.append(PsychologicalLevel(price=price, distance_pct=distance_pct))
    levels.sort(key=lambda lv: lv.price)
    return tuple(levels)


def _cluster_confluence(
    sourced_prices: Sequence[Tuple[str, float]], current_price: float, config: EvidenceEngineConfig
) -> Tuple[ConfluenceZone, ...]:
    """Greedy price clustering across every named S/R source -- a zone
    where N independent sources agree gets a confluence score
    proportional to N, capped at 100."""
    if not sourced_prices:
        return ()
    ordered = sorted(sourced_prices, key=lambda sp: (sp[1], sp[0]))
    zones: List[ConfluenceZone] = []
    cluster: List[Tuple[str, float]] = [ordered[0]]
    tolerance = config.confluence_tolerance_pct / 100.0

    def flush(cluster_items: Sequence[Tuple[str, float]]) -> None:
        prices = [p for _, p in cluster_items]
        avg_price = sum(prices) / len(prices)
        sources = tuple(sorted({name for name, _ in cluster_items}))
        score = min(100.0, 100.0 * len(sources) / config.confluence_full_score_source_count)
        zones.append(ConfluenceZone(price=avg_price, sources=sources, confluence_score=score))

    for item in ordered[1:]:
        anchor = cluster[0][1]
        if anchor != 0 and abs(item[1] - anchor) / abs(anchor) <= tolerance:
            cluster.append(item)
        else:
            flush(cluster)
            cluster = [item]
    flush(cluster)
    zones.sort(key=lambda z: abs(z.price - current_price))
    return tuple(zones)


def compute_break_quality_score(
    structure: MarketStructureResult, bars: Sequence[Bar], config: EvidenceEngineConfig
) -> float:
    """Quality of the most recent structural break: a break confirmed by
    a large-range bar (relative to ATR) is higher quality than one
    confirmed by a small, indecisive bar. Reuses `structure.events` and
    ATR -- never re-derives a break itself."""
    if not structure.events or not bars:
        return config.break_quality_default_score
    latest_event = max(structure.events, key=lambda e: e.confirmed_index)
    if latest_event.confirmed_index >= len(bars):
        return config.break_quality_default_score
    confirming_bar = bars[latest_event.confirmed_index]
    bar_range = confirming_bar.high - confirming_bar.low
    atrs = atr_series(bars, config.atr_period)
    reference_atr = atrs[latest_event.confirmed_index]
    if reference_atr <= 0:
        return config.break_quality_default_score
    ratio = bar_range / reference_atr
    score = 100.0 * (ratio / config.break_quality_atr_reference_multiple)
    return max(0.0, min(100.0, score))


def compute_false_break_probability(liquidity: LiquidityResult, config: EvidenceEngineConfig) -> float:
    """Reuses the already-computed `LiquiditySweep.is_trap`/
    `displacement_follow_through` classification -- never re-derives a
    sweep. No sweeps observed yet is a moderate-uncertainty default, not
    an assumption of safety."""
    if not liquidity.sweeps:
        return config.false_break_probability_default
    latest_sweep = max(liquidity.sweeps, key=lambda s: s.sweep_index)
    if latest_sweep.is_trap:
        return config.false_break_probability_trap
    if latest_sweep.displacement_follow_through:
        return config.false_break_probability_confirmed
    return config.false_break_probability_default


def build_support_resistance_context(
    bars: Sequence[Bar],
    now: datetime,
    structure: MarketStructureResult,
    liquidity: LiquidityResult,
    volatility: VolatilityState,
    config: EvidenceEngineConfig,
) -> SupportResistanceContext:
    if not bars:
        raise ValueError("build_support_resistance_context() requires at least one bar")

    current_price = bars[-1].close
    prev_day = previous_day_high_low(bars, now)
    prev_week = previous_week_high_low(bars, now)
    prev_month = previous_month_high_low(bars, now)
    session_high, session_low = session_high_low(bars, now, config)
    psych_levels = psychological_levels(current_price, config)

    sourced_prices: List[Tuple[str, float]] = []
    for level in structure.support_levels:
        sourced_prices.append(("support", level.price))
    for level in structure.resistance_levels:
        sourced_prices.append(("resistance", level.price))
    if prev_day is not None:
        sourced_prices.append(("previous_day_high", prev_day[0]))
        sourced_prices.append(("previous_day_low", prev_day[1]))
    if prev_week is not None:
        sourced_prices.append(("previous_week_high", prev_week[0]))
        sourced_prices.append(("previous_week_low", prev_week[1]))
    if prev_month is not None:
        sourced_prices.append(("previous_month_high", prev_month[0]))
        sourced_prices.append(("previous_month_low", prev_month[1]))
    sourced_prices.append(("session_high", session_high))
    sourced_prices.append(("session_low", session_low))
    for level in psych_levels:
        sourced_prices.append(("psychological", level.price))

    confluence_zones = _cluster_confluence(sourced_prices, current_price, config)
    break_quality_score = compute_break_quality_score(structure, bars, config)
    false_break_probability = compute_false_break_probability(liquidity, config)

    return SupportResistanceContext(
        previous_day_high=prev_day[0] if prev_day else None,
        previous_day_low=prev_day[1] if prev_day else None,
        previous_week_high=prev_week[0] if prev_week else None,
        previous_week_low=prev_week[1] if prev_week else None,
        previous_month_high=prev_month[0] if prev_month else None,
        previous_month_low=prev_month[1] if prev_month else None,
        session_high=session_high,
        session_low=session_low,
        psychological_levels=psych_levels,
        confluence_zones=confluence_zones,
        break_quality_score=break_quality_score,
        false_break_probability=false_break_probability,
    )


__all__ = [
    "previous_day_high_low",
    "previous_week_high_low",
    "previous_month_high_low",
    "session_high_low",
    "psychological_levels",
    "compute_break_quality_score",
    "compute_false_break_probability",
    "build_support_resistance_context",
]
