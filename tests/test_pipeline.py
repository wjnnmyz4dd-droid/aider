"""Unit tests for the Phantom pipeline (stdlib unittest, no pytest needed)."""

from __future__ import annotations

import json
import threading
import unittest
import urllib.request
from datetime import datetime, timedelta, timezone

from phantom.app import create_app
from phantom.api import registered_routes, serve
from phantom.config import DEFAULT_CONFIG
from phantom.guards import ComplianceEngine, Guards
from phantom.orb import ORBContext, ORBEngine, ORBRange
from phantom.scanner import Scanner
from phantom.types import Candle, Decision, Direction, MarketSnapshot, Regime
from tests.fixtures import (
    NOW,
    approve_long_snapshot,
    guard_blocked_snapshot,
    ranging_snapshot,
    strong_approve_snapshot,
)


def _bare_snap(symbol="EURUSD", **kw):
    return MarketSnapshot(symbol=symbol, now=NOW, candles={}, spread=0.00008, **kw)


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
            "Strategy Confirmation",
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


class TestStrategies(unittest.TestCase):
    def _ctx(self, **over):
        from phantom.strategies.base import StrategyContext
        from phantom.structure import StructureSignal
        base = dict(
            regime=Regime.TRENDING_UP, h4_dir=Direction.LONG, d1_dir=Direction.LONG,
            bias=Direction.LONG, bos=StructureSignal(), choch=StructureSignal(),
            sweep=StructureSignal(), fvg=StructureSignal(), ob=StructureSignal(),
            news_safe=True, spread_safe=True, correlation_safe=True,
            exposure_safe={Direction.LONG: True, Direction.SHORT: True},
            atr=0.0005, exec_candles=[],
        )
        base.update(over)
        return StrategyContext(**base)

    def test_session_breakout_confirms(self):
        res = Scanner().scan_symbol(strong_approve_snapshot())
        sess = [s for s in res.strategies["signals"] if s["name"] == "Session Breakout"][0]
        self.assertTrue(sess["confirmed"])
        self.assertEqual(sess["direction"], "LONG")

    def test_liquidity_reversal_fires(self):
        from phantom.strategies.liquidity_reversal import LiquiditySweepReversal
        from phantom.structure import StructureSignal
        # A candle with a long lower wick (rejection of lows).
        c = Candle(strong_approve_snapshot().now, open=1.10, high=1.101, low=1.090, close=1.1005)
        ctx = self._ctx(
            sweep=StructureSignal(True, Direction.LONG, "swept sell-side"),
            choch=StructureSignal(True, Direction.LONG, "bullish choch"),
            ob=StructureSignal(True, Direction.LONG, "bullish OB"),
            exec_candles=[c],
        )
        sig = LiquiditySweepReversal().evaluate(strong_approve_snapshot(), ctx)
        self.assertTrue(sig.confirmed)
        self.assertEqual(sig.direction, Direction.LONG)
        self.assertEqual(sig.score, 15.0)  # Sweep+CHOCH 10 + OB 5

    def test_liquidity_reversal_blocked_high_vol(self):
        from phantom.strategies.liquidity_reversal import LiquiditySweepReversal
        sig = LiquiditySweepReversal().evaluate(
            strong_approve_snapshot(), self._ctx(regime=Regime.HIGH_VOLATILITY))
        self.assertTrue(sig.blocked)
        self.assertEqual(sig.score, 0.0)

    def test_conflict_dampens_and_flags(self):
        from phantom.strategies.engine import StrategyEngine
        from phantom.strategies.base import StrategySignal
        eng = StrategyEngine()
        out = eng.resolve([
            StrategySignal("ORB", Direction.LONG, score=18.0, confirmed=True),
            StrategySignal("Liquidity Reversal", Direction.SHORT, score=10.0, confirmed=True),
        ])
        self.assertTrue(out.conflict)
        self.assertEqual(out.direction, Direction.LONG)
        self.assertAlmostEqual(out.net_score, (18.0 - 10.0) * 0.5)  # dampened difference

    def test_agreement_capped_no_inflation(self):
        from phantom.strategies.engine import StrategyEngine
        from phantom.strategies.base import StrategySignal
        out = StrategyEngine().resolve([
            StrategySignal("ORB", Direction.LONG, score=18.0, confirmed=True),
            StrategySignal("Session Breakout", Direction.LONG, score=18.0, confirmed=True),
        ])
        self.assertFalse(out.conflict)
        self.assertLessEqual(out.net_score, 18.0)  # hard layer cap

    def test_false_breakout_penalty_applies(self):
        from phantom.strategies.engine import StrategyEngine
        from phantom.strategies.base import StrategySignal
        out = StrategyEngine().resolve([
            StrategySignal("ORB", Direction.NONE, penalty=-10.0, blocked=True),
        ])
        self.assertEqual(out.net_score, -10.0)


