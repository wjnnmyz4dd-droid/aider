"""Full-stack tests for the ADR-034 native-socket Bridge transport --
every scenario the originating request named explicitly: partial
packets, concatenated packets, disconnects, reconnects, stale sessions,
wrong keys, replayed messages, server restarts, malformed messages, and
bounded message sizes. Mirrors `test_http_server.py`'s "exercise a real
socket, the same path the MQL5 EA itself uses" posture, just over
`socket_transport.py`'s framing instead of HTTP."""

from __future__ import annotations

import json
import socket
import threading
import time
import unittest
from datetime import datetime, timezone

from titan_protocol.bridge.command_queue import CommandQueue
from titan_protocol.bridge.connection_health import ConnectionHealth
from titan_protocol.bridge.engine import BridgeEngine
from titan_protocol.bridge.metrics import BridgeMetrics
from titan_protocol.bridge.socket_transport import (
    _LENGTH_PREFIX,
    encode_frame,
    serve_socket,
)
from tests.titan_protocol.bridge._fixtures import API_KEY, make_config


class SocketTransportTestCase(unittest.TestCase):
    def setUp(self):
        self.config = make_config(transport="socket", socket_max_connections=4, socket_idle_timeout_seconds=1.0)
        self.now = datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc)
        self.queue = CommandQueue(self.config)
        self.health = ConnectionHealth(self.config, clock=lambda: self.now)
        self.metrics = BridgeMetrics()
        self.engine = BridgeEngine(self.config, self.queue, self.health, clock=lambda: self.now, metrics=self.metrics)
        self.server = serve_socket(self.engine, self.config, clock=lambda: self.now, host="127.0.0.1", port=0, metrics=self.metrics)
        self.host, self.port = self.server.server_address
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _connect(self) -> socket.socket:
        sock = socket.create_connection((self.host, self.port), timeout=5)
        sock.settimeout(5)
        return sock

    def _recv_frame(self, sock: socket.socket) -> dict:
        header = self._recv_exact(sock, _LENGTH_PREFIX.size)
        (length,) = _LENGTH_PREFIX.unpack(header)
        body = self._recv_exact(sock, length)
        return json.loads(body.decode("utf-8"))

    @staticmethod
    def _recv_exact(sock: socket.socket, count: int) -> bytes:
        chunks = []
        remaining = count
        while remaining > 0:
            chunk = sock.recv(remaining)
            if not chunk:
                raise ConnectionError("connection closed while reading test frame")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _heartbeat_envelope(self, seq: int, api_key=API_KEY) -> dict:
        return {
            "seq": seq,
            "route": "heartbeat",
            "body": {"api_key": api_key, "magic_number": self.config.magic_number, "account_login": 1, "terminal_connected": True},
        }


class TestBasicRequestResponse(SocketTransportTestCase):
    def test_heartbeat_round_trip(self):
        sock = self._connect()
        sock.sendall(encode_frame(self._heartbeat_envelope(1)))
        resp = self._recv_frame(sock)
        self.assertEqual(resp["seq"], 1)
        self.assertEqual(resp["status"], 200)
        self.assertEqual(resp["body"]["status"], "ok")
        sock.close()

    def test_commands_poll_route(self):
        sock = self._connect()
        envelope = {"seq": 1, "route": "commands_poll", "body": {"api_key": API_KEY, "magic_number": self.config.magic_number}}
        sock.sendall(encode_frame(envelope))
        resp = self._recv_frame(sock)
        self.assertEqual(resp["status"], 200)
        self.assertIn("commands", resp["body"])
        sock.close()

    def test_unknown_route_rejected(self):
        sock = self._connect()
        envelope = {"seq": 1, "route": "not_a_real_route", "body": {}}
        sock.sendall(encode_frame(envelope))
        resp = self._recv_frame(sock)
        self.assertEqual(resp["status"], 404)
        sock.close()

    def test_wrong_api_key_rejected(self):
        sock = self._connect()
        sock.sendall(encode_frame(self._heartbeat_envelope(1, api_key="wrong-key")))
        resp = self._recv_frame(sock)
        self.assertEqual(resp["status"], 401)
        self.assertEqual(resp["body"]["error"], "INVALID_API_KEY")
        sock.close()

    def test_missing_api_key_rejected(self):
        sock = self._connect()
        envelope = {
            "seq": 1, "route": "heartbeat",
            "body": {"magic_number": self.config.magic_number, "account_login": 1, "terminal_connected": True},
        }
        sock.sendall(encode_frame(envelope))
        resp = self._recv_frame(sock)
        self.assertEqual(resp["status"], 401)
        sock.close()


