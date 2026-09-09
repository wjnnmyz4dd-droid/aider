"""Single source of truth for 'is a broker position CONFIRMED fully closed' from
its MT5 deal history (read-only, deterministic).

Used by BOTH the OutcomeReconciler (to record a closed-trade outcome) and the
Position Manager (to confirm a close before transitioning to the terminal CLOSED
phase). A position is confirmed closed ONLY by a netted-flat deal set — an entry
leg plus matching exit legs summing back to flat. An absent position or
unavailable/partial deal history is NEVER treated as closed (H1 invariant).
"""

from __future__ import annotations

import math

# MT5 deal-entry classification (mirrors live.mt5_client.DEAL_ENTRY_*).
DEAL_ENTRY_IN = 0
DEAL_ENTRY_OUT = 1
DEAL_ENTRY_OUT_BY = 3
_EXITS = (DEAL_ENTRY_OUT, DEAL_ENTRY_OUT_BY)
VOL_TOL = 1e-6


def _num(v):
    """Finite float or None (rejects bool/NaN/Inf/non-numeric)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else None
    return None


def _get(d, key):
    """Attribute-or-item accessor tolerant of MT5 namedtuples/objects/dicts."""
    try:
        return getattr(d, key)
    except AttributeError:
        try:
            return d[key]
        except Exception:
            return None


def confirm_full_close(deals, *, entry_in=DEAL_ENTRY_IN, exits=_EXITS, tol=VOL_TOL):
    """``(weighted_close, out_volume, deal_count)`` iff ``deals`` confirm a FULL
    netted-flat close (an entry leg, one or more exit legs, netted flat within
    ``tol``); else ``None``. The exit price is volume-weighted across partial
    closes. Requiring both a non-zero IN and matching OUT volume guards against a
    partial/one-sided history snapshot being mistaken for a completed round trip."""
    if not deals:
        return None
    in_vol = out_vol = notional = 0.0
    n = 0
    for d in deals:
        n += 1
        entry = _get(d, "entry")
        vol = _num(_get(d, "volume"))
        price = _num(_get(d, "price"))
        if vol is None:
            continue
        if entry == entry_in:
            in_vol += vol
        elif entry in exits and price is not None:
            out_vol += vol
            notional += price * vol
    if in_vol <= 0 or out_vol <= 0:
        return None
    if abs(in_vol - out_vol) > tol:
        return None
    return notional / out_vol, out_vol, n


def is_confirmed_closed(deals):
    """True iff ``deals`` positively confirm a full close (read-only)."""
    return confirm_full_close(deals) is not None
