"""Portfolio exposure computation: heat, currency/symbol/sector
exposure, long/short/net exposure, pending reservation totals.

Reads `PortfolioState` (caller-supplied, §0a of ADR-027) plus this
engine's own `ReservationLedger` -- never fetches either from the
Bridge or anywhere else.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, Optional, Tuple

from .models import DataQuality, Direction, ExposureSummary, OpenPosition, PortfolioState
from .reservation import Reservation


def split_currency_pair(pair: str) -> Tuple[str, str]:
    """`"EURUSD"` -> `("EUR", "USD")`. A plain string utility, not a
    market calculation -- every 6-letter Forex symbol splits this way."""

    return pair[:3].upper(), pair[3:6].upper()


def compute_exposure_summary(
    portfolio_state: Optional[PortfolioState],
    pending_reservations: Tuple[Reservation, ...],
) -> ExposureSummary:
    positions: Tuple[OpenPosition, ...] = portfolio_state.open_positions if portfolio_state is not None else ()
    data_quality = DataQuality.KNOWN if portfolio_state is not None else DataQuality.UNKNOWN

    long_exposure = sum(p.size_r for p in positions if p.direction is Direction.LONG)
    short_exposure = sum(p.size_r for p in positions if p.direction is Direction.SHORT)
    net_exposure = long_exposure - short_exposure

    currency_totals: Dict[str, float] = defaultdict(float)
    symbol_totals: Dict[str, float] = defaultdict(float)
    for position in positions:
        signed = position.size_r if position.direction is Direction.LONG else -position.size_r
        base, quote = split_currency_pair(position.pair)
        currency_totals[base] += signed
        currency_totals[quote] -= signed
        symbol_totals[position.pair] += position.size_r

    pending_total = sum(r.risk_r for r in pending_reservations)
    for reservation in pending_reservations:
        symbol_totals[reservation.pair] += reservation.risk_r

    portfolio_heat = sum(p.size_r for p in positions) + pending_total

    return ExposureSummary(
        portfolio_heat_r=portfolio_heat,
        long_exposure_r=long_exposure,
        short_exposure_r=short_exposure,
        net_exposure_r=net_exposure,
        currency_exposure_r=tuple(sorted(currency_totals.items())),
        symbol_exposure_r=tuple(sorted(symbol_totals.items())),
        sector_exposure_r=(),  # future-ready placeholder -- no sector taxonomy exists yet
        pending_reservation_total_r=pending_total,
        data_quality=data_quality,
    )


__all__ = ["split_currency_pair", "compute_exposure_summary"]
