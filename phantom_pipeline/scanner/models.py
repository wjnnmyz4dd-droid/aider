"""Scanner output objects (ADR-002 §5, §8, Amendment 1).

Every object here is an immutable (frozen) dataclass, carries
`schema_version`, and — for `ScannerObservation` itself — a deterministic
`trace_id`. No field anywhere in this module is capable of representing a
score, decision, size, or approval (ADR-002 §3, §6, §8's type-level
guarantee) — see tests/phantom_pipeline/scanner/test_scanner.py's
`TestBoundaryTypeLevel` for the enforcement test.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Mapping, Optional, Tuple

SCHEMA_VERSION = 1


class Direction(Enum):
    """A factual directional label — never a trade instruction."""

    UP = "UP"
    DOWN = "DOWN"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"


class DataQualityFlag(Enum):
    """Top-level observation quality flag (ADR-002 §9, §10). Order mirrors
    §9's own listing; `quality.py` checks in this order."""

    NOMINAL = "NOMINAL"
    WARM_UP = "WARM_UP"
    MISSING_TIMEFRAME = "MISSING_TIMEFRAME"
    STALE_SPREAD = "STALE_SPREAD"
    MALFORMED_DATA = "MALFORMED_DATA"
    SESSION_AMBIGUOUS = "SESSION_AMBIGUOUS"
    SYMBOL_NOT_RECOGNIZED = "SYMBOL_NOT_RECOGNIZED"
    MARKET_NOT_TRADEABLE = "MARKET_NOT_TRADEABLE"


class VolatilityLabel(Enum):
    COMPRESSED = "COMPRESSED"
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    EXTREME = "EXTREME"
    UNKNOWN = "UNKNOWN"


class StructureKind(Enum):
    """Generic, playbook-agnostic structural signal kinds (ADR-002 §6)."""

    BOS = "BOS"
    CHOCH = "CHOCH"
    FVG = "FVG"
    ORDER_BLOCK = "ORDER_BLOCK"
    SUPPORT = "SUPPORT"
    RESISTANCE = "RESISTANCE"


class SwingKind(Enum):
    HIGH = "HIGH"
    LOW = "LOW"


class SwingSequenceType(Enum):
    """The classified HH/HL vs LH/LL sequence type (ADR-002 §5 Amendment 1)."""

    HIGHER_HIGHS_HIGHER_LOWS = "HIGHER_HIGHS_HIGHER_LOWS"
    LOWER_HIGHS_LOWER_LOWS = "LOWER_HIGHS_LOWER_LOWS"
    MIXED = "MIXED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    UNKNOWN = "UNKNOWN"


class RangeStructure(Enum):
    EXPANSION = "EXPANSION"
    COMPRESSION = "COMPRESSION"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"


class MarketPhase(Enum):
    ACCUMULATION = "ACCUMULATION"
    MARKUP = "MARKUP"
    DISTRIBUTION = "DISTRIBUTION"
    MARKDOWN = "MARKDOWN"
    UNDEFINED = "UNDEFINED"
    UNKNOWN = "UNKNOWN"


class StructureConfidence(Enum):
    """A qualitative label only — never a numeric confidence score
    (ADR-002 §5 Amendment 1, §18)."""

    CLEAR = "CLEAR"
    AMBIGUOUS = "AMBIGUOUS"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class TrendReading:
    """Per-timeframe direction and strength (ADR-002 §5). `strength` is a
    relative magnitude (EMA separation as a fraction of price), never a
    score — it describes the trend itself, not a trade's merit."""

    direction: Direction
    strength: Optional[float]


@dataclass(frozen=True)
class StructuralSignal:
    """Mirrors the shape of `phantom/structure.py`'s `StructureSignal` as an
    idea, not as an authoritative type (ADR-002 §8)."""

    kind: StructureKind
    direction: Direction
    detail: str


@dataclass(frozen=True)
class VolatilityState:
    label: VolatilityLabel
    ratio: Optional[float]


@dataclass(frozen=True)
class SessionState:
    """`window_position` is the fraction (0.0-1.0) elapsed through the first
    active session's window, or `None` when no session is active."""

    active_sessions: Tuple[str, ...]
    window_position: Optional[float]


@dataclass(frozen=True)
class LiquidityEvent:
    kind: str
    direction: Direction
    price: Optional[float]


@dataclass(frozen=True)
class SwingPoint:
    """One entry in the swing hierarchy (ADR-002 §5 Amendment 1).
    `is_major` classifies external (major) vs internal (minor) structure
    from the same single swing-pivot pass — never a second pass at a
    different lookback (ADR-002 §13)."""

    index: int
    timestamp: datetime
    price: float
    kind: SwingKind
    is_major: bool


@dataclass(frozen=True)
class EqualLevel:
    kind: SwingKind
    price: float
    swing_count: int


@dataclass(frozen=True)
class StructureTrendState:
    """External or internal structure — a trend-like reading derived from
    the major or minor swing sequence respectively (ADR-002 §5 Amendment 1)."""

    direction: Direction
    sequence: SwingSequenceType


@dataclass(frozen=True)
class ScannerObservation:
    """The Scanner's sole output type (ADR-002 §5, §8). One instance per
    symbol per call. Every field is a fact; none may represent a score,
    decision, size, or approval."""

    schema_version: int
    trace_id: str
    symbol: str
    timestamp: datetime
    trend: Mapping[str, TrendReading]
    structure: Tuple[StructuralSignal, ...]
    volatility: VolatilityState
    session: SessionState
    liquidity_events: Tuple[LiquidityEvent, ...]
    data_quality_flag: DataQualityFlag

    # Amendment 1
    external_structure: StructureTrendState
    internal_structure: StructureTrendState
    swing_hierarchy: Tuple[SwingPoint, ...]
    equal_highs: Tuple[EqualLevel, ...]
    equal_lows: Tuple[EqualLevel, ...]
    range_structure: RangeStructure
    phase: MarketPhase
    trend_acceleration: Optional[bool]
    trend_exhaustion: Optional[bool]
    structure_confidence: StructureConfidence

    def __post_init__(self) -> None:
        object.__setattr__(self, "trend", MappingProxyType(dict(self.trend)))
        object.__setattr__(self, "structure", tuple(self.structure))
        object.__setattr__(self, "liquidity_events", tuple(self.liquidity_events))
        object.__setattr__(self, "swing_hierarchy", tuple(self.swing_hierarchy))
        object.__setattr__(self, "equal_highs", tuple(self.equal_highs))
        object.__setattr__(self, "equal_lows", tuple(self.equal_lows))
