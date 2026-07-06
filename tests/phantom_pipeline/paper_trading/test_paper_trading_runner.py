"""PaperTradingRunner tests — verifies the demo-account guard, the
weekend skip, and that every trading-relevant method is a thin,
same-signature delegation to `PipelineOrchestrator`'s own public method
(never a second decision path). Uses fake orchestrator/adapter doubles;
the real `PipelineOrchestrator` is exercised in
`test_integration.py`."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from phantom_pipeline.paper_trading.account_tracker import AccountTracker
from phantom_pipeline.paper_trading.paper_trading_runner import PaperTradingRunner
from phantom_pipeline.paper_trading.session_manager import SessionManager

T0 = datetime(2026, 7, 6, 10, 0, 0, tzinfo=timezone.utc)  # Monday
WEEKEND_T = datetime(2026, 7, 11, 12, 0, 0, tzinfo=timezone.utc)  # Saturday


class _FakeOrchestrator:
    def __init__(self) -> None:
        self.data_pipeline = object()
        self.run_scan_cycle_calls: List[tuple] = []
        self.record_fill_calls: List[tuple] = []
        self.manage_position_calls: List[tuple] = []
        self.evaluate_watchdog_health_calls: List[tuple] = []
        self.render_dashboard_snapshot_calls: List[tuple] = []

    def run_scan_cycle(self, symbol, timeframes, primary_timeframe, session_time, now, *args, **kwargs):
        self.run_scan_cycle_calls.append((symbol, timeframes, primary_timeframe, session_time, now))
        return "scan-cycle-result"

    def record_fill(self, trace_id, fill):
        self.record_fill_calls.append((trace_id, fill))
        return True

    def manage_position(self, *args, **kwargs):
        self.manage_position_calls.append((args, kwargs))
        return "position-cycle-result"

    def evaluate_watchdog_health(self, now, extra_signals=()):
        self.evaluate_watchdog_health_calls.append((now, extra_signals))
        return "system-health"

    def render_dashboard_snapshot(self, now, **kwargs):
        self.render_dashboard_snapshot_calls.append((now, kwargs))
        return {"OVERVIEW": "view"}


class _FakeMT5Adapter:
    def __init__(self, equity: Optional[float] = 10000.0) -> None:
        self.connected = False
        self.equity = equity

    def connect(self) -> bool:
        self.connected = True
        return True

    def disconnect(self) -> None:
        self.connected = False

    def query_account_equity(self) -> Optional[float]:
        return self.equity


class _FakeMarketDataAdapter:
    def __init__(self) -> None:
        self.connected = False
        self.poll_calls: List[tuple] = []

    def connect(self) -> bool:
        self.connected = True
        return True

    def disconnect(self) -> None:
        self.connected = False

    def poll_ticks(self, pipeline, symbol, **kwargs):
        self.poll_calls.append((pipeline, symbol))
        return []


def _runner(confirm_demo=lambda: True):
    return PaperTradingRunner(
        orchestrator=_FakeOrchestrator(),
        mt5_adapter=_FakeMT5Adapter(),
        market_data_adapter=_FakeMarketDataAdapter(),
        session_manager=SessionManager(),
        account_tracker=AccountTracker(initial_equity=10000.0),
        confirm_demo_account=confirm_demo,
    )


class TestDemoAccountGuard(unittest.TestCase):
    def test_connect_refuses_when_not_demo(self):
        runner = _runner(confirm_demo=lambda: False)
        with self.assertRaises(RuntimeError):
            runner.connect()

    def test_connect_succeeds_when_demo_confirmed(self):
        runner = _runner()
        self.assertTrue(runner.connect())

    def test_run_scan_cycle_refuses_without_connect(self):
        runner = _runner()
        with self.assertRaises(RuntimeError):
            runner.run_scan_cycle("EURUSD", ["M1"], "M1", T0, T0)

    def test_every_method_re_checks_demo_confirmation_each_call(self):
        calls = {"count": 0}

        def confirm():
            calls["count"] += 1
            return True

        runner = _runner(confirm_demo=confirm)
        runner.connect()
        runner.run_scan_cycle("EURUSD", ["M1"], "M1", T0, T0)
        runner.evaluate_watchdog_health(T0)
        self.assertGreaterEqual(calls["count"], 3)  # connect + 2 cycle calls

    def test_methods_raise_if_confirmation_flips_to_false_mid_session(self):
        state = {"demo": True}
        runner = _runner(confirm_demo=lambda: state["demo"])
        runner.connect()
        state["demo"] = False
        with self.assertRaises(RuntimeError):
            runner.run_scan_cycle("EURUSD", ["M1"], "M1", T0, T0)


class TestWeekendHandling(unittest.TestCase):
    def test_run_scan_cycle_skipped_on_weekend(self):
        runner = _runner()
        runner.connect()
        result = runner.run_scan_cycle("EURUSD", ["M1"], "M1", WEEKEND_T, WEEKEND_T)
        self.assertIsNone(result)
        self.assertEqual(runner._orchestrator.run_scan_cycle_calls, [])

    def test_run_scan_cycle_proceeds_on_trading_day(self):
        runner = _runner()
        runner.connect()
        result = runner.run_scan_cycle("EURUSD", ["M1"], "M1", T0, T0)
        self.assertEqual(result, "scan-cycle-result")
        self.assertEqual(len(runner._orchestrator.run_scan_cycle_calls), 1)

    def test_live_tick_pulled_before_scan_cycle(self):
        runner = _runner()
        runner.connect()
        runner.run_scan_cycle("EURUSD", ["M1"], "M1", T0, T0)
        self.assertEqual(len(runner._market_data_adapter.poll_calls), 1)
        self.assertEqual(runner._market_data_adapter.poll_calls[0][1], "EURUSD")


class TestDelegation(unittest.TestCase):
    def test_record_fill_delegates_to_orchestrator(self):
        runner = _runner()
        runner.connect()
        result = runner.record_fill("trace-1", "fill-object")
        self.assertTrue(result)
        self.assertEqual(runner._orchestrator.record_fill_calls, [("trace-1", "fill-object")])

    def test_manage_position_delegates_to_orchestrator(self):
        runner = _runner()
        runner.connect()
        result = runner.manage_position(position_id="p1")
        self.assertEqual(result, "position-cycle-result")
        self.assertEqual(len(runner._orchestrator.manage_position_calls), 1)

    def test_evaluate_watchdog_health_delegates(self):
        runner = _runner()
        runner.connect()
        result = runner.evaluate_watchdog_health(T0)
        self.assertEqual(result, "system-health")

    def test_render_dashboard_snapshot_delegates(self):
        runner = _runner()
        runner.connect()
        result = runner.render_dashboard_snapshot(T0)
        self.assertEqual(result, {"OVERVIEW": "view"})


class TestAccountObservation(unittest.TestCase):
    def test_observe_account_uses_mt5_equity(self):
        runner = _runner()
        runner.connect()
        snapshot = runner.observe_account(T0)
        self.assertEqual(snapshot.equity, 10000.0)

    def test_observe_account_raises_when_equity_unavailable(self):
        runner = PaperTradingRunner(
            orchestrator=_FakeOrchestrator(), mt5_adapter=_FakeMT5Adapter(equity=None),
            market_data_adapter=_FakeMarketDataAdapter(), session_manager=SessionManager(),
            account_tracker=AccountTracker(initial_equity=10000.0), confirm_demo_account=lambda: True,
        )
        runner.connect()
        with self.assertRaises(RuntimeError):
            runner.observe_account(T0)


if __name__ == "__main__":
    unittest.main()
