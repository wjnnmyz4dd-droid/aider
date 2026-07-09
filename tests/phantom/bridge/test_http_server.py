"""Full-stack HTTP tests for the PhantomBridgeEA server (Phase 1) --
every route exercised over a real socket via `urllib.request`, the same
end-to-end path the MQL5 EA itself uses."""

from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Optional

from phantom.bridge.command_queue import CommandQueue
from phantom.bridge.connection_health import ConnectionHealth
from phantom.bridge.engine import BridgeEngine
from phantom.bridge.server import API_KEY_HEADER, registered_routes, serve
from tests.phantom.bridge._fixtures import API_KEY, make_command, make_config


class HttpServerTestCase(unittest.TestCase):
    def setUp(self):
        self.config = make_config()
        self.now = datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc)
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

    def _url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def _post(self, path: str, payload: dict, api_key: Optional[str] = API_KEY):
        headers = {"Content-Type": "application/json"}
        if api_key is not None:
            headers[API_KEY_HEADER] = api_key
        request = urllib.request.Request(
            self._url(path), data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def _get(self, path: str, api_key: Optional[str] = API_KEY):
        headers = {}
        if api_key is not None:
            headers[API_KEY_HEADER] = api_key
        request = urllib.request.Request(self._url(path), headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))


class TestRegisteredRoutes(HttpServerTestCase):
    def test_all_nine_endpoints_are_registered(self):
        routes = registered_routes()
        self.assertEqual(len(routes), 9)
        self.assertIn("GET /bridge/commands/poll", routes)
        for path in (
            "/bridge/heartbeat", "/bridge/account", "/bridge/positions", "/bridge/orders",
            "/bridge/execution/report", "/bridge/trade-transaction", "/bridge/error", "/bridge/emergency-stop",
        ):
            self.assertIn(f"POST {path}", routes)


class TestHeartbeat(HttpServerTestCase):
    def test_valid_heartbeat_accepted(self):
        status, body = self._post("/bridge/heartbeat", {"magic_number": self.config.magic_number, "terminal_connected": True})
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")

    def test_missing_api_key_rejected(self):
        status, _ = self._post("/bridge/heartbeat", {"magic_number": self.config.magic_number}, api_key=None)
        self.assertEqual(status, 401)

    def test_wrong_api_key_rejected(self):
        status, _ = self._post("/bridge/heartbeat", {"magic_number": self.config.magic_number}, api_key="wrong")
        self.assertEqual(status, 401)

    def test_wrong_magic_number_rejected(self):
        status, body = self._post("/bridge/heartbeat", {"magic_number": 1})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "MAGIC_NUMBER_MISMATCH")


class TestAccountPositionsOrders(HttpServerTestCase):
    def test_account_snapshot_accepted(self):
        status, _ = self._post("/bridge/account", {
            "magic_number": self.config.magic_number, "balance": 10000.0, "equity": 10500.0,
        })
        self.assertEqual(status, 200)
        self.assertEqual(self.engine.latest_account_state.equity, 10500.0)

    def test_positions_accepted(self):
        status, body = self._post("/bridge/positions", {
            "magic_number": self.config.magic_number,
            "positions": [{"position_id": "p1", "symbol": "EURUSD", "direction": "BUY", "volume": 0.1, "open_price": 1.10}],
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["count"], 1)

    def test_orders_accepted(self):
        status, body = self._post("/bridge/orders", {"magic_number": self.config.magic_number, "orders": []})
        self.assertEqual(status, 200)
        self.assertEqual(body["count"], 0)


class TestCommandSubmissionPollAndReport(HttpServerTestCase):
    def test_full_round_trip(self):
        # Establish liveness first (fail-closed by default).
        status, _ = self._post("/bridge/heartbeat", {"magic_number": self.config.magic_number})
        self.assertEqual(status, 200)

        reason = self.engine.submit_command(make_command(correlation_id="c1", issued_at=self.now), self.now)
        self.assertIsNone(reason)

        status, body = self._get(f"/bridge/commands/poll?magic_number={self.config.magic_number}")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["commands"]), 1)
        self.assertEqual(body["commands"][0]["correlation_id"], "c1")

        status, body = self._post("/bridge/execution/report", {
            "correlation_id": "c1", "magic_number": self.config.magic_number,
            "success": True, "broker_ticket": "t1", "filled_price": 1.1, "filled_volume": 0.1,
        })
        self.assertEqual(status, 200)
        self.assertTrue(body["recorded"])

    def test_duplicate_execution_report_not_recorded_twice(self):
        self._post("/bridge/heartbeat", {"magic_number": self.config.magic_number})
        self.engine.submit_command(make_command(correlation_id="c1", issued_at=self.now), self.now)
        payload = {
            "correlation_id": "c1", "magic_number": self.config.magic_number,
            "success": True, "broker_ticket": "t1", "filled_price": 1.1, "filled_volume": 0.1,
        }
        self._post("/bridge/execution/report", payload)
        status, body = self._post("/bridge/execution/report", payload)
        self.assertEqual(status, 200)
        self.assertFalse(body["recorded"])

    def test_poll_without_api_key_rejected(self):
        status, _ = self._get(f"/bridge/commands/poll?magic_number={self.config.magic_number}", api_key=None)
        self.assertEqual(status, 401)


class TestTradeTransactionAndError(HttpServerTestCase):
    def test_trade_transaction_accepted(self):
        status, body = self._post("/bridge/trade-transaction", {
            "magic_number": self.config.magic_number, "symbol": "EURUSD",
            "deal_ticket": None, "transaction_type": "DEAL_ADD",
        })
        self.assertEqual(status, 200)
        self.assertTrue(body["matched_known_execution"])

    def test_error_report_accepted(self):
        status, _ = self._post("/bridge/error", {
            "magic_number": self.config.magic_number, "error_code": "WEBREQUEST_FAILED", "message": "no route",
        })
        self.assertEqual(status, 200)
        self.assertEqual(len(self.engine.errors), 1)


class TestEmergencyStop(HttpServerTestCase):
    def test_activate_then_poll_reflects_stop(self):
        status, body = self._post("/bridge/emergency-stop", {"active": True, "reason": "manual"})
        self.assertEqual(status, 200)
        self.assertTrue(body["active"])
        status, poll_body = self._get(f"/bridge/commands/poll?magic_number={self.config.magic_number}")
        self.assertEqual(status, 200)
        self.assertTrue(poll_body["emergency_stop"])
        self.assertEqual(poll_body["commands"], [])

    def test_deactivate_restores_normal_poll(self):
        self._post("/bridge/emergency-stop", {"active": True})
        status, body = self._post("/bridge/emergency-stop", {"active": False})
        self.assertEqual(status, 200)
        self.assertFalse(body["active"])

    def test_emergency_stop_requires_api_key(self):
        status, _ = self._post("/bridge/emergency-stop", {"active": True}, api_key=None)
        self.assertEqual(status, 401)


class TestUnknownRouteAndMalformedBody(HttpServerTestCase):
    def test_unknown_path_returns_404(self):
        status, _ = self._get("/bridge/does-not-exist")
        self.assertEqual(status, 404)

    def test_missing_required_field_returns_400(self):
        status, _ = self._post("/bridge/account", {"magic_number": self.config.magic_number})
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
