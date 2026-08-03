"""Per-check pure evaluation functions (ADR-006 §6-§14).

Every function here is a pure function of its explicit arguments — none
reads a clock, a database, or any other I/O (that responsibility belongs
to `state_store.py` and is read once by `engine.py`, then passed in as
plain values). This mirrors `risk_engine.constraints`'s discipline: each
check is independent, side-effect free, and combined by the caller — here
by AND (ADR-006 §5) rather than Risk Engine's minimum.

Every check resolves to `CheckStatus.UNEVALUABLE` (which blocks, exactly
like `FAILED`) whenever a required input is missing — never a default
`PASSED` (ADR-006 §15 Hard Rule).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Tuple

from ..scanner.models import Direction
from .config import ComplianceEngineConfig, SessionWindow
from .models import AccountState, CheckEvaluation, CheckStatus, NewsCalendarState


def _currency_legs(symbol: str) -> Optional[Tuple[str, str]]:
    if len(symbol) != 6 or not symbol.isalpha():
        return None
    return symbol[:3].upper(), symbol[3:].upper()


def _window_minutes(hour: int, minute: int) -> int:
    return hour * 60 + minute


def _is_active(now_minutes: int, window: SessionWindow) -> bool:
    start = _window_minutes(window.start_hour, window.start_minute)
    end = _window_minutes(window.end_hour, window.end_minute)
    if start == end:
        return False
    if start < end:
        return start <= now_minutes < end
    return now_minutes >= start or now_minutes < end


def kill_switch_gate(triggered: bool, reason: Optional[str]) -> CheckEvaluation:
    if triggered:
        return CheckEvaluation(
            "KILL_SWITCH", CheckStatus.FAILED, f"kill switch latched: {reason or 'unknown'}"
        )
    return CheckEvaluation("KILL_SWITCH", CheckStatus.PASSED, "kill switch not triggered")


def daily_drawdown(
    account_state: Optional[AccountState], config: ComplianceEngineConfig, locked_out: bool
) -> CheckEvaluation:
    if locked_out:
        return CheckEvaluation(
            "DAILY_DRAWDOWN", CheckStatus.FAILED, "daily lockout already in effect"
        )
    if account_state is None or account_state.daily_drawdown_pct is None:
        return CheckEvaluation(
            "DAILY_DRAWDOWN", CheckStatus.UNEVALUABLE, "missing daily drawdown data"
        )
    pct = account_state.daily_drawdown_pct
    threshold = config.max_daily_drawdown_percent
    if pct >= threshold:
        return CheckEvaluation(
            "DAILY_DRAWDOWN", CheckStatus.FAILED, f"daily_drawdown={pct}% >= {threshold}%"
        )
    return CheckEvaluation(
        "DAILY_DRAWDOWN", CheckStatus.PASSED, f"daily_drawdown={pct}% < {threshold}%"
    )


def total_drawdown(
    account_state: Optional[AccountState], config: ComplianceEngineConfig
) -> CheckEvaluation:
    if account_state is None or account_state.total_drawdown_pct is None:
        return CheckEvaluation(
            "TOTAL_DRAWDOWN", CheckStatus.UNEVALUABLE, "missing total drawdown data"
        )
    pct = account_state.total_drawdown_pct
    threshold = config.max_total_drawdown_percent
    if pct >= threshold:
        return CheckEvaluation(
            "TOTAL_DRAWDOWN",
            CheckStatus.FAILED,
            f"total_drawdown={pct}% >= {threshold}% (triggers kill switch)",
        )
    return CheckEvaluation(
        "TOTAL_DRAWDOWN", CheckStatus.PASSED, f"total_drawdown={pct}% < {threshold}%"
    )


def news_restriction(
    news_state: Optional[NewsCalendarState], symbol: str, timestamp: datetime
) -> CheckEvaluation:
    if news_state is None or news_state.feed_stale:
        return CheckEvaluation(
            "NEWS_RESTRICTION", CheckStatus.UNEVALUABLE, "live news calendar feed stale/unavailable"
        )
    if timestamp.tzinfo is None:
        return CheckEvaluation(
            "NEWS_RESTRICTION", CheckStatus.UNEVALUABLE, "timestamp is not timezone-aware"
        )
    legs = _currency_legs(symbol)
    if legs is None:
        return CheckEvaluation(
            "NEWS_RESTRICTION", CheckStatus.UNEVALUABLE, f"unparseable symbol for currency legs: {symbol}"
        )
    ccys = set(legs)
    for window in news_state.blackout_windows:
        if window.currency.upper() in ccys and window.start <= timestamp <= window.end:
            return CheckEvaluation(
                "NEWS_RESTRICTION",
                CheckStatus.FAILED,
                f"news blackout active for {window.currency.upper()}",
            )
    return CheckEvaluation("NEWS_RESTRICTION", CheckStatus.PASSED, "no active news blackout")


def session_restriction(config: ComplianceEngineConfig, timestamp: datetime) -> CheckEvaluation:
    if timestamp.tzinfo is None:
        return CheckEvaluation(
            "SESSION_RESTRICTION", CheckStatus.UNEVALUABLE, "timestamp is not timezone-aware"
        )
    if not config.session_windows:
        return CheckEvaluation(
            "SESSION_RESTRICTION", CheckStatus.UNEVALUABLE, "no session windows configured"
        )
    utc_time = timestamp.astimezone(timezone.utc)
    now_minutes = _window_minutes(utc_time.hour, utc_time.minute)
    active = [w.name for w in config.session_windows if _is_active(now_minutes, w)]
    if active:
        return CheckEvaluation(
            "SESSION_RESTRICTION", CheckStatus.PASSED, f"active session(s): {', '.join(active)}"
        )
    return CheckEvaluation(
        "SESSION_RESTRICTION", CheckStatus.FAILED, "outside all configured session windows"
    )


def weekend_restriction(market_status: Optional[str]) -> CheckEvaluation:
    if market_status is None:
        return CheckEvaluation(
            "WEEKEND_RESTRICTION", CheckStatus.UNEVALUABLE, "missing broker/market state"
        )
    if market_status.upper() != "OPEN":
        return CheckEvaluation(
            "WEEKEND_RESTRICTION", CheckStatus.FAILED, f"market_status={market_status} (not tradeable)"
        )
    return CheckEvaluation("WEEKEND_RESTRICTION", CheckStatus.PASSED, "market is tradeable")


def spread_validation(
    current_spread: Optional[float], symbol: str, config: ComplianceEngineConfig
) -> CheckEvaluation:
    if current_spread is None:
        return CheckEvaluation("SPREAD_VALIDATION", CheckStatus.UNEVALUABLE, "missing current spread")
    threshold = config.spread_threshold_for(symbol)
    if threshold is None:
        return CheckEvaluation(
            "SPREAD_VALIDATION", CheckStatus.UNEVALUABLE, f"no spread threshold configured for {symbol}"
        )
    if current_spread > threshold:
        return CheckEvaluation(
            "SPREAD_VALIDATION", CheckStatus.FAILED, f"spread={current_spread} > {threshold}"
        )
    return CheckEvaluation("SPREAD_VALIDATION", CheckStatus.PASSED, f"spread={current_spread} <= {threshold}")


def slippage_validation(
    expected_slippage: Optional[float], symbol: str, config: ComplianceEngineConfig
) -> CheckEvaluation:
    if expected_slippage is None:
        return CheckEvaluation(
            "SLIPPAGE_VALIDATION", CheckStatus.UNEVALUABLE, "missing expected/historical slippage"
        )
    threshold = config.slippage_threshold_for(symbol)
    if threshold is None:
        return CheckEvaluation(
            "SLIPPAGE_VALIDATION",
            CheckStatus.UNEVALUABLE,
            f"no slippage threshold configured for {symbol}",
        )
    if expected_slippage > threshold:
        return CheckEvaluation(
            "SLIPPAGE_VALIDATION", CheckStatus.FAILED, f"expected_slippage={expected_slippage} > {threshold}"
        )
    return CheckEvaluation(
        "SLIPPAGE_VALIDATION", CheckStatus.PASSED, f"expected_slippage={expected_slippage} <= {threshold}"
    )


def max_positions(
    account_state: Optional[AccountState],
    symbol: str,
    direction: Direction,
    config: ComplianceEngineConfig,
) -> CheckEvaluation:
    if account_state is None:
        return CheckEvaluation("MAX_POSITIONS", CheckStatus.UNEVALUABLE, "missing account state")
    same_symbol_same_direction = sum(
        1
        for p in account_state.open_positions
        if p.symbol == symbol and p.direction == direction
    )
    account_wide = len(account_state.open_positions)
    if same_symbol_same_direction >= config.max_positions_per_symbol:
        return CheckEvaluation(
            "MAX_POSITIONS",
            CheckStatus.FAILED,
            f"{same_symbol_same_direction} same-direction {symbol} positions >= "
            f"{config.max_positions_per_symbol}",
        )
    if account_wide >= config.max_positions_account_wide:
        return CheckEvaluation(
            "MAX_POSITIONS",
            CheckStatus.FAILED,
            f"{account_wide} open positions account-wide >= {config.max_positions_account_wide}",
        )
    return CheckEvaluation("MAX_POSITIONS", CheckStatus.PASSED, "within position-count limits")
