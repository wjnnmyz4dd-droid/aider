"""Canonical execution-sizing + monetary-risk primitives (PR-3J / M9).

ONE authoritative, pure, deterministic risk calculation shared by:
  * the upstream SIZER (producer) that chooses the executable volume, and
  * the compliance RISK GATE that independently RE-PROVES the resulting monetary
    loss-at-stop before authorization.

Money is denominated in the ACCOUNT (deposit) currency: MT5 reports
``trade_tick_value`` in the deposit currency, so

    loss_at_stop = |entry - stop| / tick_size * tick_value * volume

is directly account-currency money and needs NO second FX conversion (this mirrors
the established ``live.providers._open_risk`` precedent). FOREX-only. Fails closed
on any missing / non-finite / non-positive input. This module computes MONEY only;
it never touches price geometry (H6) or strategy math.
"""

from __future__ import annotations

import math

# Conservative comparison tolerance for monetary limits (§21): absolute floor plus a
# tiny relative component, so float noise can never admit an order meaningfully over
# the limit while an exact-limit order (loss == limit) is still allowed.
_ABS_EPS = 1e-6


def _risk_eps(limit):
    return max(_ABS_EPS, abs(float(limit)) * 1e-9)


def _finite_pos(x):
    return (isinstance(x, (int, float)) and not isinstance(x, bool)
            and math.isfinite(x) and x > 0)


def price_distance(entry, stop):
    """|entry - stop| as a positive float, or None if inputs are invalid or equal
    (entry == stop => undefined risk => fail closed)."""
    if not (_finite_pos(entry) and _finite_pos(stop)):
        return None
    d = abs(float(entry) - float(stop))
    return d if d > 0 else None


def metadata_ok(tick_size, tick_value, volume_min, volume_max, volume_step):
    """True iff all monetary/volume metadata needed to PROVE risk is present and
    self-consistent. Missing/zero/negative/NaN/Inf metadata fails closed (§9/§10)."""
    return (_finite_pos(tick_size) and _finite_pos(tick_value)
            and _finite_pos(volume_min) and _finite_pos(volume_max)
            and _finite_pos(volume_step) and volume_max >= volume_min)


def loss_at_stop(entry, stop, volume, tick_size, tick_value):
    """Account-currency money lost if ``volume`` lots move from ``entry`` to ``stop``.
    None on any invalid/missing input (fail closed). Increasing volume or stop
    distance can only INCREASE this value (properties A/B)."""
    d = price_distance(entry, stop)
    if d is None:
        return None
    if not (_finite_pos(tick_size) and _finite_pos(tick_value) and _finite_pos(volume)):
        return None
    return d / float(tick_size) * float(tick_value) * float(volume)


def quantize_down(volume, volume_min, volume_max, volume_step):
    """Round ``volume`` DOWN to the broker step, capped at ``volume_max``, then require
    the result within [min, max]. NEVER rounds up (property C). None if the metadata
    is invalid or the result would fall below ``volume_min``."""
    if not (_finite_pos(volume) and _finite_pos(volume_min)
            and _finite_pos(volume_max) and _finite_pos(volume_step)
            and volume_max >= volume_min):
        return None
    v = min(float(volume), float(volume_max))            # cap first (never increases)
    steps = math.floor((v - float(volume_min)) / float(volume_step) + 1e-9)
    if steps < 0:
        return None                                      # below the minimum lot
    q = float(volume_min) + steps * float(volume_step)
    if q > v + 1e-12 or q > float(volume_max) + 1e-12 or q < float(volume_min) - 1e-12:
        return None
    return round(q, 8)


def allowable_volume(entry, stop, risk_amount_limit, tick_size, tick_value,
                     volume_min, volume_max, volume_step):
    """Largest step-aligned volume whose ``loss_at_stop`` does not exceed
    ``risk_amount_limit``, within [volume_min, volume_max].

    Returns None => NO TRADE, when:
      * required metadata is missing/invalid (§10);
      * even one ``volume_min`` lot would exceed the risk budget — a wide stop
        (§25): minimum lot cannot override risk;
      * the quantized volume cannot be proven within budget.
    A very tight stop (§24) yields a large raw size that is safely capped at
    ``volume_max`` (never divide-by-zero: price_distance == 0 fails closed).
    """
    if not metadata_ok(tick_size, tick_value, volume_min, volume_max, volume_step):
        return None
    if not _finite_pos(risk_amount_limit):
        return None
    d = price_distance(entry, stop)
    if d is None:
        return None
    per_lot = d / float(tick_size) * float(tick_value)   # money risked by 1.0 lot
    if not _finite_pos(per_lot):
        return None
    raw = risk_amount_limit / per_lot
    if raw < float(volume_min):                          # min lot exceeds budget -> NO TRADE
        return None
    q = quantize_down(raw, volume_min, volume_max, volume_step)
    if q is None:
        return None
    la = loss_at_stop(entry, stop, q, tick_size, tick_value)
    if la is None or la > risk_amount_limit + _risk_eps(risk_amount_limit):
        return None                                      # conservative final guard
    return q


def risk_within_limit(entry, stop, volume, tick_size, tick_value, risk_amount_limit):
    """(ok, loss_at_stop) — ok is True iff the ACTUAL loss-at-stop for ``volume`` is
    computable AND within ``risk_amount_limit`` (equality allowed, §21). ok is False
    with loss None when any input needed to PROVE risk is missing (fail closed)."""
    la = loss_at_stop(entry, stop, volume, tick_size, tick_value)
    if la is None or not _finite_pos(risk_amount_limit):
        return False, la
    return (la <= risk_amount_limit + _risk_eps(risk_amount_limit)), la
