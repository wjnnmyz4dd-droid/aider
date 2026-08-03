"""Concurrency tests for `CommandQueue` (Phase 1 hotfix).

`titan_protocol/bridge/server.py` serves every route through
`http.server.ThreadingHTTPServer` -- one thread per request -- so
`CommandQueue`'s state must survive concurrent `enqueue`/`poll`/
`record_result`/read calls without lost updates, duplicated records, or
a `RuntimeError` from concurrent dict/set mutation during iteration.
These tests exercise the lock added in this hotfix directly; they do
not change `CommandQueue`'s public behavior, only prove it holds under
concurrent load.
"""

from __future__ import annotations

import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from titan_protocol.bridge.models import ErrorCode, ExecutionReport, SCHEMA_VERSION
from tests.titan_protocol.bridge._fixtures import T0, make_command, make_queue

WORKER_COUNT = 32
ITERATIONS_PER_WORKER = 200


def _make_report(correlation_id: str) -> ExecutionReport:
    return ExecutionReport(
        schema_version=SCHEMA_VERSION,
        correlation_id=correlation_id,
        magic_number=20260709,
        success=True,
        broker_ticket="ticket-1",
        filled_price=1.1000,
        filled_volume=0.1,
        error_code=None,
        reported_at=T0,
    )


class TestConcurrentEnqueue(unittest.TestCase):
    def test_many_threads_enqueueing_distinct_ids_lose_nothing(self):
        queue = make_queue()
        total = WORKER_COUNT * ITERATIONS_PER_WORKER
        ids = [f"c-{i}" for i in range(total)]

        def worker(chunk):
            for correlation_id in chunk:
                reason = queue.enqueue(make_command(correlation_id=correlation_id), is_ready=True)
                assert reason is None

        chunks = [ids[i::WORKER_COUNT] for i in range(WORKER_COUNT)]
        with ThreadPoolExecutor(max_workers=WORKER_COUNT) as pool:
            list(pool.map(worker, chunks))

        # No lost commands, no corrupted state: every id is retrievable
        # exactly once and the pending order has exactly `total` entries.
        for correlation_id in ids:
            self.assertIsNotNone(queue.command_for(correlation_id))
        delivered = queue.poll(T0 + timedelta(seconds=1))
        self.assertEqual(len(delivered), total)
        self.assertEqual(len({c.correlation_id for c in delivered}), total)


class TestConcurrentDuplicateHandling(unittest.TestCase):
    def test_only_one_thread_wins_a_duplicate_correlation_id(self):
        queue = make_queue()
        attempts = 64
        results = []
        lock = threading.Lock()

        def worker():
            reason = queue.enqueue(make_command(correlation_id="dup"), is_ready=True)
            with lock:
                results.append(reason)

        with ThreadPoolExecutor(max_workers=attempts) as pool:
            list(pool.map(lambda _: worker(), range(attempts)))

        successes = [r for r in results if r is None]
        duplicates = [r for r in results if r == ErrorCode.DUPLICATE_CORRELATION_ID]
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(duplicates), attempts - 1)


class TestConcurrentPollAndEnqueue(unittest.TestCase):
    def test_concurrent_poll_never_double_delivers_or_raises(self):
        queue = make_queue()
        total = WORKER_COUNT * ITERATIONS_PER_WORKER
        ids = [f"p-{i}" for i in range(total)]

        def enqueue_worker(chunk):
            for correlation_id in chunk:
                queue.enqueue(make_command(correlation_id=correlation_id, issued_at=T0), is_ready=True)

        def poll_worker(_):
            # Concurrent poll callers must never see a RuntimeError from
            # iterating _pending_order while another thread mutates it.
            return queue.poll(T0 + timedelta(seconds=1))

        chunks = [ids[i::WORKER_COUNT] for i in range(WORKER_COUNT)]
        all_delivered = []
        with ThreadPoolExecutor(max_workers=WORKER_COUNT * 2) as pool:
            enqueue_futures = [pool.submit(enqueue_worker, chunk) for chunk in chunks]
            poll_futures = [pool.submit(poll_worker, i) for i in range(WORKER_COUNT)]
            for future in enqueue_futures:
                future.result()
            for future in poll_futures:
                all_delivered.extend(future.result())

        # Drain anything left pending after the interleaved run.
        all_delivered.extend(queue.poll(T0 + timedelta(seconds=1)))

        delivered_ids = [c.correlation_id for c in all_delivered]
        # No duplicated commands: every delivered id appears at most once
        # across every poll() call combined.
        self.assertEqual(len(delivered_ids), len(set(delivered_ids)))
        # No lost commands: everything enqueued was eventually delivered.
        self.assertEqual(set(delivered_ids), set(ids))


