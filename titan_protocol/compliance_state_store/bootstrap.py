"""Day-one bootstrap-balance verification (KNOWN_GAPS.md #9).

`ComplianceStateStore.load_or_bootstrap()` used to trust whatever
balance the *first-ever* successful `/bridge/account` report carried,
even if that report arrived after the account already had open
positions or floating P&L for the day -- silently baking a
non-representative value into `daily_starting_balance` for the rest of
that trading day.

These are pure functions of wire-reported facts, no state of its own --
same discipline as `trading_day_id_for()` in this package."""

from __future__ import annotations

from typing import Optional


def is_account_verified_flat(
    current_balance: float, current_equity: float, has_open_positions: bool, equity_tolerance: float,
) -> bool:
    """True only when the account currently has no open positions and no
    floating P&L (`balance` == `equity` within `equity_tolerance`) --
    the strongest signal available from wire data alone that
    `current_balance` was not contaminated by trading activity already
    in progress. Cannot detect *closed*-trade contamination earlier the
    same day (a trade opened and closed before the first report ever
    reached Titan already changed `balance` permanently, with no wire
    field to reveal that) -- that residual case is what
    `day_start_balance_override` exists for."""

    if has_open_positions:
        return False
    return abs(current_balance - current_equity) <= equity_tolerance


def resolve_bootstrap_balance(
    current_balance: float, current_equity: float, has_open_positions: bool,
    equity_tolerance: float, override_balance: Optional[float],
) -> Optional[float]:
    """Returns the balance to bootstrap `daily_starting_balance` from,
    or `None` if bootstrap cannot yet proceed. An operator-supplied
    `override_balance` always wins outright (fully deterministic, zero
    ambiguity); absent that, bootstrap proceeds only once the account is
    verified flat. Never returns a balance that hasn't either been
    explicitly confirmed by the operator or verified flat -- the
    caller must treat `None` as "not ready, skip this cycle", never
    substitute a guess."""

    if override_balance is not None:
        return override_balance
    if is_account_verified_flat(current_balance, current_equity, has_open_positions, equity_tolerance):
        return current_balance
    return None


__all__ = ["is_account_verified_flat", "resolve_bootstrap_balance"]
