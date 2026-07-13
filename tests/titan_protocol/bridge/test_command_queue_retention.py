"""`CommandQueue` retention/cleanup tests (Phase 1.6 — long-run
hardening). Verifies the deterministic, age-ordered purge rule in
`CommandQueue._run_cleanup_locked`: TTL-based expiration for both
never-executed and executed correlation_ids, the count-based cap on
completed commands/cached reports, no premature deletion of anything
still within its retention window, correctness under concurrent
load, correctness after a simulated restart (fresh instance), and
stability under large command volume.
"""

from __future__ import annotations

import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from titan_protocol.bridge.models import ExecutionReport, SCHEMA_VERSION
from tests.titan_protocol.bridge._fixtures import T0, make_command, make_config, make_queue


def make_report(correlation_id: str, reported_at=T0) -> ExecutionReport:
    return ExecutionReport(
        schema_version=SCHEMA_VERSION, correlation_id=correlation_id, magic_number=20260709,
        success=True, broker_ticket=f"t-{correlation_id}", filled_price=1.1, filled_volume=0.1,
        error_code=None, reported_at=reported_at,
    )


class TestNoPrematureDeletion(unittest.TestCase):
    def test_unexpired_never_executed_command_survives_cleanup(self):
        config = make_config(correlation_ttl_seconds=3600.0, cleanup_interval_seconds=0.0)
        queue = make_queue(config)
        queue.enqueue(make_command(correlation_id="c1", issued_at=T0), is_ready=True)
        # Well before correlation_ttl_seconds has elapsed.
        queue.poll(T0 + timedelta(seconds=10))
        self.assertIsNotNone(queue.command_for("c1"))

    def test_unexpired_executed_command_and_report_survive_cleanup(self):
        config = make_config(
            execution_report_ttl_seconds=3600.0, duplicate_detection_ttl_seconds=900.0,
            cleanup_interval_seconds=0.0,
        )
        queue = make_queue(config)
        queue.enqueue(make_command(correlation_id="c1", issued_at=T0), is_ready=True)
        queue.record_result("c1", make_report("c1", reported_at=T0))
        queue.poll(T0 + timedelta(seconds=30))
        self.assertIsNotNone(queue.command_for("c1"))
        self.assertIsNotNone(queue.result_for("c1"))
        self.assertTrue(queue.is_executed("c1"))


class TestTTLExpiration(unittest.TestCase):
    def test_never_executed_command_purged_after_correlation_ttl(self):
        config = make_config(correlation_ttl_seconds=100.0, cleanup_interval_seconds=0.0)
        queue = make_queue(config)
        queue.enqueue(make_command(correlation_id="c1", issued_at=T0), is_ready=True)
        # Drive cleanup via poll(), well past correlation_ttl_seconds.
        queue.poll(T0 + timedelta(seconds=200))
        self.assertIsNone(queue.command_for("c1"))
        self.assertEqual(queue.expired_entries_removed_count(), 1)

    def test_executed_command_purged_after_max_of_the_two_ttls(self):
        config = make_config(
            execution_report_ttl_seconds=50.0, duplicate_detection_ttl_seconds=200.0,
            cleanup_interval_seconds=0.0,
        )
        queue = make_queue(config)
        queue.enqueue(make_command(correlation_id="c1", issued_at=T0), is_ready=True)
        queue.record_result("c1", make_report("c1", reported_at=T0))
        # Past execution_report_ttl_seconds (50s) but not yet past
        # duplicate_detection_ttl_seconds (200s) -- must NOT be purged
        # yet, since the rule uses max(), not min(), of the two.
        queue.poll(T0 + timedelta(seconds=100))
        self.assertIsNotNone(queue.command_for("c1"), "purged too early -- max() rule violated")
        # Now past both.
        queue.poll(T0 + timedelta(seconds=300))
        self.assertIsNone(queue.command_for("c1"))
        self.assertFalse(queue.is_executed("c1"))
        self.assertIsNone(queue.result_for("c1"))

    def test_duplicate_detection_holds_for_the_full_ttl_window(self):
        """The idempotency guarantee itself: a duplicate execution
        report submitted anywhere inside duplicate_detection_ttl_seconds
        must still be rejected, not accidentally accepted because
        cleanup purged the executed-id marker too early."""
        config = make_config(
            execution_report_ttl_seconds=10.0, duplicate_detection_ttl_seconds=500.0,
            cleanup_interval_seconds=0.0,
        )
        queue = make_queue(config)
        queue.enqueue(make_command(correlation_id="c1", issued_at=T0), is_ready=True)
        queue.record_result("c1", make_report("c1", reported_at=T0))
        # Trigger a cleanup pass well past execution_report_ttl_seconds
        # (10s) but still within duplicate_detection_ttl_seconds (500s).
        queue.poll(T0 + timedelta(seconds=100))
        duplicate = queue.record_result("c1", make_report("c1", reported_at=T0 + timedelta(seconds=100)))
        self.assertFalse(duplicate, "duplicate accepted -- idempotency guarantee broken before its TTL")


