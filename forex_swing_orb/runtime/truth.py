"""Read-only broker-truth adapter (Phase 8D) for the manage channel.

The accepted :class:`BridgeMt5Adapter` depends on a narrow *truth* interface —
``terminal_connected()`` / ``position_by_ticket(ticket)`` / ``symbol_info(symbol)``
— to read broker state (its WRITE path always routes through the manage bridge to
the EA, never here). In production that truth is the live MT5 terminal; this
adapter exposes exactly that interface over the injected live MT5 client
(:mod:`forex_swing_orb.live.mt5_client`) with NO trading capability. Off-Windows
it is exercised with :class:`FakeMt5Client`. No networking beyond the client.
"""

from __future__ import annotations

from ..live import mt5_client as mc


class Mt5TruthSource:
    """Adapts the live MT5 client to the manage adapter's read-only truth surface.

    ``symbol`` values are broker symbols (the manager registers positions under the
    broker symbol reported by the terminal), matching how the live client and the
    EA address instruments.
    """

    def __init__(self, client):
        self.client = client
        self._last_positions_error = None      # observational diagnostic only (K)

    def terminal_connected(self):
        ti = self.client.terminal_info()
        return bool(getattr(ti, "connected", False)) if ti is not None else False

    def positions(self):
        """Broker open positions as a KNOWN list, or ``None`` when UNKNOWN.

        F3 — three DISTINCT semantics; UNKNOWN must never collapse to KNOWN_EMPTY:

          * ``[]`` / ``()``            -> KNOWN_EMPTY   (a proven flat book)
          * ``[p, ...]``               -> KNOWN_NONEMPTY
          * ``None`` / an exception /
            a malformed (non-list/tuple) return -> UNKNOWN, returned as ``None``

        A transient query failure is NEVER read as an empty (flat) book. Callers must
        handle ``None`` explicitly (defer / hold / fail closed) — see runtime.adoption
        and :meth:`position_by_ticket`."""
        try:
            raw = self.client.positions_get()
        except Exception:                      # query raised -> UNKNOWN
            self._last_positions_error = self._read_last_error()
            return None
        if raw is None:                        # broker/API could not answer -> UNKNOWN
            self._last_positions_error = self._read_last_error()
            return None
        if not isinstance(raw, (list, tuple)):  # malformed return type -> UNKNOWN
            self._last_positions_error = self._read_last_error()
            return None
        self._last_positions_error = None
        return list(raw)                       # KNOWN (possibly empty)

    def position_by_ticket(self, ticket):
        raw = self.positions()
        if raw is None:                        # UNKNOWN -> not found (caller fails closed; M-6)
            return None
        for p in raw:
            if getattr(p, "ticket", None) == ticket and not getattr(p, "closed", False):
                return p
        return None

    def last_positions_error(self):
        """Last positions_get() error detail (observational diagnostic only; never
        trading authority, never credentials). None when the last query was KNOWN."""
        return self._last_positions_error

    def _read_last_error(self):
        """Best-effort MT5 last_error() for diagnostics; None if unavailable. Pure
        observation — it never influences the UNKNOWN classification above."""
        getter = getattr(self.client, "last_error", None)
        if getter is None:
            return None
        try:
            return getter()
        except Exception:
            return None

    def symbol_info(self, symbol):
        return self.client.symbol_info(symbol)

    def deals_for_position(self, position_id):
        """READ-ONLY closed-deal history for one broker position id, or ``None``
        when the capability/data is unavailable.

        Used only by the non-authoritative outcome reconciler to confirm a close
        and read exit prices — never by the trading/management path. ``None`` means
        *unknown* (client lacks the method, the query raised, or the terminal
        returned no data) and MUST NOT be read as a confirmed close; an empty list
        means the query succeeded but reported no deals. No trading capability."""
        getter = getattr(self.client, "history_deals_get", None)
        if getter is None:
            return None
        try:
            deals = getter(position=position_id)
        except Exception:
            return None
        return list(deals) if deals is not None else None
