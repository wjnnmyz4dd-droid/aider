"""Broker-grid comparison helpers for the manage channel (transport/representation).

This module is NOT a price-geometry authority and NOT Position-Management arithmetic.
It holds no pip derivation, no symbol-name heuristic, no default digit count, no
default point, and no default tick size. Per-symbol geometry comes ONLY from the ONE
authoritative source — ``position.geometry.resolve`` (H6/M11) — which itself fails
closed on missing / malformed / non-FX metadata.

PR-3L: the previous guessed ``_FALLBACK_DIGITS = 5`` is removed. Executable stop
PRICES are preserved VERBATIM from the Position Manager (which already quantizes on
the authoritative grid before ever issuing a modification, and fails closed when
geometry is unknown), so the transport never re-quantizes an executable target onto a
guessed grid. The only remaining use of geometry here is a grid-tolerant STOP
COMPARISON (benign broker normalization still verifies); when authoritative geometry
is unavailable that comparison fails closed (returns "not equal") so reconciliation
stays UNCERTAIN/retry and a distorted stop is never silently accepted.
"""

from __future__ import annotations

import math

from ..position import geometry as geo


def _geom(mt5, symbol):
    """Authoritative per-symbol FX geometry (or None). Single source: H6 resolve()."""
    try:
        info = mt5.symbol_info(symbol)
    except Exception:
        return None
    return geo.resolve(info)


def point(mt5, symbol):
    """Authoritative price quantum, or None when geometry is unavailable (no guess)."""
    g = _geom(mt5, symbol)
    return g.point if g is not None else None


def digits(mt5, symbol):
    """Authoritative display/quantization precision, or None (no guessed fallback)."""
    g = _geom(mt5, symbol)
    return g.digits if g is not None else None


def eq_stop(a, b, mt5, symbol):
    """Grid-tolerant equality on the AUTHORITATIVE symbol tick grid (a broker may
    benignly normalize a stored stop). Fails closed: None operands compare by identity,
    non-finite values are never equal, and when authoritative geometry is unavailable
    this returns False — equality can never be *assumed* on an unknown grid, so a
    read-back/reconciliation compare stays UNCERTAIN rather than silently accepting a
    possibly-distorted stop."""
    if a is None or b is None:
        return a is b
    if not (isinstance(a, (int, float)) and isinstance(b, (int, float))
            and math.isfinite(a) and math.isfinite(b)):
        return False
    g = _geom(mt5, symbol)
    if g is None:
        return False                       # unknown geometry -> cannot prove equality
    return int(round(a / g.point)) == int(round(b / g.point))
