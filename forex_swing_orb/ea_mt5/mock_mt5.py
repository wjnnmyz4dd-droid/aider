"""Programmable in-memory mock of the MetaTrader 5 trade API (TEST ONLY).

This module is a **test double**. It is never shipped inside, imported by, or
compiled into the MQL5 Expert Advisor — the EA talks to the real MT5 terminal
API. It exists so the Session Edge execution *protocol* (claim -> validate ->
ack -> order -> result -> recovery) can be exercised deterministically on this
platform, where no MetaTrader terminal / MQL compiler is available.

It models only the narrow slice of the MT5 trade API the adapter uses:

  * ``symbol_info``          -> broker symbol metadata (or None for unknown)
  * ``symbol_select``        -> ensure a symbol is in Market Watch
  * ``order_send``           -> submit a BUY/SELL market order with SL/TP
  * ``positions_get``        -> list open positions
  * ``position_by_comment``  -> ticket <-> signal_id correlation (recovery)
  * ``position_close``       -> close an open position

Determinism: no wall clock and no RNG. Tickets come from a counter; fills come
from a fixed quote book or per-order scripted outcomes. Every retcode below is a
real MT5 ``TRADE_RETCODE_*`` value so the adapter's mapping is meaningful.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# -- real MT5 return codes (MqlTradeResult.retcode) -------------------------
TRADE_RETCODE_REQUOTE = 10004
TRADE_RETCODE_REJECT = 10006
TRADE_RETCODE_DONE = 10009
TRADE_RETCODE_TIMEOUT = 10012
TRADE_RETCODE_INVALID = 10013
TRADE_RETCODE_INVALID_VOLUME = 10014
TRADE_RETCODE_INVALID_PRICE = 10015
TRADE_RETCODE_INVALID_STOPS = 10016
TRADE_RETCODE_TRADE_DISABLED = 10017
TRADE_RETCODE_MARKET_CLOSED = 10018
TRADE_RETCODE_NO_MONEY = 10019
TRADE_RETCODE_PRICE_OFF = 10021           # "off quotes"
TRADE_RETCODE_TOO_MANY_REQUESTS = 10024   # trade subsystem busy / context busy
TRADE_RETCODE_CONNECTION = 10031          # no connection to the trade server

# -- order/position sides (MT5 ORDER_TYPE_* subset) -------------------------
ORDER_TYPE_BUY = 0
ORDER_TYPE_SELL = 1

# -- symbol trade modes (SYMBOL_TRADE_MODE_*) -------------------------------
SYMBOL_TRADE_MODE_DISABLED = 0
SYMBOL_TRADE_MODE_FULL = 4


class MT5Disconnected(Exception):
    """Raised by the mock when the terminal is disconnected from the broker.

    The real MQL5 EA never sees a Python exception; it observes the same
    condition through ``TerminalInfoInteger(TERMINAL_CONNECTED) == false`` and a
    ``TRADE_RETCODE_CONNECTION`` retcode. The adapter treats both the exception
    and the retcode as the deterministic ``terminal disconnected`` failure.
    """


@dataclass
class SymbolInfo:
    name: str
    trade_mode: int = SYMBOL_TRADE_MODE_FULL
    volume_min: float = 0.01
    volume_max: float = 100.0
    volume_step: float = 0.01
    digits: int = 5
    point: float = 0.00001
    bid: float = 1.10000
    ask: float = 1.10002


@dataclass
class OrderResult:
    retcode: int
    comment: str = ""
    order: int = 0        # ticket of the resulting order
    deal: int = 0         # ticket of the resulting deal
    position: int = 0     # ticket of the resulting position
    price: float = 0.0    # actual fill price
    volume: float = 0.0   # actual filled volume
    bid: float = 0.0
    ask: float = 0.0

    @property
    def ok(self):
        return self.retcode == TRADE_RETCODE_DONE


@dataclass
class Position:
    ticket: int
    symbol: str
    type: int             # ORDER_TYPE_BUY / ORDER_TYPE_SELL
    volume: float
    price_open: float
    sl: float
    tp: float
    comment: str          # carries the signal_id for ticket<->signal correlation
    closed: bool = False
    close_price: float = 0.0


@dataclass
class MockMT5:
    """A programmable MT5 terminal double.

    Behaviour is driven by:

    * ``symbols``      : known broker symbols -> :class:`SymbolInfo`.
    * ``connected``    : terminal<->server link; False => order_send raises
      :class:`MT5Disconnected` and reports ``TRADE_RETCODE_CONNECTION``.
    * ``outcomes``     : FIFO list of scripted retcodes for the next order_send
      calls; an empty list means "fill" (``TRADE_RETCODE_DONE``).
    * ``account_id`` / ``terminal_id`` : identity strings surfaced in acks.
    """

    symbols: dict = field(default_factory=dict)
    connected: bool = True
    outcomes: list = field(default_factory=list)
    account_id: str = "MOCK-ACCOUNT-1"
    terminal_id: str = "MOCK-TERMINAL-1"
    _next_ticket: int = 5_000_000
    positions: dict = field(default_factory=dict)     # ticket -> Position
    order_log: list = field(default_factory=list)     # every order_send request seen
    modify_outcomes: list = field(default_factory=list)  # scripted stop-modify results
    modify_log: list = field(default_factory=list)    # every modify_stop attempt seen

    # -- setup helpers ------------------------------------------------------
    def add_symbol(self, name, **kw):
        info = SymbolInfo(name=name, **kw)
        self.symbols[name] = info
        return info

    def script(self, *retcodes):
        """Queue scripted retcodes for the next order_send call(s)."""
        self.outcomes.extend(retcodes)

    # -- MT5 API surface used by the adapter --------------------------------
    def symbol_info(self, symbol):
        return self.symbols.get(symbol)

    def symbol_select(self, symbol, enable=True):
        return symbol in self.symbols

    def terminal_connected(self):
        return self.connected

    def order_send(self, request):
        """Submit a market order. ``request`` mirrors MqlTradeRequest fields:
        ``symbol, volume, type, sl, tp, price, comment`` (comment = signal_id).
        Returns an :class:`OrderResult`. Never raises except on disconnect."""
        self.order_log.append(dict(request))
        if not self.connected:
            raise MT5Disconnected("terminal not connected to trade server")

        retcode = self.outcomes.pop(0) if self.outcomes else TRADE_RETCODE_DONE
        info = self.symbols.get(request["symbol"])
        if info is None:
            return OrderResult(retcode=TRADE_RETCODE_INVALID,
                               comment="unknown symbol")
        if retcode != TRADE_RETCODE_DONE:
            return OrderResult(retcode=retcode, comment="scripted",
                               bid=info.bid, ask=info.ask)

        fill = info.ask if request["type"] == ORDER_TYPE_BUY else info.bid
        ticket = self._next_ticket
        self._next_ticket += 1
        self.positions[ticket] = Position(
            ticket=ticket, symbol=request["symbol"], type=request["type"],
            volume=request["volume"], price_open=fill,
            sl=request.get("sl", 0.0), tp=request.get("tp", 0.0),
            comment=request.get("comment", ""),
        )
        return OrderResult(retcode=TRADE_RETCODE_DONE, order=ticket, deal=ticket,
                           position=ticket, price=fill, volume=request["volume"],
                           bid=info.bid, ask=info.ask, comment=request.get("comment", ""))

    def positions_get(self, symbol=None):
        out = [p for p in self.positions.values() if not p.closed]
        if symbol is not None:
            out = [p for p in out if p.symbol == symbol]
        return out

    def position_by_comment(self, comment):
        """Ticket<->signal_id correlation used for recovery. Returns the open
        position whose comment == comment, else None."""
        for p in self.positions.values():
            if p.comment == comment and not p.closed:
                return p
        return None

    def position_by_ticket(self, ticket):
        """Return the open position for a ticket (None if absent/closed)."""
        p = self.positions.get(ticket)
        return p if (p is not None and not p.closed) else None

    def script_modify(self, *outcomes):
        """Queue stop-modification outcomes for the next modify_stop call(s):
        'done' | 'reject' | 'invalid_stops' | 'requote' | 'off_quotes' |
        'disconnect' (raises, no change) | 'applied_but_unacked' (applies the SL
        then raises — simulates a crash after the broker modified but before the
        ack/audit)."""
        self.modify_outcomes.extend(outcomes)

    def modify_stop(self, ticket, new_sl):
        """Modify a position's stop-loss (MT5 TRADE_ACTION_SLTP analog).
        Returns an :class:`OrderResult`; raises MT5Disconnected on a link loss."""
        self.modify_log.append((ticket, new_sl))
        if not self.connected:
            raise MT5Disconnected("terminal not connected to trade server")
        p = self.positions.get(ticket)
        if p is None or p.closed:
            return OrderResult(retcode=TRADE_RETCODE_INVALID, comment="no position")
        outcome = self.modify_outcomes.pop(0) if self.modify_outcomes else "done"
        if outcome == "done":
            p.sl = new_sl
            return OrderResult(retcode=TRADE_RETCODE_DONE, position=ticket)
        if outcome == "applied_but_unacked":
            p.sl = new_sl                      # broker applied it...
            raise MT5Disconnected("ack lost after broker modified the stop")
        codes = {"reject": TRADE_RETCODE_REJECT, "invalid_stops": TRADE_RETCODE_INVALID_STOPS,
                 "requote": TRADE_RETCODE_REQUOTE, "off_quotes": TRADE_RETCODE_PRICE_OFF}
        if outcome == "disconnect":
            raise MT5Disconnected("link lost during modify (no change applied)")
        return OrderResult(retcode=codes.get(outcome, TRADE_RETCODE_INVALID),
                           position=ticket, comment=outcome)

    def position_close(self, ticket, price=None, reason=None):
        # ``reason`` (R3) is accepted for interface parity with the bridge-backed
        # adapter and ignored by the mock terminal.
        p = self.positions.get(ticket)
        if p is None or p.closed:
            return OrderResult(retcode=TRADE_RETCODE_INVALID, comment="no position")
        if not self.connected:
            raise MT5Disconnected("terminal not connected to trade server")
        info = self.symbols.get(p.symbol)
        close_price = price if price is not None else (
            info.bid if p.type == ORDER_TYPE_BUY else info.ask) if info else 0.0
        p.closed = True
        p.close_price = close_price
        return OrderResult(retcode=TRADE_RETCODE_DONE, position=ticket,
                           price=close_price, volume=p.volume)
