"""Deterministic Position Management MATHEMATICS (Phase 4C-R — FROZEN SPEC).

Pure functions only: given inputs, they return the deterministic proposed values
and fail-closed sentinels. They compute NOTHING at a broker, move NO stop, decide
NO precedence, and have NO side effects — a future executor consumes them under
the precedence and invariants in ``contract.py``. This is the frozen arithmetic
so no break-even / profit-lock / trailing number is left to interpretation.

Conventions (frozen):
  * initial risk R is IMMUTABLE = |entry - initial_stop|; every R-based trigger
    uses this initial R, never a later stop.
  * trigger operator is ``>=`` toward profit (equality triggers).
  * a proposed stop is only meaningful if it is a strict improvement and legal
    (never-widen / never-loosen) — checked by ``is_stop_improvement`` +
    ``contract.stop_move_is_legal``.
  * zero / negative / non-finite initial risk FAILS CLOSED (returns None).
"""

from __future__ import annotations

import math

from .contract import _is_long, _is_short, _finite   # shared direction/finite helpers


def initial_risk(direction, entry, initial_stop):
    """Immutable R = |entry - initial_stop|, or None (fail closed) for zero /
    negative / non-finite / wrong-sided risk."""
    if not (_finite(entry) and _finite(initial_stop)):
        return None
    if _is_long(direction):
        r = entry - initial_stop           # stop must be below entry
    elif _is_short(direction):
        r = initial_stop - entry           # stop must be above entry
    else:
        return None
    return r if r > 0 else None            # zero / negative -> fail closed


def _pips(cfg, pips):
    return pips * cfg.pip_size


# -- break-even --------------------------------------------------------------
def breakeven_trigger_price(direction, entry, R, cfg):
    """Price at which break-even arms. None if R invalid."""
    if R is None or not _finite(entry):
        return None
    move = cfg.breakeven_trigger_r * R
    return entry + move if _is_long(direction) else entry - move


def breakeven_triggered(direction, price, trigger_price):
    """Operator is >= toward profit (equality triggers)."""
    if trigger_price is None or not _finite(price):
        return False
    return price >= trigger_price if _is_long(direction) else price <= trigger_price


def breakeven_stop(direction, entry, cfg):
    """The break-even stop level = entry +/- (buffer + commission) pips, so the
    locked stop nets past spread/commission costs. None on invalid entry."""
    if not _finite(entry):
        return None
    off = _pips(cfg, cfg.breakeven_buffer_pips + cfg.commission_pips)
    return entry + off if _is_long(direction) else entry - off


# -- profit lock -------------------------------------------------------------
def profit_lock_trigger_price(direction, entry, R, cfg):
    if R is None or not _finite(entry):
        return None
    move = cfg.profit_lock_r * R
    return entry + move if _is_long(direction) else entry - move


def profit_lock_triggered(direction, price, trigger_price):
    if trigger_price is None or not _finite(price):
        return False
    return price >= trigger_price if _is_long(direction) else price <= trigger_price


def profit_lock_stop(direction, entry, R, cfg):
    """Lock +profit_lock_retain_r * R of profit. None if R invalid."""
    if R is None or not _finite(entry):
        return None
    off = cfg.profit_lock_retain_r * R
    return entry + off if _is_long(direction) else entry - off


# -- structure trailing ------------------------------------------------------
def trailing_stop_candidate(direction, confirmed_swing, cfg):
    """Proposed trailing stop from a CONFIRMED strategy swing (consumed, never
    recomputed). LONG trails below the confirmed higher-low; SHORT above the
    confirmed lower-high. Returns None when there is no valid structure (the
    executor then holds — PM_TRAIL_PENDING/NO_IMPROVEMENT)."""
    if confirmed_swing is None or not _finite(confirmed_swing):
        return None
    off = _pips(cfg, cfg.trail_offset_pips)
    return confirmed_swing - off if _is_long(direction) else confirmed_swing + off


def structure_is_stale(bars_since_swing, cfg):
    """True if the confirmed structure is older than the frozen staleness bound."""
    if not isinstance(bars_since_swing, int):
        return True
    return bars_since_swing > cfg.stale_structure_max_bars


def is_stop_improvement(direction, current_stop, candidate_stop, cfg):
    """A candidate stop improves protection only if it moves toward profit by at
    least ``min_trail_improvement_pips``. Equal or worse -> False (hold)."""
    if candidate_stop is None or not (_finite(current_stop) and _finite(candidate_stop)):
        return False
    thresh = _pips(cfg, cfg.min_trail_improvement_pips)
    if _is_long(direction):
        return (candidate_stop - current_stop) >= thresh
    if _is_short(direction):
        return (current_stop - candidate_stop) >= thresh
    return False


def respects_broker_min_stop(direction, price, candidate_stop, cfg):
    """A proposed stop must sit at least broker_min_stop_pips away from price on
    the correct side. Returns True when the constraint is satisfied (or disabled)."""
    if cfg.broker_min_stop_pips <= 0:
        return True
    if candidate_stop is None or not (_finite(price) and _finite(candidate_stop)):
        return False
    dist = _pips(cfg, cfg.broker_min_stop_pips)
    if _is_long(direction):
        return (price - candidate_stop) >= dist
    if _is_short(direction):
        return (candidate_stop - price) >= dist
    return False
