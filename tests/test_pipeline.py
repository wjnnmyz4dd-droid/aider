"""Unit tests for the Phantom pipeline (stdlib unittest, no pytest needed)."""

from __future__ import annotations

import json
import threading
import unittest
import urllib.request
from datetime import datetime, timezone

from phantom.app import create_app
from phantom.api import registered_routes, serve
from phantom.orb import ORBContext, ORBEngine
from phantom.scanner import Scanner
from phantom.types import Candle, Decision, Direction, Regime
from tests.fixtures import (
    approve_long_snapshot,
    guard_blocked_snapshot,
    ranging_snapshot,
    strong_approve_snapshot,
)


def _orb_ctx(regime=Regime.TRENDING_UP, news=True, spread=True, corr=True, atr=0.0005):
    return ORBContext(
        regime=regime,
        h4d1_aligned={Direction.LONG: True, Direction.SHORT: False},
        bos={Direction.LONG: True, Direction.SHORT: False},
        news_safe=news, spread_safe=spread, correlation_safe=corr,
        exposure_safe={Direction.LONG: True, Direction.SHORT: True}, atr=atr,
    )


class TestScoring(unittest.TestCase):
    def setUp(self):
        self.scanner = Scanner()

    def test_strong_setup_approves(self):
        res = self.scanner.scan_symbol(strong_approve_snapshot())
        self.assertEqual(res.decision, Decision.APPROVE)
        self.assertEqual(res.direction, Direction.LONG)
        self.assertGreaterEqual(res.total, 72.0)

    def test_moderate_setup_deflates_to_watchlist(self):
        # Same data that scored ~75 (APPROVE) under the old 19-component model
        # now lands in WATCHLIST after de-duplication — the intended deflation.
        res = self.scanner.scan_symbol(approve_long_snapshot())
        self.assertEqual(res.decision, Decision.WATCHLIST)
        self.assertLess(res.total, 72.0)

    def test_orb_confirmed_and_scores(self):
        res = self.scanner.scan_symbol(approve_long_snapshot())
        self.assertIsNotNone(res.orb)
        self.assertTrue(res.orb.confirmed)
        self.assertEqual(res.orb.breakout_direction, Direction.LONG)
        self.assertGreater(res.orb.score_impact, 0.0)

    def test_orb_never_trades_alone(self):
        # The ORB decision object exposes only score/flags — no order fields.
        res = self.scanner.scan_symbol(approve_long_snapshot())
        self.assertFalse(hasattr(res.orb, "order"))
        self.assertFalse(hasattr(res.orb, "execute"))

    def test_ranging_capped(self):
        res = self.scanner.scan_symbol(ranging_snapshot())
        self.assertNotEqual(res.decision, Decision.APPROVE)
        if res.capped_at is not None:
            self.assertLessEqual(res.total, 55.0)

    def test_guard_blocks(self):
        res = self.scanner.scan_symbol(guard_blocked_snapshot())
        self.assertEqual(res.decision, Decision.BLOCK)
        failed = [c.name for c in res.components if c.blocking and c.failed]
        self.assertIn("Spread Filter", failed)

    def test_component_list_is_the_18(self):
        res = self.scanner.scan_symbol(approve_long_snapshot())
        names = [c.name for c in res.components]
        expected = [
            "H4 Trend Alignment", "D1 Trend Alignment", "BOS", "CHOCH",
            "Liquidity Sweep", "FVG", "Order Block", "RSI Confirmation",
            "Volatility Health", "Session Filter", "News Filter",
            "Market Regime", "Spread Filter", "Correlation Guard",
            "Exposure Guard", "RR Validation", "Prop Compliance",
            "ORB Confirmation",
        ]
        for required in expected:
            self.assertIn(required, names)
        self.assertEqual(len(names), 18)

    def test_removed_and_merged_components_absent(self):
        names = [c.name for c in self.scanner.scan_symbol(approve_long_snapshot()).components]
        for gone in ("AI Meta Filter", "ATR", "Volatility Ratio"):
            self.assertNotIn(gone, names)

    def test_thesis_is_informational_only(self):
        res = self.scanner.scan_symbol(strong_approve_snapshot())
        self.assertTrue(res.thesis)
        # Thesis text must not be a scored component.
        self.assertNotIn("thesis", [c.name.lower() for c in res.components])
        # Sum of component points equals the (pre-cap) total; thesis adds nothing.
        additive = sum(c.points for c in res.components if not c.blocking)
        self.assertAlmostEqual(min(additive, 100.0), res.total, places=6)


class TestOrbBlocks(unittest.TestCase):
    def test_confirmed_full_stack(self):
        d = ORBEngine().evaluate(approve_long_snapshot(), _orb_ctx())
        self.assertTrue(d.confirmed)
        self.assertEqual(d.score_impact, 18.0)  # +8 confirmed, +5 trend, +5 BOS

    def test_high_volatility_blocks(self):
        d = ORBEngine().evaluate(approve_long_snapshot(), _orb_ctx(regime=Regime.HIGH_VOLATILITY))
        self.assertTrue(d.blocked)
        self.assertEqual(d.score_impact, 0.0)

    def test_news_blocks(self):
        d = ORBEngine().evaluate(approve_long_snapshot(), _orb_ctx(news=False))
        self.assertTrue(d.blocked)

    def test_range_too_small_blocks(self):
        d = ORBEngine().evaluate(approve_long_snapshot(), _orb_ctx(atr=1.0))
        self.assertTrue(d.blocked)
        self.assertIn("too small", d.reason)

    def test_false_breakout_penalty(self):
        snap = approve_long_snapshot()
        m = snap.candles["M15"]
        rng_bar = m[-3]
        mid = (rng_bar.high + rng_bar.low) / 2
        m[-1] = Candle(m[-1].ts, m[-1].open, m[-1].high, m[-1].low, mid)
        d = ORBEngine().evaluate(snap, _orb_ctx())
        self.assertTrue(d.false_breakout)
        self.assertEqual(d.score_impact, -10.0)


class TestApi(unittest.TestCase):
    def test_routes_registered(self):
        routes = registered_routes()
        self.assertIn("GET /orb/status", routes)

    def test_orb_status_endpoint(self):
        app = create_app()
        app.scan_symbol(approve_long_snapshot())
        server = serve(app, host="127.0.0.1", port=0)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/orb/status") as r:
                self.assertEqual(r.status, 200)
                body = json.loads(r.read())
            self.assertIn("active_sessions", body)
            self.assertIn("ranges", body)
            self.assertIn("last_decisions", body)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
