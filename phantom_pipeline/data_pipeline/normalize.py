"""Normalization functions (ADR-013 §6).

Translation only, per ADR-015's Adapter Forbidden Responsibilities: no
function here decides which symbols are tradeable, what a price
"should" be, or anything resembling business/strategy/scoring/risk/
compliance logic. Each function is pure and raises on genuinely
malformed input rather than guessing — callers (ingest.py) catch that
and degrade to a MALFORMED-quality record, never propagate an exception
into the pipeline (ADR-002 §7's "must not raise on bad input" contract,
applied one stage earlier).
"""

from __future__ import annotations

from datetime import datetime, timezone

from .config import PipelineConfig


def normalize_symbol(raw_symbol: str, config: PipelineConfig) -> str:
    """Map a broker-specific symbol variant to Phantom's canonical identifier."""
    return config.symbol_aliases.get(raw_symbol, raw_symbol)


def normalize_timestamp(raw_timestamp: datetime) -> datetime:
    """Normalize a timestamp to canonical, timezone-aware UTC.

    Raises ValueError on a naive datetime rather than assuming a
    timezone — assuming UTC for an unlabeled timestamp would be a
    fabrication, never fail-closed inference.
    """
    if raw_timestamp.tzinfo is None:
        raise ValueError(f"naive timestamp not permitted: {raw_timestamp!r}")
    return raw_timestamp.astimezone(timezone.utc)


def normalize_price(raw_price: float, symbol: str, config: PipelineConfig) -> float:
    """Round a price to the symbol's configured canonical precision."""
    if raw_price is None or raw_price <= 0:
        raise ValueError(f"non-positive or missing price: {raw_price!r}")
    digits = config.price_precision_for(symbol)
    return round(raw_price, digits)


def normalize_volume(raw_volume: float, config: PipelineConfig) -> float:
    """Round a volume to the configured canonical precision."""
    if raw_volume is None or raw_volume < 0:
        raise ValueError(f"negative or missing volume: {raw_volume!r}")
    return round(raw_volume, config.volume_precision_digits)
