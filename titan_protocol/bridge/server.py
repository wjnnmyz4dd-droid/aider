"""TitanProtocolEA HTTP server (Phase 1) -- Python stdlib only.

Every route validates before acknowledging (`validation.py`, run first);
a malformed or invalid payload is rejected with 400/401, never
partially applied. `Direction`/`CommandKind` enum values are serialized
as their plain string `.value`.

    POST /bridge/heartbeat           -> EA liveness ping
    POST /bridge/account             -> EA-reported account snapshot
    POST /bridge/positions           -> the EA's full open-position list
    POST /bridge/orders              -> the EA's full pending-order list
    GET  /bridge/commands/poll       -> pending, already-submitted commands
    POST /bridge/execution/report    -> the EA's report of what happened
    POST /bridge/trade-transaction   -> independent MT5-native trade-event mirror
    POST /bridge/error               -> an MQL5-side error
    POST /bridge/emergency-stop      -> activate/deactivate the transport-level halt
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from . import validation
from .config import BridgeConfig
from .engine import BridgeEngine
from .models import (
    SCHEMA_VERSION,
    AccountState,
    ErrorReport,
    ExecutionReport,
    HeartbeatMessage,
    PendingOrderReport,
    PositionDirection,
    PositionReport,
    TradeTransactionReport,
)

API_KEY_HEADER = "X-Titan-Protocol-Api-Key"


def _parse_datetime(value: Any) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _handle_heartbeat(engine: BridgeEngine, config: BridgeConfig, body: dict, now: datetime) -> Tuple[int, dict]:
    reason = validation.validate_inbound_message(body.get("api_key"), body.get("magic_number", -1), config)
    if reason is not None:
        return (401 if "KEY" in reason.value else 400), {"error": reason.value}
    message = HeartbeatMessage(
        schema_version=SCHEMA_VERSION,
        magic_number=body["magic_number"],
        account_login=body.get("account_login"),
        terminal_connected=bool(body.get("terminal_connected", True)),
        received_at=now,
    )
    engine.handle_heartbeat(message)
    return 200, {"status": "ok", "emergency_stop": engine.emergency_stop_state.active}


def _handle_account(engine: BridgeEngine, config: BridgeConfig, body: dict, now: datetime) -> Tuple[int, dict]:
    reason = validation.validate_inbound_message(body.get("api_key"), body.get("magic_number", -1), config)
    if reason is not None:
        return (401 if "KEY" in reason.value else 400), {"error": reason.value}
    state = AccountState(
        schema_version=SCHEMA_VERSION,
        magic_number=body["magic_number"],
        balance=float(body["balance"]),
        equity=float(body["equity"]),
        margin=body.get("margin"),
        free_margin=body.get("free_margin"),
        currency=body.get("currency", "USD"),
        leverage=body.get("leverage"),
        received_at=now,
    )
    engine.handle_account_state(state)
    return 200, {"status": "ok"}


def _handle_positions(engine: BridgeEngine, config: BridgeConfig, body: dict, now: datetime) -> Tuple[int, dict]:
    reason = validation.validate_inbound_message(body.get("api_key"), body.get("magic_number", -1), config)
    if reason is not None:
        return (401 if "KEY" in reason.value else 400), {"error": reason.value}
    positions = tuple(
        PositionReport(
            schema_version=SCHEMA_VERSION,
            position_id=raw["position_id"],
            symbol=raw["symbol"],
            direction=PositionDirection(raw["direction"]),
            volume=float(raw["volume"]),
            open_price=float(raw["open_price"]),
            stop_loss=raw.get("stop_loss"),
            take_profit=raw.get("take_profit"),
            unrealized_pnl=raw.get("unrealized_pnl"),
            magic_number=body["magic_number"],
            received_at=now,
        )
        for raw in body.get("positions", [])
    )
    engine.handle_positions(positions)
    return 200, {"status": "ok", "count": len(positions)}


def _handle_orders(engine: BridgeEngine, config: BridgeConfig, body: dict, now: datetime) -> Tuple[int, dict]:
    reason = validation.validate_inbound_message(body.get("api_key"), body.get("magic_number", -1), config)
    if reason is not None:
        return (401 if "KEY" in reason.value else 400), {"error": reason.value}
    orders = tuple(
        PendingOrderReport(
            schema_version=SCHEMA_VERSION,
            order_id=raw["order_id"],
            symbol=raw["symbol"],
            order_type=raw["order_type"],
            volume=float(raw["volume"]),
            price=float(raw["price"]),
            stop_loss=raw.get("stop_loss"),
            take_profit=raw.get("take_profit"),
            magic_number=body["magic_number"],
            received_at=now,
        )
        for raw in body.get("orders", [])
    )
    engine.handle_pending_orders(orders)
    return 200, {"status": "ok", "count": len(orders)}


def _handle_poll_commands(
    engine: BridgeEngine, config: BridgeConfig, query: Dict[str, list], now: datetime
) -> Tuple[int, dict]:
    api_key = query.get("api_key", [None])[0]
    magic_number = int(query.get("magic_number", ["-1"])[0])
    reason = validation.validate_inbound_message(api_key, magic_number, config)
    if reason is not None:
        return (401 if "KEY" in reason.value else 400), {"error": reason.value}
    commands = engine.poll_commands(now)
    return 200, {
        "emergency_stop": engine.emergency_stop_state.active,
        "commands": [
            {
                "correlation_id": c.correlation_id,
                "command_kind": c.command_kind.value,
                "symbol": c.symbol,
                "volume": c.volume,
                "stop_loss": c.stop_loss,
                "take_profit": c.take_profit,
                "position_id": c.position_id,
                "close_volume": c.close_volume,
                "magic_number": c.magic_number,
                "max_slippage_points": c.max_slippage_points,
                "issued_at": c.issued_at.isoformat(),
            }
            for c in commands
        ],
    }


def _handle_execution_report(engine: BridgeEngine, config: BridgeConfig, body: dict, now: datetime) -> Tuple[int, dict]:
    reason = validation.validate_command_execution_report(
        body.get("correlation_id", ""), body.get("magic_number", -1), config
    )
    if reason is None:
        reason = validation.check_api_key(body.get("api_key"), config)
    if reason is not None:
        return (401 if "KEY" in reason.value else 400), {"error": reason.value}
    report = ExecutionReport(
        schema_version=SCHEMA_VERSION,
        correlation_id=body["correlation_id"],
        magic_number=body["magic_number"],
        success=bool(body.get("success", False)),
        broker_ticket=body.get("broker_ticket"),
        filled_price=body.get("filled_price"),
        filled_volume=body.get("filled_volume"),
        error_code=body.get("error_code"),
        reported_at=now,
    )
    recorded = engine.handle_execution_report(report)
    return 200, {"status": "ok", "recorded": recorded}


def _handle_trade_transaction(engine: BridgeEngine, config: BridgeConfig, body: dict, now: datetime) -> Tuple[int, dict]:
    reason = validation.validate_inbound_message(body.get("api_key"), body.get("magic_number", -1), config)
    if reason is not None:
        return (401 if "KEY" in reason.value else 400), {"error": reason.value}
    report = TradeTransactionReport(
        schema_version=SCHEMA_VERSION,
        magic_number=body["magic_number"],
        symbol=body.get("symbol"),
        deal_ticket=body.get("deal_ticket"),
        order_ticket=body.get("order_ticket"),
        transaction_type=body.get("transaction_type", "UNKNOWN"),
        volume=body.get("volume"),
        price=body.get("price"),
        reported_at=now,
    )
    matched = engine.handle_trade_transaction(report)
    return 200, {"status": "ok", "matched_known_execution": matched}


def _handle_error_report(engine: BridgeEngine, config: BridgeConfig, body: dict, now: datetime) -> Tuple[int, dict]:
    reason = validation.validate_inbound_message(body.get("api_key"), body.get("magic_number", -1), config)
    if reason is not None:
        return (401 if "KEY" in reason.value else 400), {"error": reason.value}
    error = ErrorReport(
        schema_version=SCHEMA_VERSION,
        magic_number=body["magic_number"],
        error_code=body.get("error_code", "UNKNOWN"),
        message=body.get("message", ""),
        context=body.get("context"),
        reported_at=now,
    )
    engine.handle_error(error)
    return 200, {"status": "ok"}


def _handle_emergency_stop(engine: BridgeEngine, config: BridgeConfig, body: dict, now: datetime) -> Tuple[int, dict]:
    reason = validation.check_api_key(body.get("api_key"), config)
    if reason is not None:
        return 401, {"error": reason.value}
    if bool(body.get("active", True)):
        state = engine.activate_emergency_stop(body.get("reason", "operator_requested"), now)
    else:
        state = engine.deactivate_emergency_stop()
    return 200, {"active": state.active, "reason": state.reason}


_POST_ROUTES: Dict[str, Callable[[BridgeEngine, BridgeConfig, dict, datetime], Tuple[int, dict]]] = {
    "/bridge/heartbeat": _handle_heartbeat,
    "/bridge/account": _handle_account,
    "/bridge/positions": _handle_positions,
    "/bridge/orders": _handle_orders,
    "/bridge/execution/report": _handle_execution_report,
    "/bridge/trade-transaction": _handle_trade_transaction,
    "/bridge/error": _handle_error_report,
    "/bridge/emergency-stop": _handle_emergency_stop,
}


def make_handler(engine: BridgeEngine, config: BridgeConfig, clock: Callable[[], datetime]):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):  # silence default stderr logging
            pass

        def _send(self, status: int, body: dict) -> None:
            payload = json.dumps(body, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path != "/bridge/commands/poll":
                self._send(404, {"error": "not found", "path": parsed.path})
                return
            query = parse_qs(parsed.query)
            provided_key = self.headers.get(API_KEY_HEADER)
            if provided_key is not None and "api_key" not in query:
                query["api_key"] = [provided_key]
            try:
                status, body = _handle_poll_commands(engine, config, query, clock())
            except Exception as exc:  # pragma: no cover - defensive
                self._send(500, {"error": str(exc)})
                return
            self._send(status, body)

        def do_POST(self):
            parsed = urlparse(self.path)
            handler = _POST_ROUTES.get(parsed.path)
            if handler is None:
                self._send(404, {"error": "not found", "path": parsed.path})
                return
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except (ValueError, UnicodeDecodeError):
                self._send(400, {"error": "invalid_json_body"})
                return
            if not isinstance(body, dict):
                self._send(400, {"error": "json_object_required"})
                return
            provided_key = self.headers.get(API_KEY_HEADER)
            if provided_key is not None:
                body.setdefault("api_key", provided_key)
            try:
                status, response_body = handler(engine, config, body, clock())
            except (KeyError, ValueError, TypeError) as exc:
                self._send(400, {"error": f"invalid_payload:{exc}"})
                return
            except Exception as exc:  # pragma: no cover - defensive
                self._send(500, {"error": str(exc)})
                return
            self._send(status, response_body)

    return Handler


class _BridgeHTTPServer(ThreadingHTTPServer):
    """`ThreadingHTTPServer`'s default `request_queue_size` (5, inherited
    from `socketserver.TCPServer`) is the `socket.listen()` backlog --
    how many not-yet-accepted connections the OS will hold before
    resetting new ones. Under Phase 1.5 stress validation (60 concurrent
    client threads), the default size produced reproducible "Connection
    reset by peer" errors; raising it eliminated them in an isolated,
    controlled A/B test with no other change. A real MT5 deployment is a
    single EA making sequential requests, far below this bound, but the
    fix costs nothing and removes a real, reproduced failure mode under
    burst load (e.g. several telemetry POSTs firing close together)."""

    request_queue_size = 128


def serve(
    engine: BridgeEngine,
    config: BridgeConfig,
    clock: Optional[Callable[[], datetime]] = None,
    host: str = "127.0.0.1",
    port: int = 8787,
) -> ThreadingHTTPServer:
    resolved_clock = clock or (lambda: datetime.now(timezone.utc))
    return _BridgeHTTPServer((host, port), make_handler(engine, config, resolved_clock))


def registered_routes():
    """Expose the route table for diagnostics / the validation suite."""
    routes = [f"GET {path}" for path in ("/bridge/commands/poll",)]
    routes.extend(f"POST {path}" for path in _POST_ROUTES)
    return routes


__all__ = ["make_handler", "serve", "registered_routes", "API_KEY_HEADER"]
