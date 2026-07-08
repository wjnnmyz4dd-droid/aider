"""Full-stack HTTP tests for the EA Bridge server (`ADR-023` §4) — every
route exercised over a real socket via `urllib.request`, the same
end-to-end path the MQL5 EA itself uses."""

from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from phantom_pipeline.ea_bridge.broker_adapter import EABrokerAdapter
from phantom_pipeline.ea_bridge.command_queue import CommandQueue
from phantom_pipeline.ea_bridge.engine import EABridgeEngine
from phantom_pipeline.ea_bridge.http_server import API_KEY_HEADER, registered_routes, serve
from tests.phantom_pipeline.ea_bridge._fixtures import API_KEY, make_command, make_config, make_data_pipeline


class HttpServerTestCase(unittest.TestCase):
    def setUp(self):
        self.config = make_config()
        self.now = datetime(2026, 7, 8, 12, 0, 0, tzinfo=timezone.utc)
        self.queue = CommandQueue(self.config)
        self.adapter = EABrokerAdapter(self.queue, clock=lambda: self.now, config=self.config)
        self.engine = EABridgeEngine(self.config, make_data_pipeline(), self.queue, self.adapter)
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

    def _post(self, path: str, payload: dict, api_key: str | None = API_KEY):
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

    def _get(self, path: str, api_key: str | None = API_KEY):
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
        self.assertIn("GET /ea/commands/poll", routes)
        for path in (
            "/ea/heartbeat", "/ea/account", "/ea/tick", "/ea/bars", "/ea/positions",
            "/ea/execution/report", "/ea/error/report", "/ea/emergency-stop",
        ):
            self.assertIn(f"POST {path}", routes)


class TestHeartbeat(HttpServerTestCase):
    def test_valid_heartbeat_accepted(self):
        status, body = self._post("/ea/heartbeat", {
            "magic_number": self.config.magic_number, "connected": True,
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")

    def test_missing_api_key_rejected(self):
        status, body = self._post("/ea/heartbeat", {"magic_number": self.config.magic_number}, api_key=None)
        self.assertEqual(status, 401)

    def test_wrong_api_key_rejected(self):
        status, _ = self._post("/ea/heartbeat", {"magic_number": self.config.magic_number}, api_key="wrong")
        self.assertEqual(status, 401)

    def test_wrong_magic_number_rejected(self):
        status, body = self._post("/ea/heartbeat", {"magic_number": 1})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "magic_number_mismatch")


class TestAccountAndTickAndBars(HttpServerTestCase):
    def test_account_snapshot_accepted(self):
        status, _ = self._post("/ea/account", {
            "magic_number": self.config.magic_number, "equity": 10500.0, "balance": 10000.0,
        })
        self.assertEqual(status, 200)
        self.assertEqual(self.engine.latest_account_state.equity, 10500.0)

    def test_tick_accepted_for_allowed_symbol(self):
        status, _ = self._post("/ea/tick", {
            "magic_number": self.config.magic_number, "symbol": "EURUSD", "bid": 1.1, "ask": 1.1002,
        })
        self.assertEqual(status, 200)

    def test_tick_rejected_for_disallowed_symbol(self):
        status, body = self._post("/ea/tick", {
            "magic_number": self.config.magic_number, "symbol": "XAUUSD", "bid": 1.1, "ask": 1.1002,
        })
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "symbol_not_allowed")

    def test_bars_batch_accepted(self):
        status, body = self._post("/ea/bars", {
            "magic_number": self.config.magic_number,
            "bars": [{
                "symbol": "EURUSD", "timeframe": "M15", "open": 1.10, "high": 1.11,
                "low": 1.09, "close": 1.105, "volume": 100.0, "bar_time": self.now.isoformat(),
            }],
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["count"], 1)

    def test_bars_rejected_for_disallowed_symbol(self):
        status, body = self._post("/ea/bars", {
            "magic_number": self.config.magic_number,
            "bars": [{
                "symbol": "XAUUSD", "timeframe": "M15", "open": 1.0, "high": 1.0,
                "low": 1.0, "close": 1.0, "volume": 1.0, "bar_time": self.now.isoformat(),
            }],
        })
        self.assertEqual(status, 400)


class TestPositionsAndPoll(HttpServerTestCase):
    def test_positions_snapshot_accepted(self):
        status, body = self._post("/ea/positions", {
            "magic_number": self.config.magic_number,
            "positions": [{
                "position_id": "p1", "symbol": "EURUSD", "direction": "UP", "volume": 0.1,
                "open_price": 1.10,
            }],
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["count"], 1)

    def test_poll_with_header_api_key_returns_pending_commands(self):
        self.adapter.record_heartbeat(self.now)
        self.queue.enqueue(make_command(execution_id="exec-1", issued_at=self.now), is_ready=True)
        status, body = self._get(f"/ea/commands/poll?magic_number={self.config.magic_number}")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["commands"]), 1)
        self.assertEqual(body["commands"][0]["execution_id"], "exec-1")

    def test_poll_without_api_key_rejected(self):
        status, _ = self._get(f"/ea/commands/poll?magic_number={self.config.magic_number}", api_key=None)
        self.assertEqual(status, 401)


