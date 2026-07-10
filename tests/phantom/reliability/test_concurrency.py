"""Concurrency category: `ReliabilityEngine` is a genuinely stateful
observer (unlike the pure per-call trading engines), guarded by one
internal lock. Concurrent `report_heartbeat`/`record_cycle`/
`report_resource_usage`/`report_queue_depth`/`evaluate_health` calls
against one shared instance must never error and must leave the engine
in a consistent state."""

from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor

from phantom.reliability.engine import ReliabilityEngine
from phantom.runtime.models import CycleOutcome
from tests.phantom.reliability._fixtures import T0, make_audit_record, make_config, make_cycle_report


def _build_engine():
    return ReliabilityEngine(make_config())


class TestConcurrentReporting(unittest.TestCase):
    def test_concurrent_heartbeats_and_cycles_no_errors(self):
        engine = _build_engine()
        errors = []

        def worker(i):
            try:
                engine.report_heartbeat("evidence_engine", T0)
                engine.report_heartbeat("strategy_engine", T0)
                engine.record_cycle(make_cycle_report(
                    [make_audit_record(pair="EURUSD", outcome=CycleOutcome.SUBMITTED, cycle_id=f"C{i}", now=T0)]
                ))
                engine.report_queue_depth("bridge_commands", i % 10, T0)
                engine.evaluate_health(T0)
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))

        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(worker, range(64)))

        self.assertEqual(errors, [])

    def test_concurrent_record_cycle_produces_correct_total_count(self):
        engine = _build_engine()

        def worker(i):
            engine.record_cycle(make_cycle_report(
                [make_audit_record(pair="EURUSD", outcome=CycleOutcome.SUBMITTED, cycle_id=f"C{i}", now=T0)]
            ))

        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(worker, range(100)))

        health = engine.evaluate_health(T0)
        stats = {s.pair: s for s in health.cycle_stats}
        self.assertEqual(stats["EURUSD"].total_cycles, 100)

    def test_concurrent_evaluate_health_calls_agree(self):
        engine = _build_engine()
        for component in ("evidence_engine", "market_intelligence", "strategy_engine", "risk_engine"):
            engine.report_heartbeat(component, T0)
        engine.record_cycle(make_cycle_report([make_audit_record(now=T0)]))

        results = []

        def worker(_):
            snapshot = engine.evaluate_health(T0)
            results.append(snapshot.degradation_level)

        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(worker, range(32)))

        first = results[0]
        for result in results:
            self.assertEqual(result, first)


if __name__ == "__main__":
    unittest.main()
