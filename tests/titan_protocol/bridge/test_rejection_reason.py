"""Tests for Runtime Audit Phase 2 -- exact rejection-cause instrumentation
(`server.describe_rejection`) and its use in both transports' per-request
log lines.

Context: an operator reported the Bridge returning "HTTP 1003" and asked
for the authentication path to be traced and instrumented so every
rejection names its precise cause instead of a generic PASS/FAIL. `1003`
is not a status this codebase's Bridge ever emits -- ADR-034 already
established (via exhaustive code review and direct curl testing in an
earlier session) that it is an undocumented MT5-side WinINet pseudo-status
originating in the terminal's own network stack. These tests validate the
real, buildable half of that request: every genuine Bridge-side rejection
(API key, magic number, symbol, payload, correlation id, unknown route,
malformed frame) now logs its exact cause in one line, on both transports.
"""

from __future__ import annotations

import json
import logging
import time
import unittest
from datetime import datetime, timezone

from titan_protocol.bridge.command_queue import CommandQueue
from titan_protocol.bridge.connection_health import ConnectionHealth
from titan_protocol.bridge.engine import BridgeEngine
from titan_protocol.bridge.server import describe_rejection
from titan_protocol.bridge.socket_transport import encode_frame
from tests.titan_protocol.bridge._fixtures import API_KEY, make_config
from tests.titan_protocol.bridge.test_http_server import HttpServerTestCase
from tests.titan_protocol.bridge.test_socket_transport import SocketTransportTestCase


def _wait_for_substring(get_text, substring: str, timeout: float = 2.0) -> str:
    """server.py's HTTP handler writes the response over the socket before
    printing its lifecycle log line (pre-existing order, unrelated to this
    instrumentation), so the client's _post() can return microseconds
    before the server thread's print() calls actually run. Poll while
    stdout is still redirected -- once the caller restores sys.stdout,
    any print() the server thread makes afterward is looked up fresh and
    goes to the real stdout instead, not into the captured buffer, so
    waiting must happen before that restore, not after."""
    deadline = time.monotonic() + timeout
    text = get_text()
    while substring not in text and time.monotonic() < deadline:
        time.sleep(0.01)
        text = get_text()
    return text


class TestDescribeRejectionUnit(unittest.TestCase):
    """Pure unit tests -- no server, no socket."""

    def test_2xx_is_none(self):
        self.assertIsNone(describe_rejection(200, {"status": "ok"}))
        self.assertIsNone(describe_rejection(299, {}))

    def test_every_error_code_maps_to_a_specific_label(self):
        cases = {
            "MISSING_API_KEY": "API key missing",
            "INVALID_API_KEY": "API key mismatch",
            "MAGIC_NUMBER_MISMATCH": "MagicNumber mismatch",
            "SYMBOL_NOT_ALLOWED": "Symbol not in allowed list",
            "INVALID_VOLUME": "Invalid volume",
            "VOLUME_EXCEEDS_MAX": "Volume exceeds max lot size",
            "INVALID_STOP_LOSS": "Invalid stop loss",
            "INVALID_TAKE_PROFIT": "Invalid take profit",
            "TIMESTAMP_IN_FUTURE": "Timestamp in future",
            "STALE_TIMESTAMP": "Stale timestamp",
            "MISSING_CORRELATION_ID": "Missing correlation id",
            "DUPLICATE_CORRELATION_ID": "Duplicate correlation id",
            "UNKNOWN_CORRELATION_ID": "Unknown correlation id",
            "BRIDGE_NOT_READY": "Bridge not ready",
            "EMERGENCY_STOP_ACTIVE": "Emergency stop active",
            "MARKET_DATA_INGESTION_NOT_CONFIGURED": "Market data ingestion not configured",
        }
        for code, label in cases.items():
            with self.subTest(code=code):
                self.assertEqual(describe_rejection(401, {"error": code}), label)

    def test_unknown_route_labeled_for_both_transports_spellings(self):
        self.assertEqual(describe_rejection(404, {"error": "not found"}), "Unknown route")
        self.assertEqual(describe_rejection(404, {"error": "unknown_route"}), "Unknown route")

    def test_frame_level_socket_errors_are_labeled(self):
        self.assertEqual(describe_rejection(400, {"error": "invalid_json_frame"}), "Malformed socket frame (not valid JSON)")
        self.assertEqual(describe_rejection(400, {"error": "missing_or_invalid_seq"}), "Socket frame missing/invalid seq")
        self.assertEqual(describe_rejection(400, {"error": "missing_or_invalid_route"}), "Socket frame missing/invalid route")
        self.assertEqual(describe_rejection(400, {"error": "missing_or_invalid_body"}), "Socket frame missing/invalid body")
        self.assertEqual(describe_rejection(400, {"error": "duplicate_or_replayed_seq"}), "Duplicate or replayed socket seq")

    def test_invalid_payload_prefix_keeps_the_underlying_detail(self):
        reason = describe_rejection(400, {"error": "invalid_payload:'balance'"})
        self.assertEqual(reason, "Invalid payload -- 'balance'")

    def test_no_error_detail_still_produces_a_line_not_a_crash(self):
        reason = describe_rejection(500, {})
        self.assertEqual(reason, "Rejected (HTTP 500, no error detail)")

    def test_unmapped_error_string_passes_through_verbatim(self):
        self.assertEqual(describe_rejection(400, {"error": "some_future_code"}), "some_future_code")


