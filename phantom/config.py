"""Central configuration: score weights, decision thresholds, session and ORB params.

Everything tunable lives here so the scoring model can be adjusted without
touching pipeline logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from typing import Dict, List


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
class StrategyParams:
    """Multi-strategy signal layer. All values are score contributions; the
    layer NEVER creates trades."""

    # Liquidity Sweep Reversal
    sweep_choch: float = 10.0
    sweep_ob: float = 5.0
    sweep_fvg: float = 5.0
    rejection_wick_ratio: float = 0.5  # wick beyond swing >= this * candle range

    # Session Breakout Continuation (Asia range, UTC hours)
    asia_start_hour: int = 0
    asia_end_hour: int = 6
    asia_trade_until_hour: int = 21
    session_breakout: float = 8.0
    session_trend: float = 5.0
    session_bos: float = 5.0

    # Conflict resolution + anti-inflation
    conflict_dampen: float = 0.5       # opposing sides cancel to their difference * this
    confluence_bonus_per: float = 3.0  # bonus per extra agreeing strategy
    confluence_cap: float = 6.0
    layer_cap: float = 18.0            # max positive strategy-layer contribution
                                       # (== prior ORB max -> provably no inflation)


@dataclass(frozen=True)
class SymbolProfile:
    """Per-symbol microstructure. ``max_spread_points`` is in the symbol's own
    points (spread / pip_size), so one profile works across pairs, JPY, metals
    and indices."""

    pip_size: float
    max_spread_points: float


def _default_symbol_profiles() -> Dict[str, "SymbolProfile"]:
    return {
        # FX majors: pip = 0.0001, ~3 point cap (== the legacy 0.0003 abs cap).
        "EURUSD": SymbolProfile(0.0001, 3.0),
        "GBPUSD": SymbolProfile(0.0001, 3.0),
        "AUDUSD": SymbolProfile(0.0001, 3.0),
        "NZDUSD": SymbolProfile(0.0001, 3.0),
        "USDCAD": SymbolProfile(0.0001, 3.0),
        "USDCHF": SymbolProfile(0.0001, 3.0),
        # JPY: pip = 0.01.
        "USDJPY": SymbolProfile(0.01, 3.0),
        "EURJPY": SymbolProfile(0.01, 3.0),
        # Metals / indices: wider caps, larger point size.
        "XAUUSD": SymbolProfile(0.1, 50.0),
        "US30": SymbolProfile(1.0, 8.0),
        "NAS100": SymbolProfile(1.0, 5.0),
    }


@dataclass(frozen=True)
class GuardParams:
    max_spread: float = 0.0003           # legacy fallback for symbols without a profile
    max_account_drawdown_pct: float = 5.0  # legacy scalar daily-DD fallback
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
    # FIX 3 — correlation fail-closed for unknown symbols.
    correlation_fail_closed: bool = True
    derive_correlation_bucket: bool = False  # if True, derive bucket from FX legs instead
    # FIX 2 — same-direction stacking / exposure controls.
    max_positions_per_symbol: int = 1
    allow_stacking: bool = False
    max_symbol_exposure_pct: float = 100.0
    # FIX 4 — prop compliance hardening (used when live equity is supplied).
    max_daily_dd_pct: float = 5.0
    max_total_dd_pct: float = 10.0
    # FIX 5 — symbol-aware spread.
    symbol_profiles: Dict[str, SymbolProfile] = field(default_factory=_default_symbol_profiles)
    # FIX 6 — non-FX news exposure map.
    instrument_exposure_map: Dict[str, List[str]] = field(
        default_factory=lambda: {
            "XAUUSD": ["USD"], "XAGUSD": ["USD"],
            "US30": ["USD"], "NAS100": ["USD"], "SPX500": ["USD"],
            "BTCUSD": ["USD"], "ETHUSD": ["USD"],
        }
    )


@dataclass(frozen=True)
class RiskParams:
    """Statistical Risk Intelligence (additive, advisory). Percentages are
    percent-of-account risk-per-trade; drawdown thresholds are percent."""

    window: int = 50                 # rolling trade window
    risk_defensive: float = 0.25
    risk_normal: float = 0.50
    risk_aggressive: float = 0.75
    risk_max: float = 1.00
    risk_min: float = 0.25
    # DEFENSIVE triggers (any one)
    def_dd_pct: float = 2.0
    def_profit_factor: float = 1.10
    def_win_rate: float = 0.45
    # AGGRESSIVE triggers (all)
    agg_profit_factor: float = 1.75
    agg_win_rate: float = 0.60
    agg_min_trades: int = 30
    # Progressive drawdown levels (percent)
    dd_level1: float = 2.0   # reduce tier by one
    dd_level2: float = 3.0   # risk to minimum
    dd_level3: float = 4.0   # pause until next session
    dd_level4: float = 5.0   # compliance lockout
    expected_trades_per_month: int = 20  # for monthly-exposure estimate
    # Position sizing (TradeRouter). base_risk_pct is the statically configured
    # per-trade ceiling; the risk engine may only reduce/cap below it.
    base_risk_pct: float = 0.50
    contract_size: float = 100000.0  # units per standard lot (FX)


@dataclass(frozen=True)
class Config:
    thresholds: Thresholds = field(default_factory=Thresholds)
    weights: ComponentWeights = field(default_factory=ComponentWeights)
    orb: ORBParams = field(default_factory=ORBParams)
    indicators: IndicatorParams = field(default_factory=IndicatorParams)
    volatility: VolatilityParams = field(default_factory=VolatilityParams)
    strategies: StrategyParams = field(default_factory=StrategyParams)
    guards: GuardParams = field(default_factory=GuardParams)
    risk: RiskParams = field(default_factory=RiskParams)
    account_feed_ttl_seconds: int = 60  # sizing refuses if the live feed is older
    score_floor: float = 0.0
    score_ceiling: float = 100.0
    state_ttl_days: int = 3  # FIX 8 — prune ORB/session state older than this


DEFAULT_CONFIG = Config()