class TestExecutionAndErrorReport(HttpServerTestCase):
    def test_execution_report_recorded(self):
        self.queue.enqueue(make_command(execution_id="exec-1", issued_at=self.now), is_ready=True)
        status, body = self._post("/ea/execution/report", {
            "execution_id": "exec-1", "magic_number": self.config.magic_number,
            "success": True, "broker_ticket": "t1", "filled_price": 1.1, "filled_size": 0.1,
        })
        self.assertEqual(status, 200)
        self.assertTrue(body["recorded"])

    def test_duplicate_execution_report_not_recorded_twice(self):
        self.queue.enqueue(make_command(execution_id="exec-1", issued_at=self.now), is_ready=True)
        payload = {
            "execution_id": "exec-1", "magic_number": self.config.magic_number,
            "success": True, "broker_ticket": "t1", "filled_price": 1.1, "filled_size": 0.1,
        }
        self._post("/ea/execution/report", payload)
        status, body = self._post("/ea/execution/report", payload)
        self.assertEqual(status, 200)
        self.assertFalse(body["recorded"])

    def test_error_report_accepted(self):
        status, _ = self._post("/ea/error/report", {
            "magic_number": self.config.magic_number, "code": 4060, "message": "webrequest disabled",
        })
        self.assertEqual(status, 200)
        self.assertEqual(len(self.engine.errors), 1)


class TestEmergencyStop(HttpServerTestCase):
    def test_activate_then_poll_reflects_stop(self):
        status, body = self._post("/ea/emergency-stop", {"active": True, "reason": "manual"})
        self.assertEqual(status, 200)
        self.assertTrue(body["active"])
        status, poll_body = self._get(f"/ea/commands/poll?magic_number={self.config.magic_number}")
        self.assertEqual(status, 200)
        self.assertTrue(poll_body["emergency_stop"])
        self.assertEqual(poll_body["commands"], [])

    def test_deactivate_restores_normal_poll(self):
        self._post("/ea/emergency-stop", {"active": True})
        status, body = self._post("/ea/emergency-stop", {"active": False})
        self.assertEqual(status, 200)
        self.assertFalse(body["active"])

    def test_emergency_stop_requires_api_key(self):
        status, _ = self._post("/ea/emergency-stop", {"active": True}, api_key=None)
        self.assertEqual(status, 401)


class TestUnknownRouteAndMalformedBody(HttpServerTestCase):
    def test_unknown_path_returns_404(self):
        status, _ = self._get("/ea/does-not-exist")
        self.assertEqual(status, 404)

    def test_missing_required_field_returns_400(self):
        status, _ = self._post("/ea/account", {"magic_number": self.config.magic_number})
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