class TestHttpTransportLogsExactReason(HttpServerTestCase):
    """Real requests over a real socket -- confirms the actual printed
    log line, not just describe_rejection() in isolation."""

    def _post_and_capture(self, path, payload, **kwargs):
        """Redirects stdout, performs the request, and waits for the
        server thread's lifecycle log block to finish printing -- all
        while still redirected -- before restoring sys.stdout. See
        _wait_for_substring's docstring for why the wait must happen
        before the restore, not after."""
        import io
        import sys

        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            status, body = self._post(path, payload, **kwargs)
            text = _wait_for_substring(captured.getvalue, "Elapsed:")
        finally:
            sys.stdout = old_stdout
        return status, body, text

    def test_missing_api_key_logs_api_key_missing(self):
        status, body, text = self._post_and_capture("/bridge/heartbeat", {"magic_number": 20260710}, api_key=None)
        self.assertEqual(status, 401)
        self.assertEqual(body["error"], "MISSING_API_KEY")
        self.assertIn("Rejection reason: API key missing", text)

    def test_wrong_api_key_logs_api_key_mismatch(self):
        status, body, text = self._post_and_capture("/bridge/heartbeat", {"magic_number": 20260710}, api_key="wrong-key")
        self.assertEqual(status, 401)
        self.assertEqual(body["error"], "INVALID_API_KEY")
        self.assertIn("Rejection reason: API key mismatch", text)

    def test_wrong_magic_number_logs_magicnumber_mismatch(self):
        status, body, text = self._post_and_capture("/bridge/heartbeat", {"magic_number": 1})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "MAGIC_NUMBER_MISMATCH")
        self.assertIn("Rejection reason: MagicNumber mismatch", text)

    def test_unknown_route_logs_unknown_route(self):
        status, _body, text = self._post_and_capture("/bridge/no-such-route", {})
        self.assertEqual(status, 404)
        self.assertIn("Rejection reason: Unknown route", text)

    def test_successful_request_logs_no_rejection_reason_line(self):
        status, _body, text = self._post_and_capture("/bridge/heartbeat", {"magic_number": self.config.magic_number})
        self.assertEqual(status, 200)
        self.assertNotIn("Rejection reason:", text)


class TestSocketTransportLogsExactReason(SocketTransportTestCase):
    """Real messages over a real socket connection -- confirms
    socket_transport.py, which previously logged nothing per rejected
    message, now logs the same precise-cause line server.py does."""

    def test_wrong_api_key_logs_via_python_logging(self):
        sock = self._connect()
        try:
            with self.assertLogs("titan_protocol.bridge.socket_transport", level="INFO") as captured:
                frame = encode_frame({"seq": 1, "route": "heartbeat", "body": {"api_key": "wrong", "magic_number": self.config.magic_number}})
                sock.sendall(frame)
                response = self._recv_frame(sock)
        finally:
            sock.close()
        self.assertEqual(response["status"], 401)
        joined = "\n".join(captured.output)
        self.assertIn("reason=API key mismatch", joined)

    def test_malformed_frame_level_error_logs_via_python_logging(self):
        sock = self._connect()
        try:
            with self.assertLogs("titan_protocol.bridge.socket_transport", level="WARNING") as captured:
                frame = encode_frame({"seq": "not-an-int", "route": "heartbeat", "body": {}})
                sock.sendall(frame)
                response = self._recv_frame(sock)
        finally:
            sock.close()
        self.assertEqual(response["status"], 400)
        joined = "\n".join(captured.output)
        self.assertIn("reason=Socket frame missing/invalid seq", joined)

    def test_unknown_route_logs_unknown_route(self):
        sock = self._connect()
        try:
            with self.assertLogs("titan_protocol.bridge.socket_transport", level="INFO") as captured:
                frame = encode_frame({"seq": 1, "route": "not_a_real_route", "body": {"api_key": API_KEY, "magic_number": self.config.magic_number}})
                sock.sendall(frame)
                response = self._recv_frame(sock)
        finally:
            sock.close()
        self.assertEqual(response["status"], 404)
        joined = "\n".join(captured.output)
        self.assertIn("reason=Unknown route", joined)


if __name__ == "__main__":
    unittest.main()