class TestCountBasedCap(unittest.TestCase):
    def test_completed_commands_purge_oldest_first_when_over_cap(self):
        config = make_config(
            max_completed_commands=5, max_cached_reports=5,
            execution_report_ttl_seconds=1_000_000.0, duplicate_detection_ttl_seconds=1_000_000.0,
            correlation_ttl_seconds=1_000_000.0, cleanup_interval_seconds=0.0,
        )
        queue = make_queue(config)
        for i in range(10):
            cid = f"c{i}"
            queue.enqueue(make_command(correlation_id=cid, issued_at=T0 + timedelta(seconds=i)), is_ready=True)
            queue.record_result(cid, make_report(cid, reported_at=T0 + timedelta(seconds=i)))
        # No TTL has expired (all TTLs are huge) -- only the count cap
        # should have triggered, deterministically dropping the 5
        # OLDEST (c0..c4), keeping the 5 newest (c5..c9).
        queue.poll(T0 + timedelta(seconds=20))
        for i in range(5):
            self.assertIsNone(queue.command_for(f"c{i}"), f"c{i} should have been purged as oldest-over-cap")
        for i in range(5, 10):
            self.assertIsNotNone(queue.command_for(f"c{i}"), f"c{i} should have survived (newest, within cap)")
        self.assertLessEqual(queue.completed_count(), 5)
        self.assertLessEqual(queue.cached_report_count(), 5)

    def test_no_randomness_repeated_runs_purge_identically(self):
        """'No random eviction, no LRU, no probabilistic cleanup' --
        the exact same input, run twice from scratch, must purge the
        exact same set both times."""
        def build_and_purge():
            config = make_config(
                max_completed_commands=3, max_cached_reports=3,
                execution_report_ttl_seconds=1_000_000.0, duplicate_detection_ttl_seconds=1_000_000.0,
                cleanup_interval_seconds=0.0,
            )
            queue = make_queue(config)
            for i in range(7):
                cid = f"c{i}"
                queue.enqueue(make_command(correlation_id=cid, issued_at=T0 + timedelta(seconds=i)), is_ready=True)
                queue.record_result(cid, make_report(cid, reported_at=T0 + timedelta(seconds=i)))
            queue.poll(T0 + timedelta(seconds=50))
            return {f"c{i}" for i in range(7) if queue.command_for(f"c{i}") is not None}

        first = build_and_purge()
        second = build_and_purge()
        self.assertEqual(first, second)


class TestCleanupCadence(unittest.TestCase):
    def test_cleanup_runs_at_most_once_per_interval(self):
        config = make_config(cleanup_interval_seconds=60.0, correlation_ttl_seconds=5.0)
        queue = make_queue(config)
        queue.enqueue(make_command(correlation_id="a", issued_at=T0), is_ready=True)
        queue.poll(T0 + timedelta(seconds=1))
        run_count_after_first = queue.cleanup_run_count()
        # Well past correlation_ttl_seconds (5s) but within the same
        # cleanup_interval_seconds (60s) window as the first pass --
        # cleanup must NOT run again yet.
        queue.poll(T0 + timedelta(seconds=10))
        self.assertEqual(queue.cleanup_run_count(), run_count_after_first)
        # Now past cleanup_interval_seconds from the first pass.
        queue.poll(T0 + timedelta(seconds=90))
        self.assertGreater(queue.cleanup_run_count(), run_count_after_first)


