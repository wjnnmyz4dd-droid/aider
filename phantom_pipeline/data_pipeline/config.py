"""Versioned configuration for the Data Pipeline (ADR-013).

Every numeric threshold here is a tunable implementation default, never
architecture. ADR-013 itself defers exact numeric budgets to real
implementation measurement (its own §16, "Remaining Risks"); these
defaults are placeholders subject to empirical tuning, not invented
thresholds presented as final (CLAUDE.md §7, §3 — no magic numbers
buried in logic, every threshold named and configurable here instead).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass(frozen=True)
class PipelineConfig:
    # Ingestion (ADR-013 §6)
    duplicate_tick_history: int = 64
    out_of_order_tolerance_seconds: float = 1.0

    # Normalization (ADR-013 §6)
    symbol_aliases: Dict[str, str] = field(default_factory=dict)
    default_price_precision_digits: int = 5
    price_precision_digits: Dict[str, int] = field(default_factory=dict)
    volume_precision_digits: int = 2

    # Bar construction / multi-timeframe aggregation (ADR-013 §2)
    timeframe_seconds: Dict[str, int] = field(
        default_factory=lambda: {
            "M1": 60,
            "M5": 300,
            "M15": 900,
            "H1": 3600,
            "H4": 14400,
            "D1": 86400,
        }
    )

    # Historical cache (ADR-013 §11)
    historical_cache_max_bars_per_series: int = 5000
    historical_cache_ttl_seconds: float = 24 * 3600.0

    # Data quality (ADR-013 §7)
    freshness_stale_after_seconds: float = 120.0

    def price_precision_for(self, symbol: str) -> int:
        return self.price_precision_digits.get(symbol, self.default_price_precision_digits)

    def interval_seconds_for(self, timeframe: str) -> int:
        try:
            return self.timeframe_seconds[timeframe]
        except KeyError as exc:
            raise ValueError(f"unconfigured timeframe: {timeframe!r}") from exc


DEFAULT_CONFIG = PipelineConfig()
