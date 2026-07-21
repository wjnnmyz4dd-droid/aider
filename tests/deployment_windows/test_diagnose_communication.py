"""Tests for diagnose_communication.py (Runtime Audit Phase 3) -- the
deterministic classifier that proves, from real evidence, which of the
four mutually exclusive communication states a request fell into.

The MT5-terminal-resolution step (mt5_terminal.build_resolution_report())
is exercised elsewhere (test_mt5_terminal.py) and, like every other
MT5-instance-detection code in this repository, degrades to an honest
empty/ambiguous result on this Linux sandbox -- these tests exercise the
parsing/classification logic directly instead, including two full,
real, end-to-end paths (one successful request, one rejected request)
driven through the actual Bridge server code (server.py's HTTP transport,
socket_transport.py's socket transport), not fabricated strings, to
prove the classifier reads real production output correctly."""

from __future__ import annotations

import io
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone

from ._fixtures import DEPLOYMENT_DIR  # noqa: F401 -- ensures deployment_windows/ is on sys.path

import diagnose_communication as dc

from titan_protocol.bridge.server import describe_rejection, _log_bridge_lifecycle
from tests.titan_protocol.bridge._fixtures import API_KEY, make_config
from tests.titan_protocol.bridge.test_http_server import HttpServerTestCase
from tests.titan_protocol.bridge.test_socket_transport import SocketTransportTestCase


def _wait_for_substring(get_text, substring: str, timeout: float = 2.0) -> str:
    """Same reasoning as test_rejection_reason.py's helper of the same
    name: the server thread's print()/logger call can complete after the
    client already has its response, so poll briefly rather than assume
    the line is already there the instant the response arrives."""
    deadline = time.monotonic() + timeout
    text = get_text()
    while substring not in text and time.monotonic() < deadline:
        time.sleep(0.01)
        text = get_text()
    return text


