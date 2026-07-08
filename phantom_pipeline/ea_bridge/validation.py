"""Transport-integrity validation (`ADR-023` §3, §6).

Every function here defends the *relay* between Python and the MQL5 EA
from being corrupted, replayed, or spoofed — none of them re-decide a
trade. Each takes plain values and returns `Optional[str]` (a reason
string, or `None` meaning the check passed) — the same "value in,
reason-or-None out" convention `execution_validator.checks` already
established for its own Phantom-side checks.
"""

from __future__ import annotations

import hmac
from datetime import datetime
from typing import Optional

from ..scanner.models import Direction
from .config import EABridgeConfig


def check_api_key(provided_key: Optional[str], config: EABridgeConfig) -> Optional[str]:
    if provided_key is None:
        return "missing_api_key"
    if not hmac.compare_digest(provided_key, config.api_key):
        return "invalid_api_key"
    return None


def check_magic_number(magic_number: int, config: EABridgeConfig) -> Optional[str]:
    if magic_number != config.magic_number:
        return "magic_number_mismatch"
    return None


def check_symbol_allowed(symbol: Optional[str], config: EABridgeConfig) -> Optional[str]:
    if symbol is None:
        return None
    if symbol not in config.allowed_symbols:
        return "symbol_not_allowed"
    return None


def check_volume(lot_size: Optional[float], config: EABridgeConfig) -> Optional[str]:
    if lot_size is None:
        return None
    if lot_size <= 0:
        return "invalid_volume"
    if lot_size > config.max_lot_size:
        return "volume_exceeds_max"
    return None


def check_stop_loss_take_profit(
    stop_loss: Optional[float], take_profit: Optional[float]
) -> Optional[str]:
    if stop_loss is not None and stop_loss <= 0:
        return "invalid_stop_loss"
    if take_profit is not None and take_profit <= 0:
        return "invalid_take_profit"
    return None


def check_directional_sanity(
    direction: Optional[Direction],
    stop_loss: Optional[float],
    take_profit: Optional[float],
    reference_price: Optional[float],
) -> Optional[str]:
    """Only checked when a recent reference price for the symbol is
    already known — never validated against a fabricated price
    (`ADR-023` §3)."""
    if reference_price is None or direction is None:
        return None
    if direction == Direction.UP:
        if stop_loss is not None and stop_loss >= reference_price:
            return "stop_loss_wrong_side"
        if take_profit is not None and take_profit <= reference_price:
            return "take_profit_wrong_side"
    elif direction == Direction.DOWN:
        if stop_loss is not None and stop_loss <= reference_price:
            return "stop_loss_wrong_side"
        if take_profit is not None and take_profit >= reference_price:
            return "take_profit_wrong_side"
    return None


def check_timestamp_fresh(issued_at: datetime, now: datetime, ttl_seconds: float) -> Optional[str]:
    if now < issued_at:
        return "timestamp_in_future"
    if (now - issued_at).total_seconds() > ttl_seconds:
        return "stale_timestamp"
    return None


def validate_inbound_message(
    provided_key: Optional[str],
    magic_number: int,
    config: EABridgeConfig,
    symbol: Optional[str] = None,
) -> Optional[str]:
    """Aggregate check every inbound HTTP handler runs first — API key,
    magic number, and (when applicable) symbol allowlist, in that order,
    returning the first failure reason."""
    checks = (
        check_api_key(provided_key, config),
        check_magic_number(magic_number, config),
        check_symbol_allowed(symbol, config),
    )
    for reason in checks:
        if reason is not None:
            return reason
    return None


def validate_command_execution_report(
    execution_id: str,
    magic_number: int,
    config: EABridgeConfig,
) -> Optional[str]:
    if not execution_id:
        return "missing_execution_id"
    return check_magic_number(magic_number, config)


__all__ = [
    "check_api_key",
    "check_magic_number",
    "check_symbol_allowed",
    "check_volume",
    "check_stop_loss_take_profit",
    "check_directional_sanity",
    "check_timestamp_fresh",
    "validate_inbound_message",
    "validate_command_execution_report",
]
