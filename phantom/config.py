"""Central configuration: score weights, decision thresholds, session and ORB params.

Everything tunable lives here so the scoring model can be adjusted without
touching pipeline logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from typing import Dict


@dataclass(frozen=True)
class Thresholds:
    approve: float = 72.0      # APPROVE  >= 72
    watchlist: float = 60.0    # WATCHLIST 60..71  ; BLOCK < 60
    neutral_cap: float = 55.0  # when bias is NEUTRAL/RANGING the score cannot exceed this


@dataclass(frozen=True)
class ComponentWeights:
    """Maximum points each additive signal component can contribute."""

    h4_trend_alignment: float = 12.0
    d1_trend_alignment: float = 10.0
    bos: float = 10.0
    choch: float = 8.0
    liquidity_sweep: float = 8.0
    fvg: float = 7.0
    order_block: float = 7.0
    rsi_confirmation: float = 8.0
    volatility_health: float = 5.0   # merged ATR + Volatility Ratio (state-based)
    session_filter: float = 5.0
    market_regime: float = 5.0       # environment context only, NOT trend confirmation
    # Guards below are pass/fail (blocking) and contribute 0 points when they pass.
    # AI Meta Filter removed: it re-scored trend/structure/momentum (double-counting).
    # Additive max (excluding ORB) = 12+10+10+8+8+7+7+8+5+5+5 = 85; ORB adds up to +18.


@dataclass(frozen=True)
class ORBParams:
    """Opening-Range-Breakout configuration.

    The opening range is the first ``range_minutes`` after each session open,
    measured on the execution timeframe.
    """

    range_minutes: int = 15
    execution_tf: str = "M15"
    # Session opens, expressed in the session's local timezone.
    london_tz: str = "Europe/London"
    london_open: time = time(8, 0)
    newyork_tz: str = "America/New_York"
    newyork_open: time = time(9, 30)
    # How long after the range closes a breakout remains valid.
    trade_window_minutes: int = 240
    # Range-size sanity gates, expressed as multiples of current ATR.
    min_range_atr_mult: float = 0.35
    max_range_atr_mult: float = 3.0
    # Score impacts (Part 2 spec).
    score_confirmed: float = 8.0
    score_trend_align: float = 5.0
    score_bos: float = 5.0
    score_false_breakout: float = -10.0
    # News blackout radius around session for ORB (minutes).
    news_guard_minutes: int = 30


@dataclass(frozen=True)
class IndicatorParams:
    rsi_period: int = 14
    atr_period: int = 14
    atr_baseline_period: int = 50  # for ATR acceleration / volatility ratio
    swing_lookback: int = 2        # bars each side for a swing pivot


@dataclass(frozen=True)
class VolatilityParams:
    """Bands for the merged Volatility Health component (uses ATR-vs-baseline
    ratio plus ATR acceleration/expansion/compression for the descriptor)."""

    extreme_ratio: float = 2.0     # >= -> Extreme (blow-off) -> -5
    elevated_ratio: float = 1.6    # >= -> Elevated -> +3
    healthy_low: float = 0.8       # [healthy_low, elevated_ratio) -> Healthy -> +5
    # < healthy_low -> Compressed -> 0
    expansion_ratio: float = 1.1   # atr_now/atr_baseline above this = expanding
    compression_ratio: float = 0.7  # below this = compressing


@dataclass(frozen=True)
class GuardParams:
    max_spread: float = 0.0003           # absolute price units (e.g. 3 pips on a 4-dp pair)
    max_account_drawdown_pct: float = 5.0  # prop daily DD limit
    min_rr: float = 2.0                  # RR Validation minimum
    correlation_groups: Dict[str, str] = field(
        default_factory=lambda: {
            # symbol -> correlation bucket; one open trade per bucket
            "EURUSD": "USD_MAJ",
            "GBPUSD": "USD_MAJ",
            "AUDUSD": "USD_MAJ",
            "USDCHF": "USD_MAJ",
            "USDJPY": "JPY",
            "EURJPY": "JPY",
            "XAUUSD": "METALS",
        }
    )
    max_open_per_bucket: int = 1


@dataclass(frozen=True)
class Config:
    thresholds: Thresholds = field(default_factory=Thresholds)
    weights: ComponentWeights = field(default_factory=ComponentWeights)
    orb: ORBParams = field(default_factory=ORBParams)
    indicators: IndicatorParams = field(default_factory=IndicatorParams)
    volatility: VolatilityParams = field(default_factory=VolatilityParams)
    guards: GuardParams = field(default_factory=GuardParams)
    score_floor: float = 0.0
    score_ceiling: float = 100.0


DEFAULT_CONFIG = Config()
