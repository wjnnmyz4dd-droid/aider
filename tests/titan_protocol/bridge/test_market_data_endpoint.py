"""End-to-end tests for POST /bridge/market-data (Amendment 1, ADR-023)
-- exercised over a real socket, the same path the MQL5 EA itself uses.
Every assertion about bar/tick *content* validation (ordering, gaps,
duplicates, staleness) is really `MarketDataIngestionEngine`'s own
behavior, verified here only to confirm the wire path reaches it
unmodified -- never a second copy of that logic."""

from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Optional

from titan_protocol.bridge.command_queue import CommandQueue
from titan_protocol.bridge.connection_health import ConnectionHealth
from titan_protocol.bridge.engine import BridgeEngine
from titan_protocol.bridge.server import API_KEY_HEADER, serve
from titan_protocol.market_data_ingestion.config import MarketDataIngestionConfig
from titan_protocol.market_data_ingestion.engine import MarketDataIngestionEngine
from titan_protocol.market_data_ingestion.metrics import MarketDataIngestionMetrics
from tests.titan_protocol.bridge._fixtures import API_KEY, SYMBOL, make_config

T0 = datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc)


def _bar_payload(sequence_number: int, bar_open_time: str, close: float = 1.1000) -> dict:
    return {
        "symbol": SYMBOL,
        "timeframe": "M15",
        "broker_timestamp": "2026-07-09T12:00:00+00:00",
        "source_timestamp": "2026-07-09T12:00:00+00:00",
        "bar_open_time": bar_open_time,
        "open": 1.0990, "high": 1.1010, "low": 1.0980, "close": close,
        "volume": 120.0, "is_closed": True, "sequence_number": sequence_number,
        "bid": 1.09995, "ask": 1.10005,
    }


class MarketDataEndpointTestCase(unittest.TestCase):
    def setUp(self):
        self.config = make_config()
        self.market_data_config = MarketDataIngestionConfig(enabled_pairs=(SYMBOL,))
        self.market_data_metrics = MarketDataIngestionMetrics()
        self.market_data_engine = MarketDataIngestionEngine(self.market_data_config, self.market_data_metrics)
        self.queue = CommandQueue(self.config)
        self.health = ConnectionHealth(self.config, clock=lambda: T0)
        self.engine = BridgeEngine(self.config, self.queue, self.health, clock=lambda: T0, market_data_engine=self.market_data_engine)
        self.server = serve(self.engine, self.config, clock=lambda: T0, host="127.0.0.1", port=0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _post(self, payload: dict, api_key: Optional[str] = API_KEY):
        headers = {"Content-Type": "application/json"}
        if api_key is not None:
            headers[API_KEY_HEADER] = api_key
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/bridge/market-data",
            data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))


class TestBarIngestionOverHttp(MarketDataEndpointTestCase):
    def test_valid_bar_is_accepted_and_reaches_the_real_engine(self):
        status, body = self._post({
            "api_key": API_KEY, "magic_number": self.config.magic_number,
            "bar": _bar_payload(1, "2026-07-09T11:45:00+00:00"),
        })
        self.assertEqual(status, 200)
        self.assertTrue(body["bar"]["accepted"])
        # Proves the wire path really reached MarketDataIngestionEngine,
        # not just returned a hardcoded success -- get_bars() reflects it.
        from titan_protocol.market_data_ingestion.models import Timeframe
        bars = self.market_data_engine.get_bars(SYMBOL, Timeframe.M15)
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].close, 1.1000)

    def test_missing_api_key_rejected(self):
        status, body = self._post({"bar": _bar_payload(1, "2026-07-09T11:45:00+00:00")}, api_key=None)
        self.assertEqual(status, 401)
        self.assertIn("error", body)

    def test_wrong_magic_number_rejected(self):
        status, body = self._post({
            "api_key": API_KEY, "magic_number": self.config.magic_number + 1,
            "bar": _bar_payload(1, "2026-07-09T11:45:00+00:00"),
        })
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "MAGIC_NUMBER_MISMATCH")

    def test_neither_bar_nor_tick_rejected(self):
        status, body = self._post({"api_key": API_KEY, "magic_number": self.config.magic_number})
        self.assertEqual(status, 400)

    def test_unknown_timeframe_rejected_with_400(self):
        bad = _bar_payload(1, "2026-07-09T11:45:00+00:00")
        bad["timeframe"] = "M3"  # not a real Timeframe value
        status, _body = self._post({"api_key": API_KEY, "magic_number": self.config.magic_number, "bar": bad})
        self.assertEqual(status, 400)

    def test_duplicate_bar_rejected_by_the_real_ingestion_engine_not_a_second_check(self):
        """Confirms duplicate detection is MarketDataIngestionEngine's,
        reached unmodified through this endpoint -- not reimplemented."""
        payload = {"api_key": API_KEY, "magic_number": self.config.magic_number, "bar": _bar_payload(1, "2026-07-09T11:45:00+00:00")}
        status1, body1 = self._post(payload)
        status2, body2 = self._post(payload)
        self.assertEqual(status1, 200)
        self.assertTrue(body1["bar"]["accepted"])
        self.assertEqual(status2, 200)
        self.assertFalse(body2["bar"]["accepted"])
        self.assertEqual(body2["bar"]["rejection_reason"], "DUPLICATE")

    def test_out_of_order_bar_detected_as_a_gap_by_the_real_engine(self):
        first = {"api_key": API_KEY, "magic_number": self.config.magic_number, "bar": _bar_payload(1, "2026-07-09T11:00:00+00:00")}
        second = {"api_key": API_KEY, "magic_number": self.config.magic_number, "bar": _bar_payload(2, "2026-07-09T13:00:00+00:00")}
        self._post(first)
        _status, body2 = self._post(second)
        self.assertTrue(body2["bar"]["accepted"])
        self.assertTrue(body2["bar"]["gap_detected"])


