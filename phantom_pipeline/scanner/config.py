"""Versioned configuration for the Scanner (ADR-002).

Every numeric threshold here is a tunable implementation default, never
architecture. ADR-002 §13 itself defers exact numeric budgets to real
implementation measurement ("Phase 2, per ADR-001"); these defaults are
placeholders subject to empirical tuning, not invented thresholds
presented as final (`CLAUDE.md` §7, §3 — no magic numbers buried in
logic, every threshold named and configurable here instead).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Tuple

SCANNER_VERSION = "1.0.0-phase1"


@dataclass(frozen=True)
class SessionWindow:
    """A named session's daily time-of-day window, in UTC-of-day terms
    (hour, minute), inclusive start, exclusive end. Does not itself
    handle daylight-saving transitions in the venue's local time — a
    known limitation, see the Scanner's own docstring."""

    name: str
    start_hour: int
    start_minute: int
    end_hour: int
    end_minute: int


@dataclass(frozen=True)
class ScannerConfig:
    """This stage's execution model is single-threaded, matching the
    Data Pipeline's own documented constraint (`phantom_pipeline.
    data_pipeline.ingest`) — no field here implies or requires
    concurrency safety."""

    # Swing / structure detection (ADR-002 §5, §13)
    swing_lookback: int = 2
    equal_level_tolerance_pct: float = 0.0005  # 0.05%, a placeholder default
    major_swing_atr_multiple: float = 1.5  # a swing is "major" (external
    # structure) if its range exceeds this many ATRs — Amendment 1's
    # external/internal structure split, derived from the same swing list
    # and the same ATR value trend.py/volatility.py already computed,
    # never a second swing pass at a different lookback.

    # Trend (ADR-002 §5)
    ema_fast_period: int = 20
    ema_slow_period: int = 50
    trend_strength_flat_threshold: float = 0.0005

    # Volatility (ADR-002 §5)
    atr_period: int = 14
    atr_baseline_period: int = 50
    volatility_compressed_ratio: float = 0.6
    volatility_elevated_ratio: float = 1.4
    volatility_extreme_ratio: float = 2.0

    # Warm-up minimums (ADR-002 §9)
    min_bars_for_trend: int = 51  # ema_slow_period + 1
    min_bars_for_structure: int = 20
    min_swings_for_phase: int = 4  # Amendment 1 §9's distinct warm-up class

    # Data quality (ADR-002 §9)
    spread_stale_after_seconds: float = 120.0
    max_spread: float = 0.05  # a generous placeholder ceiling, not a real spec

    # Session windows (ADR-002 §5) — a minimal, illustrative default set;
    # real venue session hours are a configuration concern of the caller,
    # not architecture (ADR-002 §4).
    session_windows: Tuple[SessionWindow, ...] = (
        SessionWindow("SYDNEY", 21, 0, 6, 0),
        SessionWindow("TOKYO", 0, 0, 9, 0),
        SessionWindow("LONDON", 7, 0, 16, 0),
        SessionWindow("NEW_YORK", 12, 0, 21, 0),
    )

    # Symbol registry (ADR-002 §9's "symbol not recognized" failure mode)
    recognized_symbols: Mapping[str, bool] = field(default_factory=dict)

    # Logging (ADR-002 §11)
    log_level: int = 20  # logging.INFO, without importing logging here

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "recognized_symbols", MappingProxyType(dict(self.recognized_symbols))
        )

    def is_symbol_recognized(self, symbol: str) -> bool:
        # An empty registry means "no restriction configured" — every
        # symbol is recognized. A non-empty registry is an explicit
        # allow-list.
        if not self.recognized_symbols:
            return True
        return bool(self.recognized_symbols.get(symbol, False))


DEFAULT_CONFIG = ScannerConfig()