class TestAnalytics(unittest.TestCase):
    def test_profit_factor_and_ranking(self):
        from phantom.analytics import StrategyPerformanceTracker
        t = StrategyPerformanceTracker()
        for pnl in (100, -50, 80):      # ORB: gross +180 / -50 -> PF 3.6
            t.record("ORB", pnl)
        for pnl in (-30, -20, 10):      # Session: gross +10 / -50 -> PF 0.2
            t.record("Session Breakout", pnl)
        panel = t.panel()
        self.assertEqual(panel["strategies"]["ORB"]["trades"], 3)
        self.assertAlmostEqual(panel["strategies"]["ORB"]["profit_factor"], 3.6)
        self.assertEqual(panel["best"], "ORB")
        self.assertEqual(panel["worst"], "Session Breakout")

    def test_empty_panel_is_zeroed(self):
        from phantom.analytics import StrategyPerformanceTracker
        panel = StrategyPerformanceTracker().panel()
        self.assertIsNone(panel["best"])
        self.assertEqual(panel["strategies"]["ORB"]["trades"], 0)


class TestSafetyPatch(unittest.TestCase):
    # FIX 1 — ORB idempotency
    def test_orb_confirms_once_then_suppressed(self):
        eng = ORBEngine()
        ctx = _orb_ctx()
        d1 = eng.evaluate(approve_long_snapshot(), ctx)
        d2 = eng.evaluate(approve_long_snapshot(), ctx)
        self.assertTrue(d1.confirmed)
        self.assertFalse(d2.confirmed)
        self.assertIn("duplicate", d2.reason)
        self.assertEqual(d2.score_impact, 0.0)

    def test_orb_idempotency_via_scanner(self):
        s = Scanner()
        r1 = s.scan_symbol(approve_long_snapshot())
        r2 = s.scan_symbol(approve_long_snapshot())
        self.assertTrue(r1.orb.confirmed)
        self.assertFalse(r2.orb.confirmed)

    # FIX 2 — same-direction stacking blocked
    def test_exposure_blocks_same_direction_stacking(self):
        g = Guards()
        snap = _bare_snap(open_positions={"EURUSD": Direction.LONG})
        self.assertFalse(g.exposure(snap, Direction.LONG).passed)   # no pyramiding
        self.assertFalse(g.exposure(snap, Direction.SHORT).passed)  # conflict
        self.assertTrue(g.exposure(_bare_snap(), Direction.LONG).passed)  # flat ok

    def test_exposure_pct_cap(self):
        g = Guards()
        snap = _bare_snap(symbol_exposure_pct={"EURUSD": 100.0})
        self.assertFalse(g.exposure(snap, Direction.LONG).passed)

    # FIX 3 — correlation fail-closed
    def test_correlation_fail_closed_unknown_symbol(self):
        g = Guards()
        res = g.correlation(_bare_snap(symbol="EURGBP"), Direction.LONG)
        self.assertFalse(res.passed)
        self.assertIn("UNKNOWN_CORRELATION_BUCKET", res.detail)
        self.assertTrue(g.correlation(_bare_snap(symbol="EURUSD"), Direction.LONG).passed)

    # FIX 4 — compliance kill switch + daily lockout off live equity
    def test_compliance_daily_lockout(self):
        ce = ComplianceEngine()
        self.assertTrue(ce.check(_bare_snap(equity=10000)).passed)
        r = ce.check(_bare_snap(equity=9400))   # 6% daily DD > 5%
        self.assertFalse(r.passed)
        self.assertIn("DAILY_LOCKOUT", r.detail)
        self.assertFalse(ce.check(_bare_snap(equity=9990)).passed)  # locked rest of day

    def test_compliance_kill_switch_latches(self):
        ce = ComplianceEngine()
        ce.check(_bare_snap(equity=10000))
        r = ce.check(_bare_snap(equity=8900))   # 11% total DD > 10%
        self.assertFalse(r.passed)
        self.assertIn("KILL_SWITCH", r.detail)
        self.assertFalse(ce.check(_bare_snap(equity=10000)).passed)  # permanent

    def test_compliance_legacy_fallback_unchanged(self):
        ce = ComplianceEngine()
        self.assertTrue(ce.check(_bare_snap(account_drawdown_pct=0.0)).passed)

    # FIX 5 — symbol-aware spread
    def test_symbol_aware_spread(self):
        g = Guards()
        # 0.02 on USDJPY == 2 points (pip 0.01) -> ok; on EURUSD == 200 points -> block
        self.assertTrue(g.spread(_bare_snap(symbol="USDJPY")).passed)
        jpy_wide = MarketSnapshot("USDJPY", NOW, {}, spread=0.05)  # 5 points > 3
        self.assertFalse(g.spread(jpy_wide).passed)

    # FIX 6 — non-FX news exposure map
    def test_news_map_covers_non_fx(self):
        g = Guards()
        self.assertIn("USD", g._symbol_currencies("US30"))
        self.assertIn("USD", g._symbol_currencies("XAUUSD"))

    # FIX 7 — insufficient data state
    def test_insufficient_data_flag_and_cap(self):
        snap = approve_long_snapshot()
        snap.candles = {"M15": snap.candles["M15"][:10]}  # starve every timeframe
        res = Scanner().scan_symbol(snap)
        self.assertTrue(res.data_quality_flag)
        self.assertLessEqual(res.total, 55.0)
        self.assertNotEqual(res.decision, Decision.APPROVE)

    # FIX 8 — memory cleanup
    def test_orb_prune_removes_stale_state(self):
        eng = ORBEngine()
        old = (NOW - timedelta(days=10)).date().isoformat()
        eng._ranges["EURUSD:NEWYORK:" + old] = ORBRange(
            "EURUSD", "NEWYORK", old, 1.1, 1.09, NOW, NOW, True)
        eng._confirmed_sessions.add(("EURUSD", "NEWYORK", old))
        eng._processed_signal_ids["sig"] = old
        eng._prune(NOW)
        self.assertEqual(eng._ranges, {})
        self.assertEqual(eng._confirmed_sessions, set())
        self.assertEqual(eng._processed_signal_ids, {})

    # FIX 9 — thread safety (concurrent scan + status, no dict-race crash)
    def test_thread_safety_scan_and_status(self):
        app = create_app()
        errors = []

        def worker(n):
            try:
                for i in range(40):
                    snap = MarketSnapshot(f"SYM{n}{i%5}", NOW,
                                          strong_approve_snapshot().candles, spread=0.00008)
                    app.scan_symbol(snap)
                    app.orb.status(NOW)
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        ts = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(errors, [])


class TestApi(unittest.TestCase):
    def test_routes_registered(self):
        routes = registered_routes()
        self.assertIn("GET /orb/status", routes)
        self.assertIn("GET /strategies/performance", routes)

    def test_strategies_performance_endpoint(self):
        app = create_app()
        app.record_trade("ORB", 120.0)
        app.record_trade("ORB", -40.0)
        server = serve(app, host="127.0.0.1", port=0)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/strategies/performance") as r:
                self.assertEqual(r.status, 200)
                body = json.loads(r.read())
            self.assertIn("strategies", body)
            self.assertIn("best", body)
            self.assertEqual(body["strategies"]["ORB"]["trades"], 2)
        finally:
            server.shutdown()
            server.server_close()

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
