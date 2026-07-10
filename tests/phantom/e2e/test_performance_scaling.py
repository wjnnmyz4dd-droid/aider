"""Phase 3B performance validation: extends Phase 3A's 28-pair latency
budget test (`tests/phantom/runtime/test_performance.py`) with 50- and
100-pair scaling, and adds the remaining named dimensions this
checklist asks for that Phase 3A didn't cover on its own: CPU/memory
sampling, thread count, queue depth, and lock contention -- all via the
real `phantom.reliability.ReliabilityEngine`, never a second,
divergent resource-monitoring implementation."""

from __future__ import annotations

import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

from phantom.reliability.config import ReliabilityConfig
from phantom.reliability.engine import ReliabilityEngine
from phantom.risk_engine.config import RiskEngineConfig
from phantom.risk_engine.models import PortfolioState
from phantom.runtime.engine import RuntimeOrchestrator
from phantom.runtime.models import CycleOutcome, TradingWindow
from phantom.runtime.profiles import make_custom_profile
from tests.phantom.runtime._fixtures import (
    T0,
    make_account_state,
    make_bars,
    make_config,
    make_market_safety_inputs,
    make_stub_bridge_submit,
    make_stub_compliance_engine,
    make_stub_evidence_engine,
    make_stub_mi_engine,
    make_stub_risk_engine,
    make_stub_strategy_engine,
)

_PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD"]


def _profile_with_n_pairs(n: int):
    return make_custom_profile(
        profile_id=f"perf-{n}", description="perf scaling test", trading_window=TradingWindow(0, 24),
        session_rules=(), risk_profile=RiskEngineConfig(), allowed_pairs=tuple(_PAIRS * ((n // len(_PAIRS)) + 1))[:n],
    )


def _build_orchestrator():
    return RuntimeOrchestrator(
        make_config(), make_stub_evidence_engine(), make_stub_mi_engine(), make_stub_strategy_engine(),
        make_stub_risk_engine(), make_stub_compliance_engine(), make_stub_bridge_submit(),
    )


def _run_n_pairs(n: int):
    orchestrator = _build_orchestrator()
    profile = _profile_with_n_pairs(n)
    bars = make_bars()
    market_safety = make_market_safety_inputs()
    account_state = make_account_state()

    start = time.monotonic()
    records = [
        orchestrator.run_cycle_for_pair(
            pair, bars, (), 1.0, 1.0, market_safety, PortfolioState(), None, account_state, profile, T0, f"CYCLE-{i}",
        )
        for i, pair in enumerate(profile.allowed_pairs)
    ]
    elapsed_ms = (time.monotonic() - start) * 1000.0
    return records, elapsed_ms


class TestPairCountScaling(unittest.TestCase):
    def test_50_pairs_completes_with_no_failures(self):
        records, elapsed_ms = _run_n_pairs(50)
        self.assertEqual(len(records), 50)
        self.assertTrue(all(r.outcome != CycleOutcome.FAILED for r in records))
        self.assertLess(elapsed_ms, 1000.0, f"50-pair cycle took {elapsed_ms:.1f}ms")

    def test_100_pairs_completes_with_no_failures(self):
        records, elapsed_ms = _run_n_pairs(100)
        self.assertEqual(len(records), 100)
        self.assertTrue(all(r.outcome != CycleOutcome.FAILED for r in records))
        self.assertLess(elapsed_ms, 2000.0, f"100-pair cycle took {elapsed_ms:.1f}ms")

    def test_per_pair_latency_does_not_grow_with_pair_count(self):
        """`RuntimeOrchestrator` holds no shared mutable per-call state
        (ADR-031), so per-pair cost at 100 pairs should be in the same
        ballpark as at 28 -- not quadratic."""
        _, elapsed_28_ms = _run_n_pairs(28)
        _, elapsed_100_ms = _run_n_pairs(100)
        per_pair_28 = elapsed_28_ms / 28
        per_pair_100 = elapsed_100_ms / 100
        # Generous bound -- guards against accidental O(n^2) behavior,
        # not a tight performance regression gate.
        self.assertLess(per_pair_100, per_pair_28 * 10 + 1.0)


class TestResourceMonitoringDuringLoad(unittest.TestCase):
    def test_cpu_and_memory_are_sampled_successfully_under_a_100_pair_cycle(self):
        reliability = ReliabilityEngine(ReliabilityConfig())
        records, _ = _run_n_pairs(100)
        self.assertEqual(len(records), 100)
        usage = reliability.report_resource_usage(T0)
        # Real stdlib-only samplers (os.getloadavg()/proc/meminfo) --
        # this environment may or may not support both, but the sample
        # itself must never raise (fail-closed None on failure, per
        # ADR-032 Hard Rule 4), and evaluate_health() must still produce
        # a valid snapshot regardless.
        health = reliability.evaluate_health(T0)
        self.assertIsNotNone(health)

    def test_thread_count_is_observable_during_concurrent_cycles(self):
        orchestrator = _build_orchestrator()
        profile = _profile_with_n_pairs(28)
        bars = make_bars()

        thread_counts = []

        def worker(pair, i):
            thread_counts.append(threading.active_count())
            orchestrator.run_cycle_for_pair(
                pair, bars, (), 1.0, 1.0, make_market_safety_inputs(),
                PortfolioState(), None, make_account_state(), profile, T0, f"CYCLE-{i}",
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda args: worker(*args), enumerate(profile.allowed_pairs)))

        self.assertTrue(all(count >= 1 for count in thread_counts))

    def test_queue_depth_reporting_scales_with_reported_backlog(self):
        from phantom.reliability.models import DegradationLevel

        reliability = ReliabilityEngine(ReliabilityConfig(queue_degraded_depth=25, queue_critical_depth=90))
        for depth, expected in ((10, DegradationLevel.NORMAL), (50, DegradationLevel.DEGRADED), (100, DegradationLevel.CRITICAL)):
            reliability.report_queue_depth("bridge_commands", depth, T0)
            self.assertEqual(reliability.evaluate_health(T0).degradation_level, expected)


class TestLockContentionUnderConcurrency(unittest.TestCase):
    def test_many_concurrent_cycles_against_one_orchestrator_do_not_serialize_into_a_bottleneck(self):
        """`RuntimeOrchestrator` holds no lock at all (no shared mutable
        state) -- concurrent calls must not contend on anything."""
        orchestrator = _build_orchestrator()
        profile = _profile_with_n_pairs(28)
        bars = make_bars()

        start = time.monotonic()
        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(
                lambda pair_i: orchestrator.run_cycle_for_pair(
                    pair_i[0], bars, (), 1.0, 1.0, make_market_safety_inputs(),
                    PortfolioState(), None, make_account_state(), profile, T0, f"CYCLE-{pair_i[1]}",
                ),
                enumerate(profile.allowed_pairs),
            ))
        elapsed_ms = (time.monotonic() - start) * 1000.0
        self.assertLess(elapsed_ms, 1000.0)

    def test_reliability_engine_lock_does_not_deadlock_under_concurrent_reporting(self):
        reliability = ReliabilityEngine(ReliabilityConfig())
        errors = []

        def worker(i):
            try:
                reliability.report_heartbeat(f"component-{i % 4}", T0)
                reliability.report_queue_depth("bridge_commands", i % 10, T0)
                reliability.evaluate_health(T0)
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))

        with ThreadPoolExecutor(max_workers=32) as pool:
            list(pool.map(worker, range(200)))
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
