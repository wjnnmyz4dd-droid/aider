"""Shared data types and enumerations for the Phantom pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional


class Regime(str, Enum):
    """Output of the regime engine."""

    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    BREAKOUT = "BREAKOUT"
    RANGING = "RANGING"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    NEUTRAL = "NEUTRAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"  # warmup — not a tradeable regime


class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NONE = "NONE"


class NewsState(str, Enum):
    SAFE = "SAFE"
    DANGER = "DANGER"  # inside a high-impact news window


class Decision(str, Enum):
    APPROVE = "APPROVE"
    WATCHLIST = "WATCHLIST"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class Candle:
    """A single OHLCV bar. ``ts`` is timezone-aware (UTC)."""

    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class MarketSnapshot:
    """Everything the pipeline needs to score one symbol at one instant.

    ``candles`` maps a timeframe label ("M15", "H1", "H4", "D1") to a list of
    bars ordered oldest→newest. The execution timeframe is configurable
    (default M15) and is what the ORB layer consumes.
    """

    symbol: str
    now: datetime  # tz-aware UTC "current time"
    candles: Dict[str, List[Candle]]
    spread: float = 0.0  # current spread in price units
    # Optional context the guards consume; sensible defaults keep tests simple.
    open_positions: Dict[str, Direction] = field(default_factory=dict)
    news_windows: List["NewsWindow"] = field(default_factory=list)
    account_drawdown_pct: float = 0.0  # legacy daily-drawdown scalar (fallback)
    # Richer risk inputs (optional; guards fall back to the legacy fields above
    # when these are not supplied, preserving behaviour).
    equity: Optional[float] = None                       # live account equity
    position_counts: Dict[str, int] = field(default_factory=dict)      # symbol -> open count
    symbol_exposure_pct: Dict[str, float] = field(default_factory=dict)  # symbol -> % of equity

    def tf(self, timeframe: str) -> List[Candle]:
        return self.candles.get(timeframe, [])


@dataclass(frozen=True)
class NewsWindow:
    """A high-impact news blackout window for a currency."""

    currency: str  # e.g. "USD"
    start: datetime
    end: datetime
    impact: str = "HIGH"


@dataclass
class ScoreComponent:
    """One contribution to the composite score.

    ``points`` is added to the running total. ``blocking`` components, when
    they fail, force the final decision to BLOCK regardless of the total.
    """

    name: str
    points: float
    detail: str = ""
    blocking: bool = False
    failed: bool = False  # only meaningful for blocking components

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "points": round(self.points, 2),
            "detail": self.detail,
            "blocking": self.blocking,
            "failed": self.failed,
        }


@dataclass
class ScoreResult:
    symbol: str
    total: float
    decision: Decision
    direction: Direction
    components: List[ScoreComponent]
    capped_at: Optional[float] = None
    orb: Optional["ORBDecision"] = None
    thesis: str = ""  # Trade Thesis Summary — informational only, never scored
    strategies: Optional[dict] = None  # consolidated multi-strategy breakdown
    data_quality_flag: bool = False    # True during warmup / insufficient data

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "total": round(self.total, 2),
            "decision": self.decision.value,
            "direction": self.direction.value,
            "capped_at": self.capped_at,
            "components": [c.as_dict() for c in self.components],
            "orb": self.orb.as_dict() if self.orb else None,
            "thesis": self.thesis,
            "strategies": self.strategies,
            "data_quality_flag": self.data_quality_flag,
        }


# Imported lazily by annotation only; defined in orb.py.
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .orb import ORBDecision
