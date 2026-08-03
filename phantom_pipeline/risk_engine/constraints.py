"""Risk budget constraints (ADR-005 §6-§14).

Each function here independently evaluates one constraint and returns
its own `allowed_risk_percent` — never a pick of one constraint over
another. `RiskEngine` (engine.py) takes the minimum across every
constraint's result (§6); it is the sole place that combination happens,
so no constraint here needs to know about any other.

Every function fails closed to `0.0` on missing or uncalculable input
(ADR-005 Hard Rules, §15) — never guessed, never defaulted to a
non-zero fallback.
"""

from __future__ import annotations

from typing import Optional, Tuple

from ..scanner.models import ScannerObservation
from .config import RiskEngineConfig
from .models import AccountState, ConstraintEvaluation


def _unevaluated(constraint: str, detail: str) -> ConstraintEvaluation:
    return ConstraintEvaluation(constraint, 0.0, False, detail)


def per_trade_ceiling(config: RiskEngineConfig) -> ConstraintEvaluation:
    """The configured, versioned hard upper bound (§7) — nothing else may
    push the awarded risk above it."""
    return ConstraintEvaluation(
        "PER_TRADE_CEILING", config.max_risk_percent_per_trade, False,
        f"ceiling={config.max_risk_percent_per_trade}%",
    )


def daily_budget(
    account_state: Optional[AccountState], config: RiskEngineConfig
) -> ConstraintEvaluation:
    """Remaining cumulative risk budget for the current period (§8)."""
    if account_state is None or account_state.daily_risk_allocated_pct is None:
        return _unevaluated("DAILY_BUDGET", "missing account state")

    remaining = config.max_daily_risk_percent - account_state.daily_risk_allocated_pct
    remaining = max(0.0, remaining)
    return ConstraintEvaluation(
        "DAILY_BUDGET", remaining, False,
        f"allocated={account_state.daily_risk_allocated_pct}% of {config.max_daily_risk_percent}%",
    )


def portfolio_heat(
    account_state: Optional[AccountState], config: RiskEngineConfig
) -> ConstraintEvaluation:
    """Remaining headroom under the aggregate open-position risk cap (§9)."""
    if account_state is None:
        return _unevaluated("PORTFOLIO_HEAT", "missing account state")

    heat = sum(p.allocated_risk_percent for p in account_state.open_positions)
    remaining = max(0.0, config.max_portfolio_heat_percent - heat)
    return ConstraintEvaluation(
        "PORTFOLIO_HEAT", remaining, False,
        f"heat={heat}% of {config.max_portfolio_heat_percent}%",
    )


def _currency_legs(symbol: str) -> Optional[Tuple[str, str]]:
    """A generic, currency-agnostic parse of a standard 6-character FX
    symbol into (base, quote). Anything else is not parseable."""
    if len(symbol) != 6 or not symbol.isalpha():
        return None
    return symbol[:3].upper(), symbol[3:].upper()


def currency_exposure(
    account_state: Optional[AccountState], symbol: str, config: RiskEngineConfig
) -> ConstraintEvaluation:
    """Remaining headroom under the per-currency exposure cap (§10) —
    sizing-only; the authoritative, blocking exposure gate remains
    Compliance Engine's (ADR-006)."""
    if account_state is None:
        return _unevaluated("CURRENCY_EXPOSURE", "missing account state")

    legs = _currency_legs(symbol)
    if legs is None:
        return _unevaluated("CURRENCY_EXPOSURE", f"cannot parse currency legs from {symbol!r}")

    exposure_by_currency = {legs[0]: 0.0, legs[1]: 0.0}
    for position in account_state.open_positions:
        position_legs = _currency_legs(position.symbol)
        if position_legs is None:
            # One unparseable open position makes the aggregate exposure
            # figure unreliable — fail closed rather than under-count.
            return _unevaluated(
                "CURRENCY_EXPOSURE", f"cannot parse currency legs from open position {position.symbol!r}"
            )
        for currency in position_legs:
            if currency in exposure_by_currency:
                exposure_by_currency[currency] += position.allocated_risk_percent

    tightest_remaining = min(
        max(0.0, config.max_currency_exposure_percent - exposure)
        for exposure in exposure_by_currency.values()
    )
    return ConstraintEvaluation(
        "CURRENCY_EXPOSURE", tightest_remaining, False,
        f"legs={legs}, exposure={exposure_by_currency}",
    )


