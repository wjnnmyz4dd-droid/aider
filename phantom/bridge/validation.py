"""Transport-integrity validation for the PhantomBridgeEA bridge.

Every function here defends the *relay* between Python and the MQL5 EA
from being corrupted, replayed, or spoofed -- none of them decide a
trade, because this phase has no trading-decision authority to begin
with; it only ever relays a command that was already supplied to it.
Each takes plain values and returns `Optional[ErrorCode]` (a reason, or
`None` meaning the check passed). This is the concrete implementation
of "validate before acknowledge" -- every route handler in `server.py`
runs these checks before ever responding with success.
"""

from __future__ import annotations

import hmac
from datetime import datetime
from typing import Optional

from .config import BridgeConfig
from .models import ErrorCode


def check_api_key(provided_key: Optional[str], config: BridgeConfig) -> Optional[ErrorCode]:
    if provided_key is None:
        return ErrorCode.MISSING_API_KEY
    if not hmac.compare_digest(provided_key, config.api_key):
        return ErrorCode.INVALID_API_KEY
    return None


def check_magic_number(magic_number: int, config: BridgeConfig) -> Optional[ErrorCode]:
    if magic_number != config.magic_number:
        return ErrorCode.MAGIC_NUMBER_MISMATCH
    return None


def check_symbol_allowed(symbol: Optional[str], config: BridgeConfig) -> Optional[ErrorCode]:
    if symbol is None:
        return None
    if symbol not in config.allowed_symbols:
        return ErrorCode.SYMBOL_NOT_ALLOWED
    return None


def check_volume(volume: Optional[float], config: BridgeConfig) -> Optional[ErrorCode]:
    if volume is None:
        return None
    if volume <= 0:
        return ErrorCode.INVALID_VOLUME
    if volume > config.max_lot_size:
        return ErrorCode.VOLUME_EXCEEDS_MAX
    return None


def check_stop_loss_take_profit(
    stop_loss: Optional[float], take_profit: Optional[float]
) -> Optional[ErrorCode]:
    if stop_loss is not None and stop_loss <= 0:
        return ErrorCode.INVALID_STOP_LOSS
    if take_profit is not None and take_profit <= 0:
        return ErrorCode.INVALID_TAKE_PROFIT
    return None


def check_timestamp_fresh(
    issued_at: datetime, now: datetime, ttl_seconds: float
) -> Optional[ErrorCode]:
    if now < issued_at:
        return ErrorCode.TIMESTAMP_IN_FUTURE
    if (now - issued_at).total_seconds() > ttl_seconds:
        return ErrorCode.STALE_TIMESTAMP
    return None


def validate_inbound_message(
    provided_key: Optional[str],
    magic_number: int,
    config: BridgeConfig,
    symbol: Optional[str] = None,
) -> Optional[ErrorCode]:
    """Aggregate check every inbound HTTP handler runs first -- API key,
    magic number, and (when applicable) symbol allowlist, in that
    order, returning the first failure reason."""
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
    correlation_id: str, magic_number: int, config: BridgeConfig
) -> Optional[ErrorCode]:
    if not correlation_id:
        return ErrorCode.MISSING_CORRELATION_ID
    return check_magic_number(magic_number, config)


__all__ = [
    "check_api_key",
    "check_magic_number",
    "check_symbol_allowed",
    "check_volume",
    "check_stop_loss_take_profit",
    "check_timestamp_fresh",
    "validate_inbound_message",
    "validate_command_execution_report",
]
