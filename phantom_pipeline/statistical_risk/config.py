"""Versioned configuration for Statistical Risk Management (`ADR-022` §6).

Every threshold here is a tunable implementation default, never
architecture (`CLAUDE.md` §7, §3) — the same discipline every prior
stage's config module already establishes. This package deliberately
defines its own drawdown-limit/exposure tunables rather than importing
`risk_engine.config` — `risk_engine.config` is a private submodule of
another package and is not one of the allowed cross-package imports
(`.models`/`.trace`/`.registry`/`__init__.py`), so independent,
explicitly-configured limits here are the only architecturally-compliant
option, not a shortcut.
"""

from __future__ import annotations

from dataclasses import dataclass

STATISTICAL_RISK_VERSION = "1.0.0-phase1"


@dataclass(frozen=True)
class StatisticalRiskConfig:
    """`min_sample_size` gates every rolling/statistical computation
    (`ADR-022` Hard Rule 7) — fewer than this many closed trades and the
    corresponding field reports `None`, never an unreliable estimate from
    too small a sample.

    `monte_carlo_seed_base` is XOR-combined with a hash of the caller's
    `trace_id` to derive each run's actual seed (`monte_carlo.py`) — this
    keeps every run both deterministic (same `trace_id` + same trades +
    same config -> same seed -> same result) and distinct across
    different `trace_id`s, rather than reusing one fixed seed for every
    assessment.
    """

    rolling_window_trades: int = 30
    min_sample_size: int = 20
    monte_carlo_iterations: int = 1000
    monte_carlo_seed_base: int = 42
    monte_carlo_ruin_threshold_pct: float = 50.0
    risk_of_ruin_reduce_threshold: float = 0.05
    risk_of_ruin_skip_threshold: float = 0.15
    var_confidence_level: float = 0.95
    cvar_confidence_level: float = 0.95
    confidence_interval_level: float = 0.95
    daily_drawdown_limit_pct: float = 5.0
    total_drawdown_limit_pct: float = 10.0
    portfolio_heat_warning_pct: float = 4.0
    currency_exposure_warning_pct: float = 3.0
    position_concentration_warning_count: int = 2
    atr_period: int = 14
    volatility_lookback_bars: int = 20
    volatility_compressed_ratio: float = 0.7
    volatility_elevated_ratio: float = 1.3
    volatility_extreme_ratio: float = 2.0
    log_level: int = 20  # logging.INFO, without importing logging here


DEFAULT_CONFIG = StatisticalRiskConfig()