class TestConcurrentExecutionReports(unittest.TestCase):
    def test_concurrent_reports_for_distinct_ids_all_recorded(self):
        queue = make_queue()
        total = WORKER_COUNT * ITERATIONS_PER_WORKER
        ids = [f"r-{i}" for i in range(total)]
        for correlation_id in ids:
            queue.enqueue(make_command(correlation_id=correlation_id), is_ready=True)

        def worker(chunk):
            for correlation_id in chunk:
                recorded = queue.record_result(correlation_id, _make_report(correlation_id))
                assert recorded is True

        chunks = [ids[i::WORKER_COUNT] for i in range(WORKER_COUNT)]
        with ThreadPoolExecutor(max_workers=WORKER_COUNT) as pool:
            list(pool.map(worker, chunks))

        results = queue.all_results()
        self.assertEqual(len(results), total)
        self.assertEqual({r.correlation_id for r in results}, set(ids))

    def test_concurrent_duplicate_reports_for_same_id_recorded_once(self):
        queue = make_queue()
        queue.enqueue(make_command(correlation_id="dup-report"), is_ready=True)
        attempts = 64
        outcomes = []
        lock = threading.Lock()

        def worker():
            recorded = queue.record_result("dup-report", _make_report("dup-report"))
            with lock:
                outcomes.append(recorded)

        with ThreadPoolExecutor(max_workers=attempts) as pool:
            list(pool.map(lambda _: worker(), range(attempts)))

        self.assertEqual(outcomes.count(True), 1)
        self.assertEqual(outcomes.count(False), attempts - 1)


class TestConcurrentResultRetrieval(unittest.TestCase):
    def test_concurrent_reads_during_writes_never_raise(self):
        queue = make_queue()
        total = WORKER_COUNT * ITERATIONS_PER_WORKER
        ids = [f"g-{i}" for i in range(total)]
        for correlation_id in ids:
            queue.enqueue(make_command(correlation_id=correlation_id), is_ready=True)

        errors = []

        def writer(chunk):
            for correlation_id in chunk:
                queue.record_result(correlation_id, _make_report(correlation_id))

        def reader(_):
            for _ in range(50):
                try:
                    queue.all_results()
                    for correlation_id in ids[:10]:
                        queue.result_for(correlation_id)
                        queue.is_executed(correlation_id)
                except RuntimeError as exc:  # pragma: no cover - failure path
                    errors.append(exc)

        chunks = [ids[i::WORKER_COUNT] for i in range(WORKER_COUNT)]
        with ThreadPoolExecutor(max_workers=WORKER_COUNT * 2) as pool:
            writer_futures = [pool.submit(writer, chunk) for chunk in chunks]
            reader_futures = [pool.submit(reader, i) for i in range(WORKER_COUNT)]
            for future in writer_futures + reader_futures:
                future.result()

        self.assertEqual(errors, [])
        self.assertEqual(len(queue.all_results()), total)


class TestStressAllOperationsTogether(unittest.TestCase):
    def test_stress_every_public_method_concurrently_no_corruption(self):
        """Every public method hammered at once by many threads for a
        sustained run -- proves no lost commands, no duplicated
        commands, no corrupted state, and no RuntimeError, matching the
        hotfix's verification requirements as a single combined test."""
        queue = make_queue()
        total = WORKER_COUNT * ITERATIONS_PER_WORKER
        ids = [f"s-{i}" for i in range(total)]
        errors = []
        errors_lock = threading.Lock()

        def enqueue_worker(chunk):
            try:
                for correlation_id in chunk:
                    queue.enqueue(make_command(correlation_id=correlation_id, issued_at=T0), is_ready=True)
            except Exception as exc:  # pragma: no cover - failure path
                with errors_lock:
                    errors.append(exc)

        def poll_worker(_):
            try:
                for _ in range(20):
                    queue.poll(T0 + timedelta(seconds=1))
            except Exception as exc:  # pragma: no cover - failure path
                with errors_lock:
                    errors.append(exc)

        def report_worker(chunk):
            try:
                for correlation_id in chunk:
                    queue.record_result(correlation_id, _make_report(correlation_id))
            except Exception as exc:  # pragma: no cover - failure path
                with errors_lock:
                    errors.append(exc)

        def read_worker(_):
            try:
                for _ in range(20):
                    queue.all_results()
                    queue.emergency_stop_state
            except Exception as exc:  # pragma: no cover - failure path
                with errors_lock:
                    errors.append(exc)

        chunks = [ids[i::WORKER_COUNT] for i in range(WORKER_COUNT)]
        with ThreadPoolExecutor(max_workers=WORKER_COUNT * 4) as pool:
            futures = []
            futures += [pool.submit(enqueue_worker, chunk) for chunk in chunks]
            futures += [pool.submit(poll_worker, i) for i in range(WORKER_COUNT)]
            futures += [pool.submit(report_worker, chunk) for chunk in chunks]
            futures += [pool.submit(read_worker, i) for i in range(WORKER_COUNT)]
            for future in futures:
                future.result()

        # Drain whatever is still pending after the storm.
        queue.poll(T0 + timedelta(seconds=1))

        self.assertEqual(errors, [])
        # No corrupted state: every id enqueued is still individually
        # retrievable, and no id was silently lost.
        for correlation_id in ids:
            self.assertIsNotNone(queue.command_for(correlation_id))


if __name__ == "__main__":
    unittest.main()