class TestParseEaLog(unittest.TestCase):
    def test_attempt_blocked_and_no_response_all_parsed(self, tmp_path=None):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "20260717.log"
            log_path.write_text(
                "2026.07.17 04:40:00.000  Titan (EURUSD,M15)  TITAN_DIAG ATTEMPT route=heartbeat transport=HTTP time=2026-07-17T04:40:00+00:00\n"
                "2026.07.17 04:40:00.010  Titan (EURUSD,M15)  TITAN_DIAG BLOCKED transport=HTTP method=POST endpoint=/bridge/heartbeat lastError=4014 time=2026-07-17T04:40:00+00:00\n"
                "2026.07.17 04:41:00.000  Titan (EURUSD,M15)  TITAN_DIAG ATTEMPT route=account transport=Socket time=2026-07-17T04:41:00+00:00\n"
                "2026.07.17 04:41:00.010  Titan (EURUSD,M15)  TITAN_DIAG NO_RESPONSE transport=Socket route=account time=2026-07-17T04:41:00+00:00\n",
                encoding="utf-8",
            )
            events = dc._parse_ea_log(log_path)
        kinds = [(e.kind, e.route, e.transport) for e in events]
        self.assertIn(("ATTEMPT", "heartbeat", "HTTP"), kinds)
        self.assertIn(("BLOCKED", "/bridge/heartbeat", "HTTP"), kinds)
        self.assertIn(("ATTEMPT", "account", "Socket"), kinds)
        self.assertIn(("NO_RESPONSE", "account", "Socket"), kinds)

    def test_ignores_lines_without_the_tag(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "20260717.log"
            log_path.write_text(
                "2026.07.17 04:40:00.000  Titan (EURUSD,M15)  some unrelated Journal line\n"
                "2026.07.17 04:40:00.010  Titan (EURUSD,M15)  TitanProtocolEA: initialized\n",
                encoding="utf-8",
            )
            events = dc._parse_ea_log(log_path)
        self.assertEqual(events, [])

    def test_falls_back_from_utf16_to_utf8(self):
        """Real MT5 Experts logs may or may not carry a BOM depending on
        version -- this must never crash regardless."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "20260717.log"
            log_path.write_bytes(
                "TITAN_DIAG ATTEMPT route=heartbeat transport=HTTP time=2026-07-17T04:40:00+00:00\n".encode("utf-8")
            )
            events = dc._parse_ea_log(log_path)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].route, "heartbeat")


class TestParseBridgeConsoleLog(unittest.TestCase):
    def test_real_server_output_parsed_with_and_without_rejection(self):
        import tempfile
        from pathlib import Path

        ts = datetime(2026, 7, 17, 4, 40, 0, tzinfo=timezone.utc)
        buf = io.StringIO()
        import contextlib

        with contextlib.redirect_stdout(buf):
            _log_bridge_lifecycle(
                ts, "127.0.0.1", "POST", "/bridge/heartbeat", "FAIL", True, True, True, 400, 1.2,
                rejection_reason=describe_rejection(400, {"error": "MAGIC_NUMBER_MISMATCH"}),
            )
            _log_bridge_lifecycle(
                ts, "127.0.0.1", "POST", "/bridge/account", "PASS", True, True, True, 200, 1.2,
                rejection_reason=describe_rejection(200, {"status": "ok"}),
            )
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "bridge_console.log"
            log_path.write_text(buf.getvalue(), encoding="utf-8")
            events = dc._parse_bridge_console_log(log_path)
        self.assertEqual(len(events), 2)
        heartbeat = next(e for e in events if e.route == "/bridge/heartbeat")
        account = next(e for e in events if e.route == "/bridge/account")
        self.assertEqual(heartbeat.rejection_reason, "MagicNumber mismatch")
        self.assertEqual(heartbeat.response_status, 400)
        self.assertIsNone(account.rejection_reason)
        self.assertEqual(account.response_status, 200)


class TestParseBridgeRotatingLog(unittest.TestCase):
    def test_accepted_and_rejected_lines_parsed(self):
        import tempfile
        from pathlib import Path

        lines = [
            "2026-07-17 04:40:05,123 INFO     titan_protocol.bridge.socket_transport: socket_transport: "
            "rejected route=heartbeat status=401 reason=API key mismatch remote=('127.0.0.1', 51000) "
            "now=2026-07-17T04:40:05+00:00",
            "2026-07-17 04:40:06,456 INFO     titan_protocol.bridge.socket_transport: socket_transport: "
            "accepted route=account status=200 remote=('127.0.0.1', 51000) now=2026-07-17T04:40:06+00:00",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "titan_protocol_20260717.log"
            log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            events = dc._parse_bridge_rotating_log(log_path)
        self.assertEqual(len(events), 2)
        rejected = next(e for e in events if e.route == "heartbeat")
        accepted = next(e for e in events if e.route == "account")
        self.assertEqual(rejected.rejection_reason, "API key mismatch")
        self.assertEqual(rejected.response_status, 401)
        self.assertIsNone(accepted.rejection_reason)
        self.assertEqual(accepted.response_status, 200)


class TestRouteToHttpPath(unittest.TestCase):
    def test_short_route_translated(self):
        self.assertEqual(dc._route_as_http_path("heartbeat"), "/bridge/heartbeat")

    def test_commands_poll_special_cased(self):
        self.assertEqual(dc._route_as_http_path("commands_poll"), "/bridge/commands/poll")

    def test_already_a_path_passed_through(self):
        self.assertEqual(dc._route_as_http_path("/bridge/account"), "/bridge/account")


class TestSubfieldDerivation(unittest.TestCase):
    def test_success_all_yes(self):
        self.assertEqual(dc._subfields_for_reason(None), (dc._YES, dc._YES, dc._YES))

    def test_api_key_failure_stops_before_magic_number(self):
        auth, magic, validation = dc._subfields_for_reason("API key mismatch")
        self.assertEqual(auth, dc._NO)
        self.assertEqual(magic, dc._NA)
        self.assertEqual(validation, dc._NA)

    def test_magic_number_failure_implies_auth_passed(self):
        auth, magic, validation = dc._subfields_for_reason("MagicNumber mismatch")
        self.assertEqual(auth, dc._YES)
        self.assertEqual(magic, dc._NO)
        self.assertEqual(validation, dc._NA)

    def test_validation_failure_implies_auth_and_magic_passed(self):
        auth, magic, validation = dc._subfields_for_reason("Invalid volume")
        self.assertEqual((auth, magic), (dc._YES, dc._YES))
        self.assertEqual(validation, dc._NO)

    def test_unknown_route_is_not_applicable_for_every_subfield(self):
        self.assertEqual(dc._subfields_for_reason("Unknown route"), (dc._NA, dc._NA, dc._NA))

    def test_unrecognized_reason_is_honestly_unknown_not_guessed(self):
        auth, magic, validation = dc._subfields_for_reason("some_future_code")
        self.assertEqual((auth, magic, validation), (dc._UNKNOWN, dc._UNKNOWN, dc._UNKNOWN))


class TestClassifySyntheticEvidence(unittest.TestCase):
    """State 2 (blocked) and the honest "unmatched" case cannot be driven
    through a real WebRequest()/SocketConnect() failure without a real
    MT5 terminal -- these use directly-constructed EaEvent/BridgeEvent
    objects, exactly the shape _parse_ea_log/_parse_bridge_*_log already
    proved they produce from real files above."""

    def _attempt(self, route="heartbeat", transport="HTTP", ts=None):
        return dc.EaEvent(kind="ATTEMPT", route=route, transport=transport,
                           timestamp=ts or datetime(2026, 7, 17, 4, 40, 0, tzinfo=timezone.utc),
                           detail="", source_file="ea.log", source_line="ATTEMPT line")

    def test_state_2_blocked_with_corroborating_marker(self):
        attempt = self._attempt()
        blocked = dc.EaEvent(kind="BLOCKED", route="/bridge/heartbeat", transport="HTTP",
                              timestamp=attempt.timestamp, detail="lastError=4014",
                              source_file="ea.log", source_line="BLOCKED line lastError=4014")
        c = dc.classify(attempt, [attempt, blocked], [], timedelta(seconds=10))
        self.assertEqual(c.state, "2")
        self.assertEqual(c.mt5_attempted, dc._YES)
        self.assertEqual(c.bridge_received, dc._NO)
        self.assertTrue(any("lastError=4014" in line for line in c.evidence))

    def test_state_2_fallback_with_no_corroborating_marker_at_all(self):
        attempt = self._attempt()
        c = dc.classify(attempt, [attempt], [], timedelta(seconds=10))
        self.assertEqual(c.state, "2")
        self.assertEqual(c.bridge_received, dc._NO)

    def test_no_response_is_reported_as_unmatched_not_forced_into_a_state(self):
        attempt = self._attempt(transport="Socket")
        no_response = dc.EaEvent(kind="NO_RESPONSE", route="heartbeat", transport="Socket",
                                  timestamp=attempt.timestamp, detail="",
                                  source_file="ea.log", source_line="NO_RESPONSE line")
        c = dc.classify(attempt, [attempt, no_response], [], timedelta(seconds=10))
        self.assertEqual(c.state, "unmatched")
        self.assertEqual(c.bridge_received, dc._UNKNOWN)

    def test_out_of_window_bridge_event_is_not_matched(self):
        attempt = self._attempt()
        far_event = dc.BridgeEvent(timestamp=attempt.timestamp + timedelta(seconds=999), transport="HTTP",
                                    route="/bridge/heartbeat", rejection_reason=None, response_status=200,
                                    source_file="bridge.log", source_line="far")
        c = dc.classify(attempt, [attempt], [far_event], timedelta(seconds=10))
        self.assertEqual(c.state, "2")


class TestEndToEndHttp(HttpServerTestCase):
    """Demonstrates one real successful request path and one real failed
    request path over the actual HTTP transport, proving the classifier
    reads genuine server.py output correctly end to end."""

    def _post_and_capture(self, path, payload, **kwargs):
        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            status, body = self._post(path, payload, **kwargs)
            text = _wait_for_substring(captured.getvalue, "Elapsed:")
        finally:
            sys.stdout = old_stdout
        return status, body, text

    def test_successful_request_classifies_as_state_4(self):
        status, _body, console_text = self._post_and_capture(
            "/bridge/heartbeat", {"magic_number": self.config.magic_number},
        )
        self.assertEqual(status, 200)
        bridge_events = dc._parse_bridge_console_log_text(console_text)
        attempt = dc.EaEvent(kind="ATTEMPT", route="heartbeat", transport="HTTP", timestamp=self.now,
                              detail="", source_file="<test>", source_line="ATTEMPT route=heartbeat")
        c = dc.classify(attempt, [attempt], bridge_events, timedelta(seconds=10))
        self.assertEqual(c.state, "4")
        self.assertEqual(c.bridge_received, dc._YES)
        self.assertEqual(c.auth_passed, dc._YES)
        self.assertEqual(c.magic_number_matched, dc._YES)
        self.assertEqual(c.response_sent, dc._YES)

    def test_rejected_request_classifies_as_state_3_with_exact_reason(self):
        status, _body, console_text = self._post_and_capture(
            "/bridge/heartbeat", {"magic_number": 1},  # wrong magic number
        )
        self.assertEqual(status, 400)
        bridge_events = dc._parse_bridge_console_log_text(console_text)
        attempt = dc.EaEvent(kind="ATTEMPT", route="heartbeat", transport="HTTP", timestamp=self.now,
                              detail="", source_file="<test>", source_line="ATTEMPT route=heartbeat")
        c = dc.classify(attempt, [attempt], bridge_events, timedelta(seconds=10))
        self.assertEqual(c.state, "3")
        self.assertEqual(c.bridge_received, dc._YES)
        self.assertEqual(c.auth_passed, dc._YES)
        self.assertEqual(c.magic_number_matched, dc._NO)


class TestEndToEndSocket(SocketTransportTestCase):
    """Same demonstration as TestEndToEndHttp, over the real socket
    transport instead."""

    def test_successful_request_classifies_as_state_4(self):
        from titan_protocol.bridge.socket_transport import encode_frame

        sock = self._connect()
        try:
            with self.assertLogs("titan_protocol.bridge.socket_transport", level="INFO") as captured:
                frame = encode_frame({"seq": 1, "route": "account", "body": {
                    "api_key": API_KEY, "magic_number": self.config.magic_number, "balance": 10000.0,
                    "equity": 10000.0, "margin": 0.0, "free_margin": 10000.0, "margin_level": 0.0,
                }})
                sock.sendall(frame)
                response = self._recv_frame(sock)
        finally:
            sock.close()
        self.assertEqual(response["status"], 200)
        bridge_events = dc._parse_bridge_rotating_log_lines(captured.output)
        attempt = dc.EaEvent(kind="ATTEMPT", route="account", transport="Socket", timestamp=self.now,
                              detail="", source_file="<test>", source_line="ATTEMPT route=account")
        c = dc.classify(attempt, [attempt], bridge_events, timedelta(seconds=10))
        self.assertEqual(c.state, "4")
        self.assertEqual(c.bridge_received, dc._YES)

    def test_wrong_api_key_classifies_as_state_3(self):
        from titan_protocol.bridge.socket_transport import encode_frame

        sock = self._connect()
        try:
            with self.assertLogs("titan_protocol.bridge.socket_transport", level="INFO") as captured:
                frame = encode_frame({"seq": 1, "route": "heartbeat", "body": {
                    "api_key": "wrong-key", "magic_number": self.config.magic_number,
                }})
                sock.sendall(frame)
                response = self._recv_frame(sock)
        finally:
            sock.close()
        self.assertEqual(response["status"], 401)
        bridge_events = dc._parse_bridge_rotating_log_lines(captured.output)
        attempt = dc.EaEvent(kind="ATTEMPT", route="heartbeat", transport="Socket", timestamp=self.now,
                              detail="", source_file="<test>", source_line="ATTEMPT route=heartbeat")
        c = dc.classify(attempt, [attempt], bridge_events, timedelta(seconds=10))
        self.assertEqual(c.state, "3")
        self.assertEqual(c.auth_passed, dc._NO)


class TestHttpTransportPseudoStatusClassification(unittest.TestCase):
    """Runtime Audit Phase 4 -- the EA's `TITAN_DIAG NO_RESPONSE
    transport=HTTP ... pseudoStatus=<n> ...` marker (emitted by
    `PrintHttpTransportPseudoStatusFailure()` for a `WebRequest()` return
    value outside the valid 100-599 HTTP range, e.g. the field-observed
    `1001`/`GetLastError=5203` signature) must be parsed correctly and
    classified directly and confidently as state 2 -- not left
    "unmatched" the way a generic Socket-transport NO_RESPONSE is."""

    def _attempt(self, ts):
        return dc.EaEvent(kind="ATTEMPT", route="heartbeat", transport="HTTP", timestamp=ts,
                           detail="", source_file="ea.log", source_line="ATTEMPT line")

    def test_pseudo_status_marker_is_parsed_from_a_real_log_line(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "20260721.log"
            log_path.write_text(
                "2026.07.21 03:30:14.000  Titan (EURUSD,M15)  TITAN_DIAG NO_RESPONSE transport=HTTP "
                "method=POST endpoint=/bridge/heartbeat pseudoStatus=1001 lastError=5203 elapsedMs=7015 "
                "time=2026-07-21T03:30:14+00:00\n",
                encoding="utf-8",
            )
            events = dc._parse_ea_log(log_path)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.kind, "NO_RESPONSE")
        self.assertEqual(event.transport, "HTTP")
        self.assertIn("pseudoStatus=1001", event.detail)
        self.assertIn("lastError=5203", event.detail)

    def test_is_http_pseudo_status_no_response_true_only_with_the_field(self):
        ts = datetime(2026, 7, 21, 3, 30, 14, tzinfo=timezone.utc)
        pseudo = dc.EaEvent(kind="NO_RESPONSE", route="heartbeat", transport="HTTP", timestamp=ts,
                             detail="pseudoStatus=1001 lastError=5203", source_file="ea.log", source_line="x")
        generic_socket = dc.EaEvent(kind="NO_RESPONSE", route="heartbeat", transport="Socket", timestamp=ts,
                                     detail="", source_file="ea.log", source_line="x")
        generic_http = dc.EaEvent(kind="NO_RESPONSE", route="heartbeat", transport="HTTP", timestamp=ts,
                                   detail="", source_file="ea.log", source_line="x")
        self.assertTrue(dc._is_http_pseudo_status_no_response(pseudo))
        self.assertFalse(dc._is_http_pseudo_status_no_response(generic_socket))
        self.assertFalse(dc._is_http_pseudo_status_no_response(generic_http))

    def test_1001_5203_signature_classifies_confidently_as_state_2(self):
        ts = datetime(2026, 7, 21, 3, 30, 14, tzinfo=timezone.utc)
        attempt = self._attempt(ts)
        pseudo_status_event = dc.EaEvent(
            kind="NO_RESPONSE", route="/bridge/heartbeat", transport="HTTP", timestamp=ts,
            detail="pseudoStatus=1001 lastError=5203 elapsedMs=7015",
            source_file="ea.log", source_line="TITAN_DIAG NO_RESPONSE ... pseudoStatus=1001 lastError=5203",
        )
        c = dc.classify(attempt, [attempt, pseudo_status_event], [], timedelta(seconds=10))
        self.assertEqual(c.state, "2")
        self.assertEqual(c.bridge_received, dc._NO)
        self.assertTrue(any("pseudoStatus=1001" in line or "pseudoStatus" in line for line in c.evidence))
        self.assertFalse(any(e.startswith("No BLOCKED/NO_RESPONSE marker") for e in c.evidence))

    def test_generic_socket_no_response_is_still_left_unmatched(self):
        """Guards against the new branch accidentally widening to cover
        the Socket transport's own, genuinely ambiguous NO_RESPONSE case
        -- that one has no pseudoStatus field and must remain unmatched."""
        ts = datetime(2026, 7, 21, 3, 30, 14, tzinfo=timezone.utc)
        attempt = dc.EaEvent(kind="ATTEMPT", route="heartbeat", transport="Socket", timestamp=ts,
                              detail="", source_file="ea.log", source_line="ATTEMPT line")
        no_response = dc.EaEvent(kind="NO_RESPONSE", route="heartbeat", transport="Socket", timestamp=ts,
                                  detail="", source_file="ea.log", source_line="NO_RESPONSE line")
        c = dc.classify(attempt, [attempt, no_response], [], timedelta(seconds=10))
        self.assertEqual(c.state, "unmatched")


if __name__ == "__main__":
    unittest.main()