class TestPartialAndConcatenatedPackets(SocketTransportTestCase):
    def test_partial_packet_reassembled(self):
        """A frame split across many small `send()` calls must still be
        processed as one complete message -- this is what `_recv_exact`'s
        looped reads exist to guarantee."""
        sock = self._connect()
        frame = encode_frame(self._heartbeat_envelope(1))
        for i in range(0, len(frame), 3):
            sock.sendall(frame[i:i + 3])
            time.sleep(0.01)
        resp = self._recv_frame(sock)
        self.assertEqual(resp["status"], 200)
        sock.close()

    def test_concatenated_packets_both_processed_in_order(self):
        """Two frames sent back-to-back in a single `sendall()` call
        (indistinguishable, at the TCP layer, from one packet carrying
        both) must each be read and answered separately, in order."""
        sock = self._connect()
        frame1 = encode_frame(self._heartbeat_envelope(1))
        frame2 = encode_frame(self._heartbeat_envelope(2))
        sock.sendall(frame1 + frame2)
        resp1 = self._recv_frame(sock)
        resp2 = self._recv_frame(sock)
        self.assertEqual((resp1["seq"], resp1["status"]), (1, 200))
        self.assertEqual((resp2["seq"], resp2["status"]), (2, 200))
        sock.close()

    def test_three_concatenated_frames_of_varying_size(self):
        sock = self._connect()
        frames = b"".join(encode_frame(self._heartbeat_envelope(seq)) for seq in (1, 2, 3))
        sock.sendall(frames)
        seqs = [self._recv_frame(sock)["seq"] for _ in range(3)]
        self.assertEqual(seqs, [1, 2, 3])
        sock.close()


class TestSequenceReplayProtection(SocketTransportTestCase):
    def test_replayed_seq_rejected(self):
        sock = self._connect()
        sock.sendall(encode_frame(self._heartbeat_envelope(5)))
        self._recv_frame(sock)
        sock.sendall(encode_frame(self._heartbeat_envelope(5)))  # replay of the same seq
        resp = self._recv_frame(sock)
        self.assertEqual(resp["status"], 400)
        self.assertEqual(resp["body"]["error"], "duplicate_or_replayed_seq")
        sock.close()

    def test_lower_seq_after_higher_seq_rejected(self):
        sock = self._connect()
        sock.sendall(encode_frame(self._heartbeat_envelope(10)))
        self._recv_frame(sock)
        sock.sendall(encode_frame(self._heartbeat_envelope(3)))
        resp = self._recv_frame(sock)
        self.assertEqual(resp["status"], 400)
        sock.close()

    def test_strictly_increasing_seq_all_accepted(self):
        sock = self._connect()
        for seq in (1, 2, 3, 100, 101):
            sock.sendall(encode_frame(self._heartbeat_envelope(seq)))
            resp = self._recv_frame(sock)
            self.assertEqual(resp["status"], 200, f"seq {seq} unexpectedly rejected")
        sock.close()

    def test_fresh_connection_resets_sequence_space(self):
        """A new TCP connection is a new session -- seq 1 must be
        accepted again even though a previous, now-closed connection
        already used it."""
        sock1 = self._connect()
        sock1.sendall(encode_frame(self._heartbeat_envelope(1)))
        self._recv_frame(sock1)
        sock1.close()

        sock2 = self._connect()
        sock2.sendall(encode_frame(self._heartbeat_envelope(1)))
        resp = self._recv_frame(sock2)
        self.assertEqual(resp["status"], 200)
        sock2.close()