class TestTickIngestionOverHttp(MarketDataEndpointTestCase):
    def test_valid_tick_is_accepted_and_reaches_the_real_engine(self):
        status, body = self._post({
            "api_key": API_KEY, "magic_number": self.config.magic_number,
            "tick": {"symbol": SYMBOL, "bid": 1.0999, "ask": 1.1001},
        })
        self.assertEqual(status, 200)
        self.assertTrue(body["tick"]["accepted"])
        self.assertIsNotNone(self.market_data_engine.latest_spread(SYMBOL))

    def test_tick_for_unknown_symbol_rejected(self):
        status, body = self._post({
            "api_key": API_KEY, "magic_number": self.config.magic_number,
            "tick": {"symbol": "GBPUSD", "bid": 1.25, "ask": 1.2502},
        })
        self.assertEqual(status, 200)  # transport accepted; content rejected
        self.assertFalse(body["tick"]["accepted"])
        self.assertEqual(body["tick"]["rejection_reason"], "UNKNOWN_SYMBOL")

    def test_bar_and_tick_can_be_reported_in_one_call(self):
        status, body = self._post({
            "api_key": API_KEY, "magic_number": self.config.magic_number,
            "bar": _bar_payload(1, "2026-07-09T11:45:00+00:00"),
            "tick": {"symbol": SYMBOL, "bid": 1.0999, "ask": 1.1001},
        })
        self.assertEqual(status, 200)
        self.assertTrue(body["bar"]["accepted"])
        self.assertTrue(body["tick"]["accepted"])


class TestMarketDataEngineNotConfigured(unittest.TestCase):
    """Backward compatibility: a BridgeEngine constructed the old way
    (no market_data_engine, exactly every pre-Amendment-1 call site and
    test) must not crash -- the endpoint reports a clear 503 instead."""

    def setUp(self):
        self.config = make_config()
        self.queue = CommandQueue(self.config)
        self.health = ConnectionHealth(self.config, clock=lambda: T0)
        self.engine = BridgeEngine(self.config, self.queue, self.health, clock=lambda: T0)  # no market_data_engine
        self.server = serve(self.engine, self.config, clock=lambda: T0, host="127.0.0.1", port=0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def test_returns_503_when_no_market_data_engine_was_configured(self):
        headers = {"Content-Type": "application/json", API_KEY_HEADER: API_KEY}
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/bridge/market-data",
            data=json.dumps({"magic_number": self.config.magic_number, "bar": _bar_payload(1, "2026-07-09T11:45:00+00:00")}).encode("utf-8"),
            headers=headers, method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                status = response.status
        except urllib.error.HTTPError as exc:
            status = exc.code
        self.assertEqual(status, 503)
        self.assertFalse(self.engine.has_market_data_engine)


if __name__ == "__main__":
    unittest.main()
