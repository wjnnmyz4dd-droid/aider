"""A real `BrokerAdapter` backed by the official `MetaTrader5` Python
package (ADR-008 §16's own acknowledgement that a real adapter is future
work, `ADR-015`'s Adapter Forbidden Responsibilities).

**Translation only.** Every method here does exactly one of: call the
injected MT5 client, or perform a direct field mapping between an
already-fully-decided `BrokerRequest` (produced by `checks.translate_order`/
`translate_position_adjustment`/`translate_position_close` — never by this
module) and the MT5 API's own request/reply shape. Nothing here computes a
score, a size, an SL/TP, or a verdict; nothing here decides whether to
trade — nothing here differs from what `FakeBrokerAdapter` was already
documented to stand in for.

**Why the MT5 client is an injectable constructor parameter.** The
official `MetaTrader5` package only functions against a running MT5
terminal (Windows, or Wine) — it cannot be installed or exercised in every
CI/dev environment. Exactly like every other stage's own boundary object
already gets constructor-injected (a `BrokerAdapter`, a `PrometheusReadPort`,
a `RecoveryActionExecutor`), the underlying vendor client here is injected
too: `MT5Adapter(mt5_module=...)` accepts anything exposing the small
subset of the real module's surface this file actually calls
(`initialize`, `shutdown`, `terminal_info`, `account_info`, `positions_get`,
`symbol_info_tick`, `order_send`, `TRADE_ACTION_DEAL`, `TRADE_ACTION_SLTP`,
`ORDER_TYPE_BUY`, `ORDER_TYPE_SELL`, `TRADE_RETCODE_DONE`, `last_error`).
When omitted, the real `MetaTrader5` package is imported lazily inside
`connect()` — never at module import time — so this module remains
importable (and its translation logic remains unit-testable via an
injected fake) in an environment where the real package cannot be
installed at all.

**Credentials.** Login/password/server/terminal-path are read from
environment variables (`MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`,
`MT5_TERMINAL_PATH`) unless passed explicitly to the constructor — never
hardcoded, never logged (ADR-013 §12's "Credentials... are scoped" applied
here to the sibling MT5 Bridge connection, ADR-008 §16's own reference to
`ADR-002`-`ADR-007`'s existing credential-scoping precedent).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from ..scanner.models import Direction
from .broker_adapter import BrokerAdapter
from .models import (
    BrokerAcknowledgement,
    BrokerError,
    BrokerRequest,
    ExecutionReceipt,
    RequestKind,
    SCHEMA_VERSION,
)

_DIRECTION_TO_ORDER_TYPE = {
    Direction.UP: "ORDER_TYPE_BUY",
    Direction.DOWN: "ORDER_TYPE_SELL",
}


def _import_metatrader5() -> Any:
    try:
        import MetaTrader5 as mt5  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "MT5Adapter requires the official 'MetaTrader5' package and a "
            "running MT5 terminal; install it or pass mt5_module= for testing."
        ) from exc
    return mt5


class MT5Adapter(BrokerAdapter):
    """Translates `BrokerRequest`/broker-reply shapes to and from the real
    `MetaTrader5` API. Holds no idempotency/connection-state logic of its
    own (that remains `MT5Bridge`'s job, per `engine.py`) — this class only
    ever executes exactly what it is asked to submit or query."""

    def __init__(
        self,
        mt5_module: Optional[Any] = None,
        login: Optional[int] = None,
        password: Optional[str] = None,
        server: Optional[str] = None,
        terminal_path: Optional[str] = None,
        magic_number: int = 20260706,
        deviation_points: int = 20,
    ) -> None:
        self._mt5 = mt5_module
        self._login = login if login is not None else _env_int("MT5_LOGIN")
        self._password = password if password is not None else os.environ.get("MT5_PASSWORD")
        self._server = server if server is not None else os.environ.get("MT5_SERVER")
        self._terminal_path = terminal_path if terminal_path is not None else os.environ.get("MT5_TERMINAL_PATH")
        self._magic_number = magic_number
        self._deviation_points = deviation_points
        # execution_id -> (broker order/deal ticket, trace_id), so
        # poll_execution can look up what it submitted without
        # re-deriving anything.
        self._tickets: Dict[str, Tuple[int, str]] = {}

    def _client(self) -> Any:
        if self._mt5 is None:
            self._mt5 = _import_metatrader5()
        return self._mt5

    # -- Connection (ADR-008 §6) ----------------------------------------

    def connect(self) -> bool:
        mt5 = self._client()
        kwargs: Dict[str, Any] = {}
        if self._terminal_path:
            kwargs["path"] = self._terminal_path
        if self._login is not None:
            kwargs["login"] = self._login
        if self._password is not None:
            kwargs["password"] = self._password
        if self._server is not None:
            kwargs["server"] = self._server
        return bool(mt5.initialize(**kwargs))

    def disconnect(self) -> None:
        self._client().shutdown()

    def heartbeat(self) -> bool:
        info = self._client().terminal_info()
        return bool(info is not None and getattr(info, "connected", False))

    # -- Submission (ADR-008 §2, §5, Amendment 1) -----------------------

    def send_request(self, request: BrokerRequest) -> "BrokerAcknowledgement | BrokerError":
        mt5 = self._client()
        if request.request_kind == RequestKind.OPEN:
            mt5_request, reason = self._build_open_request(mt5, request)
        elif request.request_kind == RequestKind.ADJUST:
            mt5_request, reason = self._build_adjust_request(mt5, request)
        else:
            mt5_request, reason = self._build_close_request(mt5, request)

        if reason is not None:
            return BrokerError(
                schema_version=SCHEMA_VERSION,
                execution_id=request.execution_id,
                trace_id=request.trace_id,
                request_kind=request.request_kind,
                reason=reason,
                timestamp=request.timestamp,
            )

        result = mt5.order_send(mt5_request)
        return self._translate_order_send_result(result, request)

    def _build_open_request(self, mt5: Any, request: BrokerRequest) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        order_type_name = _DIRECTION_TO_ORDER_TYPE.get(request.direction)
        if order_type_name is None:
            return None, f"unmappable_direction:{request.direction}"
        tick = mt5.symbol_info_tick(request.symbol)
        if tick is None:
            return None, "no_tick_for_symbol"
        price = tick.ask if order_type_name == "ORDER_TYPE_BUY" else tick.bid
        return (
            {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": request.symbol,
                "volume": request.lot_size,
                "type": getattr(mt5, order_type_name),
                "price": price,
                "sl": request.stop_loss or 0.0,
                "tp": request.take_profit or 0.0,
                "deviation": self._deviation_points,
                "magic": self._magic_number,
                "comment": request.execution_id,
            },
            None,
        )

    def _build_adjust_request(self, mt5: Any, request: BrokerRequest) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        position = self._find_position(mt5, request.position_id)
        if position is None:
            return None, "position_not_found"
        return (
            {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": position.ticket,
                "symbol": position.symbol,
                "sl": request.stop_loss if request.stop_loss is not None else position.sl,
                "tp": request.take_profit if request.take_profit is not None else position.tp,
                "magic": self._magic_number,
                "comment": request.execution_id,
            },
            None,
        )

    def _build_close_request(self, mt5: Any, request: BrokerRequest) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        position = self._find_position(mt5, request.position_id)
        if position is None:
            return None, "position_not_found"
        closing_buy = position.type == mt5.ORDER_TYPE_SELL
        order_type = mt5.ORDER_TYPE_BUY if closing_buy else mt5.ORDER_TYPE_SELL
        tick = mt5.symbol_info_tick(position.symbol)
        if tick is None:
            return None, "no_tick_for_symbol"
        price = tick.ask if closing_buy else tick.bid
        volume = position.volume * (request.close_fraction or 1.0)
        return (
            {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": position.symbol,
                "volume": volume,
                "type": order_type,
                "position": position.ticket,
                "price": price,
                "deviation": self._deviation_points,
                "magic": self._magic_number,
                "comment": request.execution_id,
            },
            None,
        )

    def _find_position(self, mt5: Any, position_id: Optional[str]) -> Optional[Any]:
        if not position_id:
            return None
        try:
            ticket = int(position_id)
        except (TypeError, ValueError):
            return None
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return None
        return positions[0]

    def _translate_order_send_result(
        self, result: Any, request: BrokerRequest
    ) -> "BrokerAcknowledgement | BrokerError":
        mt5 = self._client()
        if result is None:
            reason = f"order_send_returned_none:{mt5.last_error()}"
            return BrokerError(
                schema_version=SCHEMA_VERSION,
                execution_id=request.execution_id,
                trace_id=request.trace_id,
                request_kind=request.request_kind,
                reason=reason,
                timestamp=request.timestamp,
            )

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return BrokerError(
                schema_version=SCHEMA_VERSION,
                execution_id=request.execution_id,
                trace_id=request.trace_id,
                request_kind=request.request_kind,
                reason=f"mt5_retcode_{result.retcode}:{getattr(result, 'comment', '')}",
                timestamp=request.timestamp,
            )

        ticket = getattr(result, "order", None) or getattr(result, "deal", None)
        if ticket:
            self._tickets[request.execution_id] = (ticket, request.trace_id)
        return BrokerAcknowledgement(
            schema_version=SCHEMA_VERSION,
            execution_id=request.execution_id,
            trace_id=request.trace_id,
            request_kind=request.request_kind,
            broker_ref=str(ticket) if ticket else None,
            timestamp=request.timestamp,
        )

    # -- Execution polling (ADR-008 §5, §7) ------------------------------

    def poll_execution(self, execution_id: str) -> Optional["ExecutionReceipt | BrokerError"]:
        mt5 = self._client()
        entry = self._tickets.get(execution_id)
        if entry is None:
            return None
        ticket, trace_id = entry
        deals = mt5.history_deals_get(ticket=ticket)
        if not deals:
            return None
        deal = deals[0]
        return ExecutionReceipt(
            schema_version=SCHEMA_VERSION,
            execution_id=execution_id,
            trace_id=trace_id,
            request_kind=RequestKind.OPEN,
            broker_ref=str(ticket),
            filled_price=getattr(deal, "price", None),
            filled_size=getattr(deal, "volume", None),
            timestamp=datetime.fromtimestamp(getattr(deal, "time", 0), tz=timezone.utc),
        )

    # -- State queries (ADR-008 §9) ---------------------------------------

    def query_open_position_ids(self) -> Tuple[str, ...]:
        positions = self._client().positions_get()
        if not positions:
            return ()
        return tuple(str(p.ticket) for p in positions)

    def query_account_equity(self) -> Optional[float]:
        info = self._client().account_info()
        return float(info.equity) if info is not None else None


def _env_int(name: str) -> Optional[int]:
    value = os.environ.get(name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


__all__ = ["MT5Adapter"]