def correlation_exposure(
    account_state: Optional[AccountState], symbol: str, config: RiskEngineConfig
) -> ConstraintEvaluation:
    """Zero if the candidate's own correlation bucket is unconfigured —
    never assumed safe (§11 Hard Rule). Otherwise a binary allow/zero
    based on the configured max positions per bucket."""
    if account_state is None:
        return _unevaluated("CORRELATION_EXPOSURE", "missing account state")

    bucket = config.correlation_bucket_for(symbol)
    if bucket is None:
        return _unevaluated("CORRELATION_EXPOSURE", f"no configured correlation bucket for {symbol!r}")

    same_bucket_count = sum(
        1 for p in account_state.open_positions if config.correlation_bucket_for(p.symbol) == bucket
    )
    if same_bucket_count >= config.max_positions_per_correlation_bucket:
        return ConstraintEvaluation(
            "CORRELATION_EXPOSURE", 0.0, False,
            f"bucket={bucket} open={same_bucket_count} >= max {config.max_positions_per_correlation_bucket}",
        )
    return ConstraintEvaluation(
        "CORRELATION_EXPOSURE", config.max_risk_percent_per_trade, False,
        f"bucket={bucket} open={same_bucket_count} < max {config.max_positions_per_correlation_bucket}",
    )


def volatility_adjustment(
    observation: ScannerObservation, config: RiskEngineConfig
) -> ConstraintEvaluation:
    """Reduces the ceiling under elevated/extreme or unknown volatility
    (§12) — reused directly from the Scanner's already-computed
    `volatility` fact, never recomputed."""
    label = observation.volatility.label.value
    multiplier = config.volatility_multiplier(label)
    allowed = config.max_risk_percent_per_trade * multiplier
    return ConstraintEvaluation(
        "VOLATILITY_ADJUSTMENT", allowed, False,
        f"label={label} multiplier={multiplier}",
    )


def loss_streak_adjustment(
    account_state: Optional[AccountState], config: RiskEngineConfig
) -> ConstraintEvaluation:
    """Reduces the ceiling as consecutive losses accumulate (§13)."""
    if account_state is None or account_state.consecutive_losses is None:
        return _unevaluated("LOSS_STREAK_ADJUSTMENT", "missing account state")

    multiplier = config.tier_multiplier(config.loss_streak_tiers, account_state.consecutive_losses)
    allowed = config.max_risk_percent_per_trade * multiplier
    return ConstraintEvaluation(
        "LOSS_STREAK_ADJUSTMENT", allowed, False,
        f"consecutive_losses={account_state.consecutive_losses} multiplier={multiplier}",
    )


def drawdown_scaling(
    account_state: Optional[AccountState], config: RiskEngineConfig
) -> ConstraintEvaluation:
    """Progressively tighter risk as drawdown increases (§14) — may scale
    an individual decision to zero; never the persistent, account-wide
    kill-switch (that authority belongs to Compliance Engine, ADR-006)."""
    if (
        account_state is None
        or account_state.daily_drawdown_pct is None
        or account_state.total_drawdown_pct is None
    ):
        return _unevaluated("DRAWDOWN_SCALING", "missing account state")

    worst_drawdown = max(account_state.daily_drawdown_pct, account_state.total_drawdown_pct)
    multiplier = config.tier_multiplier(config.drawdown_tiers, worst_drawdown)
    allowed = config.max_risk_percent_per_trade * multiplier
    return ConstraintEvaluation(
        "DRAWDOWN_SCALING", allowed, False,
        f"worst_drawdown={worst_drawdown}% multiplier={multiplier}",
    )
