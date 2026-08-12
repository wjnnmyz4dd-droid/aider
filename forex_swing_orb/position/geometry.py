"""Canonical per-symbol FX price geometry (PR-3D / H6).

ONE read-only derivation of executable price geometry — ``point`` (price quantum),
``digits`` (display/quantization precision) and ``pip`` (strategy price unit) — from
AUTHORITATIVE broker symbol metadata. Session Edge is FOREX-ONLY; standard spot-FX
symbols quote at 2/3 digits (JPY-quoted; pip = 0.01) or 4/5 digits (pip = 0.0001),
where the 3-digit and 5-digit forms are the fractional-pip ("pipette") variants:

    5-digit EURUSD  point=0.00001  digits=5  pip=0.0001 (= 10 * point)
    4-digit EURUSD  point=0.0001   digits=4  pip=0.0001 (=      point)
    3-digit USDJPY  point=0.001    digits=3  pip=0.01   (= 10 * point)
    2-digit USDJPY  point=0.01     digits=2  pip=0.01   (=      point)

``pip`` is derived from the metadata DIGIT COUNT (a broker-reported fact), NEVER from
the symbol name and NEVER from a universal 0.0001 assumption — so it is correct for
JPY pairs, broker suffixes/prefixes (EURUSD.a, USDJPYm, ...) and every quote format.

Fail closed: if metadata is missing, malformed, non-finite, internally inconsistent
(``point`` must equal ``10 ** -digits``), or not a supported FX price format, then
``resolve`` returns ``None`` and NO executable geometry is assumed. Callers MUST NOT
modify a stop (or quantize an executable price to a guessed grid) when geometry is
unknown. This module never touches a broker, never writes, and is pure/deterministic.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Supported FX display precisions. 4/5-digit -> pip 1e-4; 2/3-digit -> pip 1e-2.
_FX_DIGITS = (2, 3, 4, 5)
_REL_TOL = 1e-9                 # digits/point (and tick/point) consistency tolerance


@dataclass(frozen=True)
class SymbolGeometry:
    """An immutable, authoritative per-symbol geometry snapshot."""
    point: float               # tradable price quantum (FX: 10 ** -digits)
    digits: int                # display / quantization precision
    pip: float                 # strategy pip in price units (per symbol)

    def pips_to_price(self, pips):
        """Convert a pip-denominated distance to a price distance for THIS symbol."""
        return pips * self.pip


def _is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def resolve(info):
    """Derive :class:`SymbolGeometry` from a ``symbol_info``-like object (duck-typed
    ``.digits``, ``.point``, optional ``.trade_tick_size``). Returns ``None`` (fail
    closed) on ANY missing / malformed / non-finite / inconsistent / non-FX metadata.
    Pure and deterministic — safe to call read-only on every cycle."""
    if info is None:
        return None

    digits = getattr(info, "digits", None)
    if not isinstance(digits, int) or isinstance(digits, bool):
        return None
    if digits not in _FX_DIGITS:                 # non-FX price precision -> unsupported
        return None

    point = getattr(info, "point", None)
    if not _is_number(point):
        return None
    point = float(point)
    if not math.isfinite(point) or point <= 0.0:
        return None
    expected = 10.0 ** (-digits)
    if abs(point - expected) > expected * _REL_TOL:      # digits/point inconsistent
        return None

    # Optional tradable quantum: for spot FX it equals ``point``. If the broker
    # exposes an exotic tick grid (tick_size != point, e.g. a CFD/metal), that is
    # OUT of the FOREX-only product scope -> fail closed rather than guess.
    tick = getattr(info, "trade_tick_size", None)
    if tick is not None:
        if not _is_number(tick):
            return None
        tick = float(tick)
        if not math.isfinite(tick) or tick <= 0.0:
            return None
        if abs(tick - point) > point * _REL_TOL:
            return None

    pip = 1e-4 if digits in (4, 5) else 1e-2     # 2/3-digit (JPY) -> 0.01
    return SymbolGeometry(point=point, digits=digits, pip=pip)
