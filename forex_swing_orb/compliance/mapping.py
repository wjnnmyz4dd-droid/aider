"""Deterministic Forex currency <-> pair mapping (Phase 5C, FOREX-ONLY).

The pair universe is the 28 majors formed from the 8 major currencies. It is
DERIVED from an ordered currency list (never hand-listed per currency), so a
currency's affected-pairs set cannot drift or contain an inverted quote.
"""

from __future__ import annotations

# Standard FX quotation precedence: the earlier currency is the base.
_QUOTE_ORDER = ("EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "JPY")
MAJOR_CURRENCIES = frozenset(_QUOTE_ORDER)


def _build_universe():
    pairs = []
    for i, a in enumerate(_QUOTE_ORDER):
        for b in _QUOTE_ORDER[i + 1:]:
            pairs.append(a + b)
    return tuple(pairs)


MAJOR_PAIRS = _build_universe()          # 28 canonical majors, deterministic order
_MAJOR_SET = frozenset(MAJOR_PAIRS)

_FX_SUFFIX = ".FX"


def strip_fx(symbol):
    """'EURUSD.FX' -> 'EURUSD'; returns '' if not a well-formed canonical symbol."""
    if not isinstance(symbol, str) or len(symbol) != 9 or not symbol.endswith(_FX_SUFFIX):
        return ""
    return symbol[0:6]


def base(symbol):
    core = strip_fx(symbol)
    return core[0:3] if core else ""


def quote(symbol):
    core = strip_fx(symbol)
    return core[3:6] if core else ""


def is_forex_symbol(symbol):
    """True iff ``symbol`` is a canonical '<PAIR>.FX' among the 28 majors."""
    core = strip_fx(symbol)
    return core in _MAJOR_SET


def affects(currency):
    """Frozenset of major pairs whose base or quote is ``currency``."""
    cur = str(currency).upper()
    return frozenset(p for p in MAJOR_PAIRS if p[0:3] == cur or p[3:6] == cur)


def pair_blocked_by_currency(symbol, currency):
    """True iff ``currency`` is the base or quote of ``symbol`` (news relevance)."""
    cur = str(currency).upper()
    return cur == base(symbol) or cur == quote(symbol)
