"""Native MQL5-socket transport for the TitanProtocolEA bridge (ADR-034).

A substrate swap only -- every message shape, every validation check
(`validation.py`), and every `BridgeEngine` method this module calls are
exactly the ones `server.py`'s HTTP transport already uses, unmodified.
This module's only job is: frame bytes on a persistent TCP connection,
authenticate/replay-protect at the frame level, and dispatch each
decoded message to the same route-handler functions `server.py` already
defines, via the same `(engine, config, body, now) -> (status, body)`
contract those functions already have.

Wire format: each message is a 4-byte big-endian length prefix followed
by that many bytes of UTF-8 JSON -- chosen (over newline-delimited JSON)
so a message's exact byte length is known before any of its payload is
read, letting `socket_max_message_bytes` be enforced before the payload
is ever buffered.

Envelope (both directions):
    {"seq": <int>, "route": <str>, "body": {...}}    -- request, EA -> Bridge
    {"seq": <int>, "status": <int>, "body": {...}}   -- response, Bridge -> EA
    (`route` is absent from responses; `status` is absent from requests.)

`seq` must strictly increase within one TCP connection -- a fresh
connection resets the sequence (a new session), a replayed or duplicated
frame (seq <= the last one accepted on this connection) is rejected. This
is a transport-level replay guard, independent of and in addition to
`command_queue.py`'s existing `correlation_id`-keyed idempotency, which
guards command submission specifically; this guards every message type
carried over this substrate, including ones (heartbeat, account state)
that carry no correlation_id of their own.
"""

from __future__ import annotations

import json
import logging
import socket
import socketserver
import struct
import threading
from datetime import datetime, timezone
from typing import Callable, Optional, Tuple

from . import server as _http_server
from .config import BridgeConfig
from .engine import BridgeEngine
from .metrics import BridgeMetrics

logger = logging.getLogger("titan_protocol.bridge.socket_transport")

_LENGTH_PREFIX = struct.Struct(">I")
_RECV_CHUNK_BYTES = 4096

# Maps a socket envelope's "route" string onto the exact HTTP path
# `server._POST_ROUTES` already dispatches -- one more name added
# ("commands_poll", handled separately below since its HTTP form is a
# GET with query params, not a POST body) but zero new handler logic.
_ROUTE_TO_HTTP_PATH = {
    "heartbeat": "/bridge/heartbeat",
    "account": "/bridge/account",
    "positions": "/bridge/positions",
    "orders": "/bridge/orders",
    "execution_report": "/bridge/execution/report",
    "trade_transaction": "/bridge/trade-transaction",
    "error": "/bridge/error",
    "emergency_stop": "/bridge/emergency-stop",
    "market_data": "/bridge/market-data",
}
_COMMANDS_POLL_ROUTE = "commands_poll"


class FrameError(Exception):
    """Base for every framing-level failure. Never raised across a
    connection boundary -- each subclass is caught at the point a
    connection is being read, and turned into either a rejection
    response (frame boundary known, content invalid) or a closed
    connection (framing itself broke, so no further byte offset in the
    stream can be trusted)."""


class FrameTooLargeError(FrameError):
    def __init__(self, declared_length: int) -> None:
        super().__init__(f"frame declares {declared_length} bytes, exceeding the configured maximum")
        self.declared_length = declared_length


class ConnectionClosedError(FrameError):
    """The peer closed the connection (or sent 0 bytes on a blocking
    read), whether between frames (clean) or mid-frame (a partial-packet
    stream cut short)."""


def encode_frame(payload: dict) -> bytes:
    body = json.dumps(payload, default=str).encode("utf-8")
    return _LENGTH_PREFIX.pack(len(body)) + body


