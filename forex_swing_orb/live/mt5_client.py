"""MT5 client abstraction (Phase 8A) — the single seam to MetaTrader 5.

The live providers depend ONLY on this narrow, duck-typed client — never on the
``MetaTrader5`` package directly — so provider logic is testable off-Windows with
:class:`FakeMt5Client`. :func:`create_real_client` lazily imports MetaTrader5 at
deployment (Windows only); importing this module never requires the package.

The MT5 package uses a local IPC pipe to a running terminal — no HTTP, no sockets,
no scraping. That is the ONLY external integration these providers use.
"""

from __future__ import annotations

# canonical timeframe labels -> MetaTrader5 timeframe enum values (fixed by MT5)
_MT5_TF = {"M15": 15, "H1": 16385, "H4": 16388, "D1": 16408}

# MetaTrader5 account trade modes
ACCOUNT_TRADE_MODE_DEMO = 0
ACCOUNT_TRADE_MODE_CONTEST = 1
ACCOUNT_TRADE_MODE_REAL = 2
# MetaTrader5 symbol trade modes
SYMBOL_TRADE_MODE_DISABLED = 0
SYMBOL_TRADE_MODE_FULL = 4
POSITION_TYPE_BUY = 0
POSITION_TYPE_SELL = 1
# MetaTrader5 deal entry directions (history classification; READ-ONLY use only)
DEAL_ENTRY_IN = 0
DEAL_ENTRY_OUT = 1
DEAL_ENTRY_INOUT = 2
DEAL_ENTRY_OUT_BY = 3

# MetaTrader5 deal types (ENUM_DEAL_TYPE). Every balance-affecting deal encodes its
# balance delta in (profit + commission + swap + fee), so the daily-anchor cold-start
# reconstruction needs the exhaustive KNOWN set only to FAIL CLOSED on any value
# outside it (an unrecognized broker balance event -> unverifiable). READ-ONLY use.
DEAL_TYPE_BUY = 0
DEAL_TYPE_SELL = 1
DEAL_TYPE_BALANCE = 2                 # deposit / withdrawal
DEAL_TYPE_CREDIT = 3
DEAL_TYPE_CHARGE = 4
DEAL_TYPE_CORRECTION = 5
DEAL_TYPE_BONUS = 6
DEAL_TYPE_COMMISSION = 7
DEAL_TYPE_COMMISSION_DAILY = 8
DEAL_TYPE_COMMISSION_MONTHLY = 9
DEAL_TYPE_COMMISSION_AGENT_DAILY = 10
DEAL_TYPE_COMMISSION_AGENT_MONTHLY = 11
DEAL_TYPE_INTEREST = 12
DEAL_TYPE_BUY_CANCELED = 13
DEAL_TYPE_SELL_CANCELED = 14
DEAL_DIVIDEND = 15
DEAL_DIVIDEND_FRANKED = 16
DEAL_TAX = 17
# The exhaustive documented set (0..17). Any deal.type outside this -> fail closed.
KNOWN_DEAL_TYPES = frozenset(range(0, 18))


def create_real_client(*, terminal_path=None, login=None, server=None,
                       password=None):  # pragma: no cover - Windows/terminal only
    """Wrap the live MetaTrader5 package. Raises a clear error off-Windows / when
    the package or terminal is unavailable. NEVER imported at module load.

    Optional connection parameters (terminal path / login / server / password) are
    forwarded to ``MetaTrader5.initialize`` when supplied; omitting them attaches to
    an already-running, already-logged-in terminal. The password is used only for
    the local IPC login and is never persisted or logged here."""
    try:
        import MetaTrader5 as _mt5  # noqa: N813
    except Exception as exc:
        raise RuntimeError(
            "MetaTrader5 package unavailable — live providers run only on a "
            "Windows host with MetaTrader5 installed and a terminal running "
            f"({exc!r})")
    init_kwargs = {}
    if terminal_path:
        init_kwargs["path"] = terminal_path
    if login is not None:
        init_kwargs["login"] = int(login)
    if server:
        init_kwargs["server"] = server
    if password:
        init_kwargs["password"] = password
    if not _mt5.initialize(**init_kwargs):
        raise RuntimeError(f"MetaTrader5.initialize() failed: {_mt5.last_error()!r}")
    return _RealMt5Client(_mt5)


