"""EA Bridge HTTP server (`ADR-023` §4) — Python stdlib only, mirroring
`phantom/api.py`'s "explicit route table, no third-party framework"
precedent for a handful of simple routes.

Every route checks the API key first (`validation.check_api_key`);
`Direction`/`RequestKind` enum values are serialized as their plain
string `.value`. A malformed or invalid payload is rejected with 400,
never partially applied.

    POST /ea/heartbeat          -> EA liveness ping
    POST /ea/account            -> EA-reported account snapshot
    POST /ea/tick               -> one live tick
    POST /ea/bars               -> one or more M15/H1/H4/D1 bars
    POST /ea/positions          -> the EA's full current position list
    GET  /ea/commands/poll      -> pending, Phantom-approved commands
    POST /ea/execution/report   -> the EA's report of what happened
    POST /ea/error/report       -> an MQL5-side error
    POST /ea/emergency-stop     -> activate/deactivate the kill switch
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from ..mt5_bridge.models import RequestKind
from ..scanner.models import Direction
from . import validation
from .config import EABridgeConfig
from .engine import EABridgeEngine
from .models import (
    BarMessage,
    EAAccountState,
    ErrorReport,
    ExecutionReport,
    HeartbeatMessage,
    PositionReport,
    SCHEMA_VERSION,
    TickMessage,
)

API_KEY_HEADER = "X-Phantom-Api-Key"


def _parse_datetime(value: Any) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _handle_heartbeat(engine: EABridgeEngine, config: EABridgeConfig, body: dict, now: datetime) -> Tuple[int, dict]:
    reason = validation.validate_inbound_message(body.get("api_key"), body.get("magic_number", -1), config)
    if reason is not None:
        return 401 if "key" in reason else 400, {"error": reason}
    message = HeartbeatMessage(
        schema_version=SCHEMA_VERSION,
        magic_number=body["magic_number"],
        terminal_time=_parse_datetime(body["terminal_time"]) if body.get("terminal_time") else now,
        account_login=body.get("account_login"),
        connected=bool(body.get("connected", True)),
        received_at=now,
    )
    engine.handle_heartbeat(message)
    return 200, {"status": "ok", "emergency_stop": engine.emergency_stop_state.active}


def _handle_account(engine: EABridgeEngine, config: EABridgeConfig, body: dict, now: datetime) -> Tuple[int, dict]:
    reason = validation.validate_inbound_message(body.get("api_key"), body.get("magic_number", -1), config)
    if reason is not None:
        return 401 if "key" in reason else 400, {"error": reason}
    state = EAAccountState(
        schema_version=SCHEMA_VERSION,
        magic_number=body["magic_number"],
        equity=float(body["equity"]),
        balance=float(body["balance"]),
        margin=body.get("margin"),
        free_margin=body.get("free_margin"),
        currency=body.get("currency", "USD"),
        received_at=now,
    )
    engine.handle_account_state(state)
    return 200, {"status": "ok"}


def _handle_tick(engine: EABridgeEngine, config: EABridgeConfig, body: dict, now: datetime) -> Tuple[int, dict]:
    reason = validation.validate_inbound_message(
        body.get("api_key"), body.get("magic_number", config.magic_number), config, symbol=body.get("symbol")
    )
    if reason is not None:
        return 401 if "key" in reason else 400, {"error": reason}
    tick = TickMessage(
        schema_version=SCHEMA_VERSION,
        symbol=body["symbol"],
        bid=body.get("bid"),
        ask=body.get("ask"),
        last=body.get("last"),
        volume=body.get("volume"),
        terminal_time=_parse_datetime(body["terminal_time"]) if body.get("terminal_time") else now,
        received_at=now,
    )
    engine.handle_tick(tick)
    return 200, {"status": "ok"}


def _handle_bars(engine: EABridgeEngine, config: EABridgeConfig, body: dict, now: datetime) -> Tuple[int, dict]:
    reason = validation.validate_inbound_message(body.get("api_key"), body.get("magic_number", config.magic_number), config)
    if reason is not None:
        return 401 if "key" in reason else 400, {"error": reason}
    bars = body.get("bars", [])
    for raw_bar in bars:
        symbol_reason = validation.check_symbol_allowed(raw_bar.get("symbol"), config)
        if symbol_reason is not None:
            return 400, {"error": symbol_reason}
    messages = tuple(
        BarMessage(
            schema_version=SCHEMA_VERSION,
            symbol=raw_bar["symbol"],
            timeframe=raw_bar["timeframe"],
            open=float(raw_bar["open"]),
            high=float(raw_bar["high"]),
            low=float(raw_bar["low"]),
            close=float(raw_bar["close"]),
            volume=float(raw_bar.get("volume", 0.0)),
            bar_time=_parse_datetime(raw_bar["bar_time"]),
            received_at=now,
        )
        for raw_bar in bars
    )
    engine.handle_bars(messages)
    return 200, {"status": "ok", "count": len(messages)}


def _handle_positions(engine: EABridgeEngine, config: EABridgeConfig, body: dict, now: datetime) -> Tuple[int, dict]:
    reason = validation.validate_inbound_message(body.get("api_key"), body.get("magic_number", -1), config)
    if reason is not None:
        return 401 if "key" in reason else 400, {"error": reason}
    positions = tuple(
        PositionReport(
            schema_version=SCHEMA_VERSION,
            position_id=raw["position_id"],
            symbol=raw["symbol"],
            direction=Direction(raw["direction"]),
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


def _handle_poll_commands(
    engine: EABridgeEngine, config: EABridgeConfig, query: Dict[str, list], now: datetime
) -> Tuple[int, dict]:
    api_key = query.get("api_key", [None])[0]
    magic_number = int(query.get("magic_number", ["-1"])[0])
    reason = validation.validate_inbound_message(api_key, magic_number, config)
    if reason is not None:
        return 401 if "key" in reason else 400, {"error": reason}
    commands = engine.poll_commands(now)
    return 200, {
        "emergency_stop": engine.emergency_stop_state.active,
        "commands": [
            {
                "execution_id": c.execution_id,
                "trace_id": c.trace_id,
                "request_kind": c.request_kind.value,
                "symbol": c.symbol,
                "direction": c.direction.value if c.direction is not None else None,
                "lot_size": c.lot_size,
                "stop_loss": c.stop_loss,
                "take_profit": c.take_profit,
                "position_id": c.position_id,
                "close_fraction": c.close_fraction,
                "magic_number": c.magic_number,
                "max_slippage_points": c.max_slippage_points,
                "issued_at": c.issued_at.isoformat(),
            }
            for c in commands
        ],
    }


def _handle_execution_report(engine: EABridgeEngine, config: EABridgeConfig, body: dict, now: datetime) -> Tuple[int, dict]:
    reason = validation.validate_command_execution_report(
        body.get("execution_id", ""), body.get("magic_number", -1), config
    )
    if reason is None:
        reason = validation.check_api_key(body.get("api_key"), config)
    if reason is not None:
        return 401 if "key" in reason else 400, {"error": reason}
    report = ExecutionReport(
        schema_version=SCHEMA_VERSION,
        execution_id=body["execution_id"],
        magic_number=body["magic_number"],
        success=bool(body.get("success", False)),
        broker_ticket=body.get("broker_ticket"),
        filled_price=body.get("filled_price"),
        filled_size=body.get("filled_size"),
        reason=body.get("reason"),
        reported_at=now,
    )
    recorded = engine.handle_execution_report(report)
    return 200, {"status": "ok", "recorded": recorded}


def _handle_error_report(engine: EABridgeEngine, config: EABridgeConfig, body: dict, now: datetime) -> Tuple[int, dict]:
    reason = validation.validate_inbound_message(body.get("api_key"), body.get("magic_number", -1), config)
    if reason is not None:
        return 401 if "key" in reason else 400, {"error": reason}
    error = ErrorReport(
        schema_version=SCHEMA_VERSION,
        magic_number=body["magic_number"],
        code=body.get("code"),
        message=body.get("message", ""),
        context=body.get("context"),
        reported_at=now,
    )
    engine.handle_error(error)
    return 200, {"status": "ok"}


def _handle_emergency_stop(engine: EABridgeEngine, config: EABridgeConfig, body: dict, now: datetime) -> Tuple[int, dict]:
    reason = validation.check_api_key(body.get("api_key"), config)
    if reason is not None:
        return 401, {"error": reason}
    if bool(body.get("active", True)):
        state = engine.activate_emergency_stop(body.get("reason", "operator_requested"), now)
    else:
        state = engine.deactivate_emergency_stop()
    return 200, {"active": state.active, "reason": state.reason}


_POST_ROUTES: Dict[str, Callable[[EABridgeEngine, EABridgeConfig, dict, datetime], Tuple[int, dict]]] = {
    "/ea/heartbeat": _handle_heartbeat,
    "/ea/account": _handle_account,
    "/ea/tick": _handle_tick,
    "/ea/bars": _handle_bars,
    "/ea/positions": _handle_positions,
    "/ea/execution/report": _handle_execution_report,
    "/ea/error/report": _handle_error_report,
    "/ea/emergency-stop": _handle_emergency_stop,
}


def make_handler(engine: EABridgeEngine, config: EABridgeConfig, clock: Callable[[], datetime]):
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
            if parsed.path != "/ea/commands/poll":
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


def serve(
    engine: EABridgeEngine,
    config: EABridgeConfig,
    clock: Optional[Callable[[], datetime]] = None,
    host: str = "127.0.0.1",
    port: int = 8787,
) -> ThreadingHTTPServer:
    resolved_clock = clock or (lambda: datetime.now(timezone.utc))
    return ThreadingHTTPServer((host, port), make_handler(engine, config, resolved_clock))


def registered_routes():
    """Expose the route table for diagnostics / the validation suite."""
    routes = [f"GET {path}" for path in ("/ea/commands/poll",)]
    routes.extend(f"POST {path}" for path in _POST_ROUTES)
    return routes


__all__ = ["make_handler", "serve", "registered_routes", "API_KEY_HEADER"]