class TestMalformedMessages(SocketTransportTestCase):
    def test_invalid_json_body_rejected(self):
        sock = self._connect()
        payload = b"not json at all"
        sock.sendall(_LENGTH_PREFIX.pack(len(payload)) + payload)
        resp = self._recv_frame(sock)
        self.assertEqual(resp["status"], 400)
        self.assertEqual(resp["body"]["error"], "invalid_json_frame")
        sock.close()

    def test_non_object_json_rejected(self):
        sock = self._connect()
        payload = json.dumps([1, 2, 3]).encode("utf-8")
        sock.sendall(_LENGTH_PREFIX.pack(len(payload)) + payload)
        resp = self._recv_frame(sock)
        self.assertEqual(resp["status"], 400)
        sock.close()

    def test_missing_seq_rejected(self):
        sock = self._connect()
        envelope = {"route": "heartbeat", "body": {"api_key": API_KEY, "magic_number": self.config.magic_number}}
        sock.sendall(encode_frame(envelope))
        resp = self._recv_frame(sock)
        self.assertEqual(resp["status"], 400)
        self.assertEqual(resp["body"]["error"], "missing_or_invalid_seq")
        sock.close()

    def test_bool_seq_rejected(self):
        """`bool` is a subclass of `int` in Python -- must not silently
        pass as a valid sequence number."""
        sock = self._connect()
        envelope = {"seq": True, "route": "heartbeat", "body": {"api_key": API_KEY, "magic_number": self.config.magic_number}}
        sock.sendall(encode_frame(envelope))
        resp = self._recv_frame(sock)
        self.assertEqual(resp["status"], 400)
        sock.close()

    def test_missing_route_rejected(self):
        sock = self._connect()
        envelope = {"seq": 1, "body": {"api_key": API_KEY, "magic_number": self.config.magic_number}}
        sock.sendall(encode_frame(envelope))
        resp = self._recv_frame(sock)
        self.assertEqual(resp["status"], 400)
        self.assertEqual(resp["body"]["error"], "missing_or_invalid_route")
        sock.close()

    def test_missing_body_rejected(self):
        sock = self._connect()
        envelope = {"seq": 1, "route": "heartbeat"}
        sock.sendall(encode_frame(envelope))
        resp = self._recv_frame(sock)
        self.assertEqual(resp["status"], 400)
        self.assertEqual(resp["body"]["error"], "missing_or_invalid_body")
        sock.close()

    def test_malformed_frame_does_not_kill_the_connection(self):
        """A malformed *payload* (framing itself intact) is a rejection,
        not a disconnect -- the connection stays usable afterward."""
        sock = self._connect()
        payload = b"garbage"
        sock.sendall(_LENGTH_PREFIX.pack(len(payload)) + payload)
        resp = self._recv_frame(sock)
        self.assertEqual(resp["status"], 400)
        sock.sendall(encode_frame(self._heartbeat_envelope(1)))
        resp2 = self._recv_frame(sock)
        self.assertEqual(resp2["status"], 200)
        sock.close()


class TestBoundedMessageSize(SocketTransportTestCase):
    def test_oversized_frame_rejected_and_connection_closed(self):
        sock = self._connect()
        declared_length = self.config.socket_max_message_bytes + 1
        sock.sendall(_LENGTH_PREFIX.pack(declared_length))
        resp = self._recv_frame(sock)
        self.assertEqual(resp["status"], 400)
        self.assertEqual(resp["body"]["error"], "frame_too_large")
        self.assertEqual(resp["body"]["declared_length"], declared_length)
        # Framing trust is broken once an oversized length is refused --
        # the server closes the connection outright.
        remainder = sock.recv(16)
        self.assertEqual(remainder, b"")
        sock.close()

    def test_frame_at_exactly_the_limit_is_accepted(self):
        """A body whose declared length equals `socket_max_message_bytes`
        exactly must still be processed (the bound is inclusive, not
        exclusive) -- padded with extra whitespace inside the JSON
        object to hit the exact byte target without changing meaning."""
        sock = self._connect()
        envelope = self._heartbeat_envelope(1)
        base = json.dumps(envelope).encode("utf-8")
        pad_needed = self.config.socket_max_message_bytes - len(base)
        self.assertGreater(pad_needed, 0, "test fixture config's max is too small for this padding approach")
        padded = json.dumps(envelope) + (" " * pad_needed)
        payload = padded.encode("utf-8")
        self.assertEqual(len(payload), self.config.socket_max_message_bytes)
        sock.sendall(_LENGTH_PREFIX.pack(len(payload)) + payload)
        resp = self._recv_frame(sock)
        self.assertEqual(resp["status"], 200)
        sock.close()