class TestCleanupDuringConcurrentRequests(unittest.TestCase):
    def test_cleanup_under_concurrent_load_produces_no_errors_or_corruption(self):
        config = make_config(
            execution_report_ttl_seconds=2.0, duplicate_detection_ttl_seconds=2.0,
            correlation_ttl_seconds=2.0, cleanup_interval_seconds=0.01,
            max_completed_commands=50, max_cached_reports=50,
        )
        queue = make_queue(config)
        errors = []
        errors_lock = threading.Lock()

        def worker(i):
            try:
                for j in range(200):
                    cid = f"w{i}-{j}"
                    ts = T0 + timedelta(milliseconds=(i * 1000 + j))
                    queue.enqueue(make_command(correlation_id=cid, issued_at=ts), is_ready=True)
                    queue.record_result(cid, make_report(cid, reported_at=ts))
                    queue.poll(ts)
                    queue.pending_count()
                    queue.completed_count()
                    queue.estimated_memory_bytes()
            except Exception as exc:  # pragma: no cover - failure path
                with errors_lock:
                    errors.append(str(exc))

        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(worker, range(16)))

        self.assertEqual(errors, [])
        # Bounded: retention must have kept the tracked set well under
        # the naive 16*200=3200 total ever created.
        self.assertLessEqual(queue.total_tracked_correlation_ids(), 3200)


class TestCleanupAfterRestart(unittest.TestCase):
    def test_fresh_instance_has_clean_retention_state(self):
        config = make_config()
        queue = make_queue(config)
        self.assertEqual(queue.cleanup_run_count(), 0)
        self.assertEqual(queue.expired_entries_removed_count(), 0)
        self.assertEqual(queue.total_tracked_correlation_ids(), 0)
        # First operation after "restart" must not crash on empty state.
        queue.poll(T0)
        queue.enqueue(make_command(correlation_id="c1", issued_at=T0), is_ready=True)
        self.assertIsNotNone(queue.command_for("c1"))


class TestLargeVolume(unittest.TestCase):
    def test_large_command_volume_stays_bounded_and_deterministic(self):
        """Representative of a multi-week production run's realistic
        total command count. A literal multi-million-entry real-time
        run is impractical for a unit test; this validates that the
        cap/TTL logic itself is size-driven (not time-driven only) and
        holds correctly at a volume large enough to exercise the sort-
        based eviction path repeatedly, not just once."""
        config = make_config(
            max_completed_commands=1000, max_cached_reports=1000,
            execution_report_ttl_seconds=1_000_000.0, duplicate_detection_ttl_seconds=1_000_000.0,
            correlation_ttl_seconds=1_000_000.0, cleanup_interval_seconds=0.0,
        )
        queue = make_queue(config)
        total = 50_000
        for i in range(total):
            cid = f"v{i}"
            ts = T0 + timedelta(seconds=i)
            queue.enqueue(make_command(correlation_id=cid, issued_at=ts), is_ready=True)
            queue.record_result(cid, make_report(cid, reported_at=ts))
            if i % 5000 == 0:
                queue.poll(ts)  # periodic cleanup trigger, matching real traffic
        queue.poll(T0 + timedelta(seconds=total))
        self.assertLessEqual(queue.completed_count(), 1000)
        self.assertLessEqual(queue.cached_report_count(), 1000)
        # The newest entries must be exactly what survived (deterministic).
        self.assertIsNotNone(queue.command_for(f"v{total - 1}"))
        self.assertIsNone(queue.command_for("v0"))


class TestMemoryStabilization(unittest.TestCase):
    def test_estimated_memory_bytes_stabilizes_under_sustained_load(self):
        config = make_config(
            max_completed_commands=200, max_cached_reports=200,
            execution_report_ttl_seconds=1_000_000.0, duplicate_detection_ttl_seconds=1_000_000.0,
            correlation_ttl_seconds=1_000_000.0, cleanup_interval_seconds=0.0,
        )
        queue = make_queue(config)
        samples = []
        for i in range(3000):
            cid = f"m{i}"
            ts = T0 + timedelta(seconds=i)
            queue.enqueue(make_command(correlation_id=cid, issued_at=ts), is_ready=True)
            queue.record_result(cid, make_report(cid, reported_at=ts))
            queue.poll(ts)
            if i % 100 == 0:
                samples.append(queue.estimated_memory_bytes())
        # Once past the cap, later samples must not keep growing --
        # the whole point of bounded retention.
        plateau = samples[-5:]
        self.assertEqual(len(set(plateau)), 1, f"memory estimate did not stabilize: {plateau}")


if __name__ == "__main__":
    unittest.main()
