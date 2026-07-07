"""Dynamic portfolio heat, position concentration, and currency exposure
analysis (`ADR-022` §1, capabilities 16-18).

Reuses `risk_engine.models.OpenPosition`/`AccountState` verbatim (`ADR-022`
§2) — the same objects `RiskEngine.decide()` itself receives, so this
package's view of "what's open" can never drift from the Risk Engine's
own view. Currency exposure is derived from the standard six-letter FX
symbol convention (`base` = first 3 characters, `quote` = last 3) when a
symbol matches it; a symbol that does not (an index, a commodity, a
non-standard ticker) is grouped under its own raw symbol name instead of
being guessed at — an honest fallback, never a fabricated currency pair.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Dict, Sequence, Tuple

from ..risk_engine.models import OpenPosition
from .config import DEFAULT_CONFIG, StatisticalRiskConfig
from .models import RiskRecommendation


def portfolio_heat(open_positions: Sequence[OpenPosition]) -> float:
    """Sum of every open position's allocated risk percent — the same
    "portfolio heat" concept `risk_engine.constraints.portfolio_heat`
    already gates a live decision with; this is a read-only recomputation
    over the identical input type for advisory/reporting purposes only."""
    return sum(position.allocated_risk_percent for position in open_positions)


def recommendation_for_portfolio_heat(
    heat_percent: float, config: StatisticalRiskConfig = DEFAULT_CONFIG
) -> RiskRecommendation:
    if heat_percent >= config.portfolio_heat_warning_pct * 2:
        return RiskRecommendation.SKIP_HIGH_RISK
    if heat_percent >= config.portfolio_heat_warning_pct:
        return RiskRecommendation.REDUCE_RISK_25
    return RiskRecommendation.NORMAL_RISK


def position_concentration(open_positions: Sequence[OpenPosition]) -> Dict[str, int]:
    """Open-position count per symbol — flags a single symbol carrying
    more than one open position (never gated here; reporting only)."""
    return dict(Counter(position.symbol for position in open_positions))


def _currency_pair(symbol: str) -> Tuple[str, ...]:
    if len(symbol) == 6 and symbol.isalpha():
        return (symbol[:3].upper(), symbol[3:6].upper())
    return (symbol,)


def currency_exposure(open_positions: Sequence[OpenPosition]) -> Dict[str, float]:
    """Allocated risk percent summed per currency, using the standard
    six-letter FX symbol convention; a non-matching symbol is grouped
    under its own raw name rather than guessed at."""
    exposure: Dict[str, float] = defaultdict(float)
    for position in open_positions:
        for currency in _currency_pair(position.symbol):
            exposure[currency] += position.allocated_risk_percent
    return dict(exposure)


def recommendation_for_currency_exposure(
    exposure: Dict[str, float], config: StatisticalRiskConfig = DEFAULT_CONFIG
) -> RiskRecommendation:
    if any(value >= config.currency_exposure_warning_pct * 2 for value in exposure.values()):
        return RiskRecommendation.REDUCE_RISK_50
    if any(value >= config.currency_exposure_warning_pct for value in exposure.values()):
        return RiskRecommendation.REDUCE_RISK_25
    return RiskRecommendation.NORMAL_RISK


__all__ = [
    "portfolio_heat",
    "recommendation_for_portfolio_heat",
    "position_concentration",
    "currency_exposure",
    "recommendation_for_currency_exposure",
]
