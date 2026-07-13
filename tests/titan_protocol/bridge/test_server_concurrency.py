"""Server-level concurrency test (Phase 1.5 hotfix).

Discovered during Phase 1.5 stress validation: `ThreadingHTTPServer`'s
default `request_queue_size` (5, inherited from `socketserver.TCPServer`)
is the `socket.listen()` backlog. Under ~60 concurrent client threads
issuing real HTTP requests, the default size produced reproducible
`ConnectionResetError` ("Connection reset by peer") on the client side
-- confirmed via an isolated, controlled A/B test (identical load,
`request_queue_size=5` vs. `128`) to be the root cause, not a logic bug
elsewhere. `titan_protocol/bridge/server.py`'s `serve()` now returns a
`_BridgeHTTPServer` with a larger backlog; this test reproduces the
original failure scenario against the real fix and asserts it holds.
"""

from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from titan_protocol.bridge.command_queue import CommandQueue
from titan_protocol.bridge.connection_health import ConnectionHealth
from titan_protocol.bridge.engine import BridgeEngine
from titan_protocol.bridge.server import API_KEY_HEADER, serve
from tests.titan_protocol.bridge._fixtures import API_KEY, make_config


class TestServerHandlesConcurrentBurstWithoutConnectionReset(unittest.TestCase):
    def setUp(self):
        self.config = make_config()
        self.now = datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc)
        self.queue = CommandQueue(self.config)
        self.health = ConnectionHealth(self.config, clock=lambda: self.now)
        self.engine = BridgeEngine(self.config, self.queue, self.health, clock=lambda: self.now)
        self.server = serve(self.engine, self.config, clock=lambda: self.now, host="127.0.0.1", port=0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _post(self, path, payload):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(payload).encode(), method="POST",
            headers={"Content-Type": "application/json", API_KEY_HEADER: API_KEY},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status

    def _get(self, path):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", headers={API_KEY_HEADER: API_KEY},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status

    def test_backlog_is_larger_than_stdlib_default(self):
        self.assertGreater(self.server.request_queue_size, 5)

    def test_sustained_concurrent_burst_produces_no_connection_errors(self):
        thread_count = 60
        iterations = 50
        errors = []
        errors_lock = threading.Lock()

        def heartbeater(_):
            for _ in range(iterations):
                try:
                    status = self._post("/bridge/heartbeat", {"magic_number": self.config.magic_number, "terminal_connected": True})
                    assert status == 200
                except Exception as exc:
                    with errors_lock:
                        errors.append(str(exc))

        def poller(_):
            for _ in range(iterations):
                try:
                    status = self._get(f"/bridge/commands/poll?magic_number={self.config.magic_number}")
                    assert status == 200
                except Exception as exc:
                    with errors_lock:
                        errors.append(str(exc))

        def reporter(i):
            for j in range(iterations):
                try:
                    status = self._post("/bridge/execution/report", {
                        "correlation_id": f"srv-{i}-{j}", "magic_number": self.config.magic_number,
                        "success": True, "broker_ticket": f"t-{i}-{j}", "filled_price": 1.1, "filled_volume": 0.1,
                    })
                    assert status == 200
                except Exception as exc:
                    with errors_lock:
                        errors.append(str(exc))

        with ThreadPoolExecutor(max_workers=thread_count) as pool:
            futures = []
            futures += [pool.submit(heartbeater, i) for i in range(thread_count // 3)]
            futures += [pool.submit(poller, i) for i in range(thread_count // 3)]
            futures += [pool.submit(reporter, i) for i in range(thread_count // 3)]
            for future in futures:
                future.result()

        self.assertEqual(errors, [], f"{len(errors)} connection-level errors under concurrent burst load")


if __name__ == "__main__":
    unittest.main()
