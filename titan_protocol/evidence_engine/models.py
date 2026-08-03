"""Data models for the Evidence Engine (Phase 2A).

Every type here is either a plain, immutable record of an observed
market fact (a `Bar`, a `SwingPoint`, a `StructureEvent`) or a scored
evaluation of one (`ComponentScore`, `EvidenceScore`). Nothing here is a
trade decision: there is no `BUY`/`SELL` enum, no position size, no stop
loss / take profit anywhere in this module, by design (see
`docs/adr/ADR-024-evidence-engine.md` Hard Rule 1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Optional, Tuple

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Bar(object):
    """One OHLC candle. The sole raw input to every evidence
    computation in this package."""

    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


# -- Market structure -------------------------------------------------


class SwingType(Enum):
    HIGH = "HIGH"
    LOW = "LOW"


@dataclass(frozen=True)
class SwingPoint:
    """A confirmed local extreme -- confirmed means bars exist on both
    sides that are less extreme, per `structure.py`'s fixed lookback
    rule. Never revised once emitted for a given bar series."""

    swing_type: SwingType
    index: int
    timestamp: datetime
    price: float


class StructureEventType(Enum):
    BOS_INTERNAL = "BOS_INTERNAL"
    BOS_EXTERNAL = "BOS_EXTERNAL"
    CHOCH = "CHOCH"


class StructureDirection(Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"


@dataclass(frozen=True)
class StructureEvent:
    """A Break of Structure or Change of Character, anchored to the
    swing point it broke and the bar index at which the break was
    confirmed."""

    event_type: StructureEventType
    direction: StructureDirection
    broken_swing: SwingPoint
    confirmed_index: int
    confirmed_price: float


class TrendClassification(Enum):
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGE = "RANGE"
    COMPRESSION = "COMPRESSION"
    EXPANSION = "EXPANSION"
    REVERSAL = "REVERSAL"


@dataclass(frozen=True)
class PriceLevel:
    """A support or resistance level -- a price the market has
    respected more than once, never a single-touch line."""

    price: float
    touches: int
    first_index: int
    last_index: int


@dataclass(frozen=True)
class MarketStructureResult:
    swings: Tuple[SwingPoint, ...]
    events: Tuple[StructureEvent, ...]
    trend: TrendClassification
    support_levels: Tuple[PriceLevel, ...]
    resistance_levels: Tuple[PriceLevel, ...]


# -- Liquidity ----------------------------------------------------------


@dataclass(frozen=True)
class EqualLevel:
    """A cluster of swing highs (or lows) within tolerance of one
    another -- the raw material a liquidity pool sits on."""

    swing_type: SwingType
    price: float
    indices: Tuple[int, ...]


@dataclass(frozen=True)
class LiquidityPool:
    """A resting-liquidity zone: an equal-level cluster the market has
    not yet swept."""

    swing_type: SwingType
    price: float
    indices: Tuple[int, ...]
    swept: bool


@dataclass(frozen=True)
class LiquiditySweep:
    """A wick through a liquidity pool's price that closes back on the
    origin side -- the defining shape of a stop hunt, distinguished from
    a genuine breakout by the close location, never by intent."""

    pool: LiquidityPool
    sweep_index: int
    sweep_price: float
    closed_back_inside: bool
    is_stop_hunt: bool
    is_trap: bool
    displacement_follow_through: bool


@dataclass(frozen=True)
class LiquidityResult:
    pools: Tuple[LiquidityPool, ...]
    sweeps: Tuple[LiquiditySweep, ...]


# -- Candlesticks ---------------------------------------------------------


class CandlestickPattern(Enum):
    HAMMER = "HAMMER"
    HANGING_MAN = "HANGING_MAN"
    SHOOTING_STAR = "SHOOTING_STAR"
    DOJI = "DOJI"
    MARUBOZU = "MARUBOZU"
    SPINNING_TOP = "SPINNING_TOP"
    BULLISH_ENGULFING = "BULLISH_ENGULFING"
    BEARISH_ENGULFING = "BEARISH_ENGULFING"
    HARAMI = "HARAMI"
    PIERCING_PATTERN = "PIERCING_PATTERN"
    DARK_CLOUD_COVER = "DARK_CLOUD_COVER"
    TWEEZER_TOP = "TWEEZER_TOP"
    TWEEZER_BOTTOM = "TWEEZER_BOTTOM"
    MORNING_STAR = "MORNING_STAR"
    EVENING_STAR = "EVENING_STAR"
    THREE_WHITE_SOLDIERS = "THREE_WHITE_SOLDIERS"
    THREE_BLACK_CROWS = "THREE_BLACK_CROWS"
    THREE_INSIDE_UP = "THREE_INSIDE_UP"
    THREE_INSIDE_DOWN = "THREE_INSIDE_DOWN"
    THREE_OUTSIDE_UP = "THREE_OUTSIDE_UP"
    THREE_OUTSIDE_DOWN = "THREE_OUTSIDE_DOWN"


class PatternContext(Enum):
    """Where the pattern occurred relative to the recent trend -- a
    reversal-shaped pattern found at a trend extreme is contextually
    stronger than the same shape found mid-range."""

    AT_UPTREND_EXTREME = "AT_UPTREND_EXTREME"
    AT_DOWNTREND_EXTREME = "AT_DOWNTREND_EXTREME"
    MID_RANGE = "MID_RANGE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class CandlestickMatch:
    pattern: CandlestickPattern
    index: int
    quality: float  # 0-1, shape-fidelity to the pattern's textbook definition
    context: PatternContext
    confidence: float  # 0-1, quality combined with context


# -- Volatility -----------------------------------------------------------


@dataclass(frozen=True)
class VolatilityState:
    atr: float
    is_expansion: bool
    is_compression: bool
    volatility_score: float  # 0-100


# -- Session --------------------------------------------------------------


class SessionName(Enum):
    ASIAN = "ASIAN"
    LONDON = "LONDON"
    LONDON_NEW_YORK_OVERLAP = "LONDON_NEW_YORK_OVERLAP"
    EARLY_NEW_YORK = "EARLY_NEW_YORK"
    LATE_NEW_YORK = "LATE_NEW_YORK"
    CLOSED = "CLOSED"


@dataclass(frozen=True)
class SessionState:
    session: SessionName
    quality_score: float  # 0-100


# -- Indicators -------------------------------------------------------------


@dataclass(frozen=True)
class IndicatorResult:
    name: str
    value: float
    parameters: Tuple[Tuple[str, float], ...]


# -- Scoring ------------------------------------------------------------


@dataclass(frozen=True)
class ComponentScore:
    """One of the seven independent inputs to the composite
    `EvidenceScore`. `reason`/`weight`/`confidence` are mandatory on
    every instance -- there is no code path that produces a
    `ComponentScore` without all three (see ADR-024 Hard Rule 3)."""

    name: str
    value: float  # 0-100
    weight: float  # 0-1, this component's contribution to the composite
    confidence: float  # 0-1
    reason: str


@dataclass(frozen=True)
class EvidenceScore:
    composite: float  # 0-100
    components: Tuple[ComponentScore, ...]


@dataclass(frozen=True)
class EvidenceReport:
    symbol: str
    generated_at: datetime
    score: EvidenceScore
    strengths: Tuple[str, ...]
    weaknesses: Tuple[str, ...]
    confidence_explanation: str


@dataclass(frozen=True)
class PairRanking:
    symbol: str
    rank: int  # 1 = highest score
    score: float


# -- Support/resistance context (Amendment 1) --------------------------------


@dataclass(frozen=True)
class PsychologicalLevel:
    """A round-number price level -- traders cluster orders around
    these regardless of any structural swing."""

    price: float
    distance_pct: float  # 0-100+, distance from the current price


@dataclass(frozen=True)
class ConfluenceZone:
    """A price zone where two or more independent S/R sources agree."""

    price: float
    sources: Tuple[str, ...]
    confluence_score: float  # 0-100


@dataclass(frozen=True)
class SupportResistanceContext:
    """Every support/resistance fact a downstream consumer (e.g. a
    future Strategy Engine) is required to have access to, beyond the
    plain structural support/resistance levels already in
    `MarketStructureResult`."""

    previous_day_high: Optional[float]
    previous_day_low: Optional[float]
    previous_week_high: Optional[float]
    previous_week_low: Optional[float]
    previous_month_high: Optional[float]
    previous_month_low: Optional[float]
    session_high: float
    session_low: float
    psychological_levels: Tuple[PsychologicalLevel, ...]
    confluence_zones: Tuple[ConfluenceZone, ...]
    break_quality_score: float  # 0-100
    false_break_probability: float  # 0-1


@dataclass(frozen=True)
class FairValueGap:
    """(Amendment 2) A 3-candle price imbalance: candle 1 and candle 3
    never overlap, leaving a gap most of candle 2's range created.
    `filled` is true once any later bar has traded back into the gap
    zone."""

    direction: StructureDirection
    start_index: int  # candle 1
    end_index: int  # candle 3
    gap_high: float
    gap_low: float
    filled: bool
    fill_index: Optional[int]


@dataclass(frozen=True)
class OpeningRangeBarObservation:
    """(ADR-024 Amendment 4) One closed, contiguous, completed bar
    following an opening range's own `range_end` -- a pure factual OHLC
    observation, never a breakout/direction/qualification decision.
    `index` is sequence-relative to the `bars` argument of the one
    `EvidenceEngine.evaluate_snapshot()` call that produced it -- not a
    globally stable identity, and not comparable across separate calls.
    `timestamp` (bar-open time) supplies this observation's own temporal
    identity only within that same call's enclosing symbol context;
    `symbol` is deliberately not duplicated here, matching
    `OpeningRangeState`'s and `FairValueGap`'s own convention of relying
    on the enclosing snapshot for it."""

    index: int
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class OpeningRangeState:
    """(ADR-035 §3, Phase 0 -- ADR-024 Amendment 2) A fixed-width price
    range anchored to a configured session-open time. `session` is
    descriptive only -- the identifying key is this instance's own
    `range_start`/`range_end` window, never `session` alone (two
    configured anchors can share a `SessionName`)."""

    session: SessionName
    range_start: datetime
    range_end: datetime
    range_start_index: int  # first included bar's position in the `bars` sequence `_analyze()` received
    range_end_index: int  # exclusive upper bound, same index space as FairValueGap.start_index/end_index
    range_high: float
    range_low: float
    range_midpoint: float
    is_formed: bool  # True once range_end has fully elapsed relative to `now`
    is_valid: bool  # False on insufficient bar count or a detected temporal gap
    post_range_bars: Tuple[OpeningRangeBarObservation, ...] = ()
    """(ADR-024 Amendment 4) The bounded, chronological, contiguous
    prefix of completed bars immediately following `range_end_index`.
    The first entry's `timestamp` must equal `range_end` exactly (no
    tolerance, no forward search); every subsequent entry's `timestamp`
    must equal the previous entry's `timestamp` plus
    `EvidenceEngineConfig.expected_bar_interval_seconds` exactly. A
    continuity failure or an incomplete candidate stops extraction --
    never skip-and-resume. Bounded by
    `EvidenceEngineConfig.opening_range_post_range_bar_window`."""


@dataclass(frozen=True)
class EvidenceSnapshot:
    """(Amendment 1) The raw facts behind an `EvidenceReport` -- every
    intermediate analysis result `evaluate()` already computes
    internally, exposed additively so a downstream consumer never has
    to recompute structure/liquidity/candlestick facts itself. `report`
    is the exact same `EvidenceReport` `evaluate()` would return for the
    same bars -- nothing here is a second, divergent computation."""

    report: EvidenceReport
    structure: MarketStructureResult
    liquidity: LiquidityResult
    candlesticks: Tuple[CandlestickMatch, ...]
    volatility: VolatilityState
    session: SessionState
    support_resistance: SupportResistanceContext
    fair_value_gaps: Tuple[FairValueGap, ...] = ()
    opening_ranges: Tuple[OpeningRangeState, ...] = ()


__all__ = [
    "SCHEMA_VERSION",
    "Bar",
    "SwingType",
    "SwingPoint",
    "StructureEventType",
    "StructureDirection",
    "StructureEvent",
    "TrendClassification",
    "PriceLevel",
    "MarketStructureResult",
    "EqualLevel",
    "LiquidityPool",
    "LiquiditySweep",
    "LiquidityResult",
    "CandlestickPattern",
    "PatternContext",
    "CandlestickMatch",
    "VolatilityState",
    "SessionName",
    "SessionState",
    "IndicatorResult",
    "ComponentScore",
    "EvidenceScore",
    "EvidenceReport",
    "PairRanking",
    "PsychologicalLevel",
    "ConfluenceZone",
    "SupportResistanceContext",
    "FairValueGap",
    "OpeningRangeBarObservation",
    "OpeningRangeState",
    "EvidenceSnapshot",
]