class _RealMt5Client:  # pragma: no cover - requires a live terminal
    def __init__(self, mt5):
        self._mt5 = mt5

    def timeframe(self, label):
        return getattr(self._mt5, "TIMEFRAME_" + label)

    def copy_rates_from_pos(self, symbol, tf_label, start, count):
        return self._mt5.copy_rates_from_pos(symbol, self.timeframe(tf_label), start, count)

    def symbol_info(self, symbol):
        return self._mt5.symbol_info(symbol)

    def account_info(self):
        return self._mt5.account_info()

    def positions_get(self, symbol=None):
        return self._mt5.positions_get(symbol=symbol) if symbol else self._mt5.positions_get()

    def terminal_info(self):
        return self._mt5.terminal_info()

    def history_deals_get(self, position=None):
        """READ-ONLY: closed-deal history for one broker position id (no trading).

        Delegates to ``MetaTrader5.history_deals_get(position=...)``, which selects
        and returns every deal (entry + exit legs) belonging to that position id.
        Returns the MT5 tuple, or ``None`` when the terminal reports no data /
        the query is rejected — the caller MUST treat ``None`` as *unknown*, never
        as a confirmed close."""
        return self._mt5.history_deals_get(position=position)

    def history_deals_range(self, date_from, date_to):  # pragma: no cover - live terminal
        """READ-ONLY: all deals with server time in [date_from, date_to] (no trading).

        Delegates to ``MetaTrader5.history_deals_get(date_from, date_to)`` (the
        time-range overload). Returns the MT5 tuple (possibly empty = a successful
        query with zero deals), or ``None`` when the query is rejected/errors — the
        caller MUST treat ``None`` as *unknown coverage* and FAIL CLOSED, never as
        proof of zero deals."""
        return self._mt5.history_deals_get(date_from, date_to)


# --------------------------------------------------------------------------- #
# Deterministic test double (mirrors the MetaTrader5 API surface used above).
# --------------------------------------------------------------------------- #
class _Deal:
    """Deterministic stand-in for an MT5 history deal (read-only fields only)."""

    __slots__ = ("ticket", "order", "position_id", "time", "type", "entry",
                 "volume", "price", "symbol", "reason", "profit",
                 "commission", "swap", "fee")

    def __init__(self, position_id, entry, volume, price, *, deal_type=0,
                 ticket=0, order=0, time=0, symbol="", reason=0, profit=0.0,
                 commission=0.0, swap=0.0, fee=0.0):
        self.position_id = position_id
        self.entry = entry
        self.volume = volume
        self.price = price
        self.type = deal_type
        self.ticket = ticket
        self.order = order
        self.time = time
        self.symbol = symbol
        self.reason = reason
        self.profit = profit
        self.commission = commission          # broker commission (balance delta component)
        self.swap = swap                      # swap/rollover (balance delta component)
        self.fee = fee                        # exchange/other fee (balance delta component)

    def __getitem__(self, k):        # MT5 deals behave like structured records
        return getattr(self, k)



class _Rate:
    __slots__ = ("time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume")

    def __init__(self, time, o, h, l, c):
        self.time = time; self.open = o; self.high = h; self.low = l; self.close = c
        self.tick_volume = 0; self.spread = 0; self.real_volume = 0

    def __getitem__(self, k):        # MT5 rates behave like structured records
        return getattr(self, k)


class FakeMt5Client:
    """In-memory MT5 client for tests. No networking. Deterministic."""

    def __init__(self):
        self.rates = {}          # (symbol, tf_label) -> list[_Rate]
        self.symbols = {}        # symbol -> object with MT5 symbol_info fields
        self.account = None      # object with account_info fields
        self.positions = []      # list of objects with position fields
        self.deals = {}          # position_id -> list[_Deal] (closed-deal history)
        self.terminal = type("T", (), {"connected": True, "trade_allowed": True})()

    def timeframe(self, label):
        return _MT5_TF[label]

    def add_rates(self, symbol, tf_label, rows):
        self.rates[(symbol, tf_label)] = [
            _Rate(int(t), o, h, l, c) for (t, o, h, l, c) in rows]

    def copy_rates_from_pos(self, symbol, tf_label, start, count):
        data = self.rates.get((symbol, tf_label))
        if data is None:
            return None
        return list(data[start:start + count]) if count else list(data[start:])

    def symbol_info(self, symbol):
        return self.symbols.get(symbol)

    def account_info(self):
        return self.account

    def positions_get(self, symbol=None):
        if symbol is not None:
            return tuple(p for p in self.positions if p.symbol == symbol)
        return tuple(self.positions)

    def terminal_info(self):
        return self.terminal

    def add_deal(self, position_id, entry, volume, price, **kw):
        """Record one closed deal for ``position_id`` (test helper; read-only API)."""
        self.deals.setdefault(position_id, []).append(
            _Deal(position_id, entry, volume, price, **kw))

    def history_deals_get(self, position=None):
        """READ-ONLY closed-deal history. Mirrors the MT5 tuple return; an unknown
        position id yields an empty tuple (query succeeded, no deals)."""
        if position is None:
            return tuple(d for lst in self.deals.values() for d in lst)
        return tuple(self.deals.get(position, ()))

    # Set to True in a test to simulate a rejected/errored range query (-> None).
    history_range_fails = False

    def history_deals_range(self, date_from, date_to):
        """READ-ONLY deals with POSIX ``time`` in [date_from, date_to]. Accepts
        datetimes or POSIX seconds; returns a tuple (possibly empty) on success, or
        None when ``history_range_fails`` is set (simulated query rejection)."""
        if self.history_range_fails:
            return None
        def _sec(x):
            return int(x.timestamp()) if hasattr(x, "timestamp") else int(x)
        lo, hi = _sec(date_from), _sec(date_to)
        return tuple(d for lst in self.deals.values() for d in lst
                     if lo <= int(d.time) <= hi)