class TestDisconnectsAndStaleSessions(SocketTransportTestCase):
    def test_abrupt_disconnect_does_not_crash_server(self):
        sock = self._connect()
        sock.sendall(encode_frame(self._heartbeat_envelope(1)))
        self._recv_frame(sock)
        sock.close()  # abrupt close, no clean shutdown handshake

        # Server must still be alive and serving other connections.
        sock2 = self._connect()
        sock2.sendall(encode_frame(self._heartbeat_envelope(1)))
        resp = self._recv_frame(sock2)
        self.assertEqual(resp["status"], 200)
        sock2.close()

    def test_reset_connection_does_not_crash_server(self):
        sock = self._connect()
        sock.sendall(encode_frame(self._heartbeat_envelope(1)))
        self._recv_frame(sock)
        # SO_LINGER with linger=0 forces an RST on close instead of a
        # clean FIN -- simulates a hard network/process failure.
        import struct as _struct
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, _struct.pack("ii", 1, 0))
        sock.close()

        sock2 = self._connect()
        sock2.sendall(encode_frame(self._heartbeat_envelope(1)))
        resp = self._recv_frame(sock2)
        self.assertEqual(resp["status"], 200)
        sock2.close()

    def test_stale_idle_session_is_closed_by_server(self):
        """`socket_idle_timeout_seconds=1.0` in this fixture's config --
        a connection that sends nothing for longer than that must be
        closed by the server (an EA that reconnects will get a fresh
        session, never hang waiting on a half-dead one)."""
        sock = self._connect()
        sock.sendall(encode_frame(self._heartbeat_envelope(1)))
        self._recv_frame(sock)
        time.sleep(1.5)
        sock.settimeout(2)
        remainder = sock.recv(16)
        self.assertEqual(remainder, b"")
        sock.close()

    def test_reconnect_after_stale_close_gets_a_working_fresh_session(self):
        sock = self._connect()
        sock.sendall(encode_frame(self._heartbeat_envelope(1)))
        self._recv_frame(sock)
        time.sleep(1.5)
        sock.close()

        sock2 = self._connect()
        sock2.sendall(encode_frame(self._heartbeat_envelope(1)))
        resp = self._recv_frame(sock2)
        self.assertEqual(resp["status"], 200)
        sock2.close()


class TestConnectionBound(SocketTransportTestCase):
    def test_connections_beyond_max_are_rejected(self):
        conns = [self._connect() for _ in range(self.config.socket_max_connections)]
        time.sleep(0.1)
        extra = self._connect()
        extra.settimeout(2)
        # A rejected connection is closed by the server without any
        # response frame -- recv() returns b"" (EOF), never data.
        data = extra.recv(16)
        self.assertEqual(data, b"")
        for c in conns:
            c.close()
        extra.close()

    def test_connection_slot_freed_after_close(self):
        conns = [self._connect() for _ in range(self.config.socket_max_connections)]
        time.sleep(0.1)
        conns[0].close()
        time.sleep(0.2)
        replacement = self._connect()
        replacement.sendall(encode_frame(self._heartbeat_envelope(1)))
        resp = self._recv_frame(replacement)
        self.assertEqual(resp["status"], 200)
        for c in conns[1:]:
            c.close()
        replacement.close()


class TestServerRestart(SocketTransportTestCase):
    def test_client_can_reconnect_after_server_restart(self):
        """Simulates a Bridge process restart: the listening server is
        torn down and a new one bound to the same port, and a client
        that had an open connection to the old server can open a fresh
        one to the new server and be served normally -- the scenario an
        EA's reconnect/backoff loop must handle."""
        sock = self._connect()
        sock.sendall(encode_frame(self._heartbeat_envelope(1)))
        self._recv_frame(sock)

        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        sock.close()

        new_server = serve_socket(self.engine, self.config, clock=lambda: self.now, host=self.host, port=self.port, metrics=self.metrics)
        new_thread = threading.Thread(target=new_server.serve_forever, daemon=True)
        new_thread.start()
        try:
            sock2 = self._connect()
            sock2.sendall(encode_frame(self._heartbeat_envelope(1)))
            resp = self._recv_frame(sock2)
            self.assertEqual(resp["status"], 200)
            sock2.close()
        finally:
            new_server.shutdown()
            new_server.server_close()
            new_thread.join(timeout=5)
            # Prevent tearDown from operating on the already-closed original server.
            self.server = new_server
            self.thread = new_thread


class TestMetrics(SocketTransportTestCase):
    def test_metrics_reflect_activity(self):
        sock = self._connect()
        sock.sendall(encode_frame(self._heartbeat_envelope(1)))
        self._recv_frame(sock)
        sock.sendall(encode_frame(self._heartbeat_envelope(1)))  # duplicate
        self._recv_frame(sock)
        sock.close()
        time.sleep(0.2)

        snapshot = self.metrics.socket_health_snapshot()
        self.assertGreaterEqual(snapshot["connections_opened"], 1)
        self.assertGreaterEqual(snapshot["connections_closed"], 1)
        self.assertGreaterEqual(snapshot["messages_processed"], 1)
        self.assertGreaterEqual(snapshot["duplicate_or_replayed_seq"], 1)
        self.assertGreater(snapshot["bytes_received"], 0)
        self.assertGreater(snapshot["bytes_sent"], 0)


if __name__ == "__main__":
    unittest.main()