def _recv_exact(sock: socket.socket, count: int) -> bytes:
    """Reads exactly `count` bytes, looping across as many individual
    `recv()` calls as the OS/network happens to split them into -- this
    is what makes a partial packet (one `recv()` returning fewer bytes
    than requested) transparent to every caller, and what leaves any
    bytes belonging to a *subsequent* frame untouched in the socket's
    receive buffer for the next `read_frame()` call to pick up (a
    concatenated-packets scenario) rather than discarding them."""
    chunks = []
    remaining = count
    while remaining > 0:
        chunk = sock.recv(min(_RECV_CHUNK_BYTES, remaining))
        if not chunk:
            raise ConnectionClosedError("connection closed while reading a frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_frame(sock: socket.socket, max_bytes: int) -> bytes:
    """Blocks (subject to the socket's own configured timeout) until one
    complete frame is read, and returns its JSON payload bytes. Raises
    `FrameTooLargeError` before reading a single payload byte if the
    declared length exceeds `max_bytes` -- oversized frames are refused
    at the cheapest possible point, never partially buffered."""
    header = _recv_exact(sock, _LENGTH_PREFIX.size)
    (length,) = _LENGTH_PREFIX.unpack(header)
    if length > max_bytes:
        raise FrameTooLargeError(length)
    return _recv_exact(sock, length)


class _BridgeSocketHandler(socketserver.BaseRequestHandler):
    """One instance per accepted TCP connection -- `setup()`/`handle()`/
    `finish()` together are this connection's entire lifecycle. State
    here (`_last_seq`) is per-connection only, by design: a new
    connection is a new session with its own sequence space, matching
    how a stale/dropped connection can never be replayed against (the
    server never remembers a sequence across connections)."""

    def setup(self) -> None:
        self.request.settimeout(self.server.config.socket_idle_timeout_seconds)
        self._last_seq: Optional[int] = None
        if self.server.metrics is not None:
            self.server.metrics.record_socket_connection_opened()
        logger.info("socket_transport: connection opened from %s", self.client_address)

    def finish(self) -> None:
        if self.server.metrics is not None:
            self.server.metrics.record_socket_connection_closed()
        logger.info("socket_transport: connection closed from %s", self.client_address)

    def handle(self) -> None:
        while True:
            try:
                payload = read_frame(self.request, self.server.config.socket_max_message_bytes)
            except FrameTooLargeError as exc:
                logger.warning(
                    "socket_transport: oversized frame from %s (%d bytes)",
                    self.client_address, exc.declared_length,
                )
                if self.server.metrics is not None:
                    self.server.metrics.record_socket_oversized_frame()
                self._send(None, 400, {"error": "frame_too_large", "declared_length": exc.declared_length})
                return  # framing trust is broken once a claimed length is refused -- close, don't guess where the next frame starts
            except ConnectionClosedError:
                return
            except socket.timeout:
                logger.info("socket_transport: idle timeout, closing connection from %s", self.client_address)
                if self.server.metrics is not None:
                    self.server.metrics.record_socket_idle_timeout()
                return
            except OSError as exc:
                # e.g. ConnectionResetError/BrokenPipeError -- the peer
                # vanished abnormally (crash, network drop, forced
                # reset). Logged and closed like any other disconnect;
                # never allowed to propagate into socketserver's default
                # handle_error() traceback dump, since a peer going away
                # is an expected, routine transport event here, not an
                # unexpected bug in this handler.
                logger.info("socket_transport: connection from %s closed abnormally (%s)", self.client_address, exc)
                return
            if self.server.metrics is not None:
                self.server.metrics.record_socket_bytes_received(_LENGTH_PREFIX.size + len(payload))
            self._process_frame(payload)

    def _reject_frame(self, seq: Optional[int], error: str, now: datetime) -> None:
        """Runtime Audit Phase 2 -- every frame-level rejection (before
        `_dispatch()` is ever reached) now logs the same one-line,
        precise-cause format `describe_rejection()`'s label table
        provides, instead of only incrementing a metrics counter with no
        corresponding log line.

        Runtime Audit Phase 3 -- `now` (the Bridge's own explicit UTC
        clock, `self.server.clock()`) is logged verbatim rather than
        relying on the `logging` module's `%(asctime)s`, which renders in
        this process's local time zone by default -- a diagnostic tool
        correlating this line against the EA's own UTC-based timestamps
        must not have to guess which zone a bare asctime is in."""
        reason = _http_server.describe_rejection(400, {"error": error})
        logger.warning(
            "socket_transport: rejected (frame-level) status=400 reason=%s remote=%s now=%s",
            reason, self.client_address, now.isoformat(),
        )
        self._send(seq, 400, {"error": error})

    def _process_frame(self, payload: bytes) -> None:
        now = self.server.clock()
        metrics = self.server.metrics
        try:
            envelope = json.loads(payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            if metrics is not None:
                metrics.record_socket_malformed_frame()
            self._reject_frame(None, "invalid_json_frame", now)
            return
        if not isinstance(envelope, dict):
            if metrics is not None:
                metrics.record_socket_malformed_frame()
            self._reject_frame(None, "json_object_required", now)
            return

        seq = envelope.get("seq")
        route = envelope.get("route")
        body = envelope.get("body")
        if not isinstance(seq, int) or isinstance(seq, bool):
            if metrics is not None:
                metrics.record_socket_malformed_frame()
            self._reject_frame(None, "missing_or_invalid_seq", now)
            return
        if not isinstance(route, str):
            if metrics is not None:
                metrics.record_socket_malformed_frame()
            self._reject_frame(seq, "missing_or_invalid_route", now)
            return
        if not isinstance(body, dict):
            if metrics is not None:
                metrics.record_socket_malformed_frame()
            self._reject_frame(seq, "missing_or_invalid_body", now)
            return
        if self._last_seq is not None and seq <= self._last_seq:
            if metrics is not None:
                metrics.record_socket_duplicate_or_replayed_seq()
            self._reject_frame(seq, "duplicate_or_replayed_seq", now)
            return
        self._last_seq = seq

        status, response_body = self._dispatch(route, body, now)
        if metrics is not None:
            metrics.record_socket_message_processed()
        rejection_reason = _http_server.describe_rejection(status, response_body)
        if rejection_reason is not None:
            # Runtime Audit Phase 2 -- one line naming the exact rejection
            # cause, shared with server.py's own HTTP-side instrumentation
            # (same describe_rejection(), same labels) so a request
            # rejected for the same reason reads identically regardless of
            # which transport carried it. Previously this transport logged
            # framing anomalies (malformed/duplicate frames) but nothing
            # at all for a message that framed correctly and was then
            # rejected by validation -- this closes that gap.
            logger.info(
                "socket_transport: rejected route=%s status=%s reason=%s remote=%s now=%s",
                route, status, rejection_reason, self.client_address, now.isoformat(),
            )
        else:
            # Runtime Audit Phase 3 -- a message that was received, framed
            # correctly, and accepted previously left no trace at all on
            # this transport (unlike server.py's do_POST/do_GET, which
            # logs every response, success included). Without this, a
            # deterministic "did the Bridge receive and accept this
            # request" classification had evidence for every outcome
            # except the one that matters most for a healthy path.
            logger.info(
                "socket_transport: accepted route=%s status=%s remote=%s now=%s",
                route, status, self.client_address, now.isoformat(),
            )
        self._send(seq, status, response_body)

    def _dispatch(self, route: str, body: dict, now: datetime) -> Tuple[int, dict]:
        engine = self.server.engine
        config = self.server.config
        if route == _COMMANDS_POLL_ROUTE:
            query = {
                "api_key": [body.get("api_key")],
                "magic_number": [str(body.get("magic_number", -1))],
            }
            return _http_server._handle_poll_commands(engine, config, query, now)
        http_path = _ROUTE_TO_HTTP_PATH.get(route)
        handler = _http_server._POST_ROUTES.get(http_path) if http_path is not None else None
        if handler is None:
            return 404, {"error": "unknown_route", "route": route}
        try:
            return handler(engine, config, body, now)
        except (KeyError, ValueError, TypeError) as exc:
            return 400, {"error": f"invalid_payload:{exc}"}
        except Exception as exc:  # pragma: no cover - defensive, mirrors server.py's own do_POST
            logger.exception("socket_transport: unhandled exception dispatching route %s", route)
            return 500, {"error": str(exc)}

    def _send(self, seq: Optional[int], status: int, body: dict) -> None:
        frame = encode_frame({"seq": seq, "status": status, "body": body})
        try:
            self.request.sendall(frame)
        except OSError:
            return  # peer already gone -- nothing more to do
        if self.server.metrics is not None:
            self.server.metrics.record_socket_bytes_sent(len(frame))


class _BridgeSocketServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 128

    def __init__(
        self,
        address: Tuple[str, int],
        engine: BridgeEngine,
        config: BridgeConfig,
        clock: Callable[[], datetime],
        metrics: Optional[BridgeMetrics],
    ) -> None:
        self.engine = engine
        self.config = config
        self.clock = clock
        self.metrics = metrics
        self.connection_lock = threading.Lock()
        self.active_connections = 0
        super().__init__(address, _BridgeSocketHandler)

    def verify_request(self, request, client_address) -> bool:
        with self.connection_lock:
            if self.active_connections >= self.config.socket_max_connections:
                if self.metrics is not None:
                    self.metrics.record_socket_connection_rejected()
                logger.warning(
                    "socket_transport: connection from %s rejected -- at socket_max_connections (%d)",
                    client_address, self.config.socket_max_connections,
                )
                return False
            self.active_connections += 1
        return True

    def finish_request(self, request, client_address) -> None:
        """Symmetric with `verify_request`'s increment -- wraps the
        entire handler lifecycle (not just its `handle()` body) so
        `active_connections` is decremented exactly once per accepted
        connection even if the handler fails during `setup()`, before
        its own `finish()` would otherwise run."""
        try:
            super().finish_request(request, client_address)
        finally:
            with self.connection_lock:
                self.active_connections -= 1


def serve_socket(
    engine: BridgeEngine,
    config: BridgeConfig,
    clock: Optional[Callable[[], datetime]] = None,
    host: str = "127.0.0.1",
    port: Optional[int] = None,
    metrics: Optional[BridgeMetrics] = None,
) -> socketserver.ThreadingTCPServer:
    resolved_clock = clock or (lambda: datetime.now(timezone.utc))
    resolved_port = port if port is not None else config.socket_port
    return _BridgeSocketServer((host, resolved_port), engine, config, resolved_clock, metrics)


__all__ = [
    "encode_frame",
    "read_frame",
    "FrameError",
    "FrameTooLargeError",
    "ConnectionClosedError",
    "serve_socket",
]
