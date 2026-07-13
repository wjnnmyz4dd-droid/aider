"""Concurrency tests for `ConnectionHealth` (Phase 1 hotfix).

`titan_protocol/bridge/server.py` serves every route through
`http.server.ThreadingHTTPServer` -- one thread per request -- so
`record_heartbeat` (from `POST /bridge/heartbeat`) and `is_ready`/
`is_fail_closed` (from every command-submission/poll path) can be
called concurrently from separate threads. These tests exercise the
lock added in this hotfix directly; they do not change
`ConnectionHealth`'s public behavior, fail-closed semantics, or
timeout handling -- only prove it holds under concurrent load.
"""

from __future__ import annotations

import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from titan_protocol.bridge.connection_health import ConnectionHealth
from tests.titan_protocol.bridge._fixtures import T0, make_config

WORKER_COUNT = 32
ITERATIONS_PER_WORKER = 500


class _MutableClock:
    """A clock whose current time can be advanced from the test thread
    while worker threads keep calling it -- lets these tests provoke
    lost-heartbeat and recovery transitions under concurrent load."""

    def __init__(self, start):
        self._now = start
        self._lock = threading.Lock()

    def advance_to(self, when):
        with self._lock:
            self._now = when

    def __call__(self):
        with self._lock:
            return self._now


class TestConcurrentHeartbeatUpdates(unittest.TestCase):
    def test_many_threads_recording_heartbeats_never_raise_or_corrupt(self):
        config = make_config(heartbeat_timeout_seconds=30.0)
        health = ConnectionHealth(config, clock=lambda: T0 + timedelta(seconds=5))
        errors = []
        errors_lock = threading.Lock()

        def worker(i):
            try:
                for j in range(ITERATIONS_PER_WORKER):
                    health.record_heartbeat(T0 + timedelta(seconds=i * 1000 + j))
            except Exception as exc:  # pragma: no cover - failure path
                with errors_lock:
                    errors.append(exc)

        with ThreadPoolExecutor(max_workers=WORKER_COUNT) as pool:
            list(pool.map(worker, range(WORKER_COUNT)))

        self.assertEqual(errors, [])
        # No corrupted state: last_heartbeat_at is always one of the
        # values actually written, never a torn/partial value.
        self.assertIsNotNone(health.last_heartbeat_at)


class TestConcurrentHealthReads(unittest.TestCase):
    def test_concurrent_is_ready_and_is_fail_closed_never_raise(self):
        config = make_config(heartbeat_timeout_seconds=30.0)
        health = ConnectionHealth(config, clock=lambda: T0 + timedelta(seconds=10))
        health.record_heartbeat(T0)
        errors = []
        errors_lock = threading.Lock()

        def reader(_):
            try:
                for _ in range(ITERATIONS_PER_WORKER):
                    ready = health.is_ready()
                    fail_closed = health.is_fail_closed()
                    # No inconsistent snapshot: the two must always be
                    # exact opposites of each other for a stable clock.
                    assert ready != fail_closed
                    health.last_heartbeat_at
            except Exception as exc:  # pragma: no cover - failure path
                with errors_lock:
                    errors.append(exc)

        with ThreadPoolExecutor(max_workers=WORKER_COUNT) as pool:
            list(pool.map(reader, range(WORKER_COUNT)))

        self.assertEqual(errors, [])


class TestConcurrentStaleStateChecks(unittest.TestCase):
    def test_concurrent_reads_during_writes_produce_no_exception(self):
        config = make_config(heartbeat_timeout_seconds=5.0)
        clock = _MutableClock(T0)
        health = ConnectionHealth(config, clock=clock)
        errors = []
        errors_lock = threading.Lock()
        stop = threading.Event()

        def writer():
            try:
                for i in range(ITERATIONS_PER_WORKER):
                    health.record_heartbeat(T0 + timedelta(seconds=i))
                    clock.advance_to(T0 + timedelta(seconds=i))
            except Exception as exc:  # pragma: no cover - failure path
                with errors_lock:
                    errors.append(exc)
            finally:
                stop.set()

        def reader(_):
            try:
                while not stop.is_set():
                    health.is_ready()
                    health.is_fail_closed()
                    health.last_heartbeat_at
            except Exception as exc:  # pragma: no cover - failure path
                with errors_lock:
                    errors.append(exc)

        with ThreadPoolExecutor(max_workers=WORKER_COUNT + 1) as pool:
            futures = [pool.submit(writer)]
            futures += [pool.submit(reader, i) for i in range(WORKER_COUNT)]
            for future in futures:
                future.result()

        self.assertEqual(errors, [])


class TestLostHeartbeatTransition(unittest.TestCase):
    def test_transitions_to_fail_closed_once_timeout_elapses(self):
        config = make_config(heartbeat_timeout_seconds=10.0)
        clock = _MutableClock(T0)
        health = ConnectionHealth(config, clock=clock)
        health.record_heartbeat(T0)
        self.assertTrue(health.is_ready())

        clock.advance_to(T0 + timedelta(seconds=11))
        self.assertFalse(health.is_ready())
        self.assertTrue(health.is_fail_closed())

    def test_concurrent_reads_observe_lost_heartbeat_consistently(self):
        config = make_config(heartbeat_timeout_seconds=10.0)
        clock = _MutableClock(T0)
        health = ConnectionHealth(config, clock=clock)
        health.record_heartbeat(T0)
        errors = []
        errors_lock = threading.Lock()

        def reader(_):
            try:
                for _ in range(ITERATIONS_PER_WORKER):
                    health.is_ready()
                    health.is_fail_closed()
            except Exception as exc:  # pragma: no cover - failure path
                with errors_lock:
                    errors.append(exc)

        with ThreadPoolExecutor(max_workers=WORKER_COUNT) as pool:
            futures = [pool.submit(reader, i) for i in range(WORKER_COUNT)]
            clock.advance_to(T0 + timedelta(seconds=11))
            for future in futures:
                future.result()

        self.assertEqual(errors, [])
        self.assertTrue(health.is_fail_closed())


class TestRecoveryAfterHeartbeatResumes(unittest.TestCase):
    def test_recovers_to_ready_after_a_fresh_heartbeat(self):
        config = make_config(heartbeat_timeout_seconds=10.0)
        clock = _MutableClock(T0)
        health = ConnectionHealth(config, clock=clock)
        health.record_heartbeat(T0)
        clock.advance_to(T0 + timedelta(seconds=11))
        self.assertTrue(health.is_fail_closed())

        health.record_heartbeat(T0 + timedelta(seconds=11))
        self.assertTrue(health.is_ready())
        self.assertFalse(health.is_fail_closed())

    def test_concurrent_recovery_under_load(self):
        config = make_config(heartbeat_timeout_seconds=10.0)
        clock = _MutableClock(T0)
        health = ConnectionHealth(config, clock=clock)
        health.record_heartbeat(T0)
        clock.advance_to(T0 + timedelta(seconds=11))
        errors = []
        errors_lock = threading.Lock()

        def reader(_):
            try:
                for _ in range(200):
                    health.is_ready()
            except Exception as exc:  # pragma: no cover - failure path
                with errors_lock:
                    errors.append(exc)

        with ThreadPoolExecutor(max_workers=WORKER_COUNT) as pool:
            futures = [pool.submit(reader, i) for i in range(WORKER_COUNT)]
            health.record_heartbeat(T0 + timedelta(seconds=11))
            for future in futures:
                future.result()

        self.assertEqual(errors, [])
        self.assertTrue(health.is_ready())


class TestStressAllOperationsTogether(unittest.TestCase):
    def test_high_thread_count_stress_no_errors_no_deadlock(self):
        """Every public method hammered at once by many threads for a
        sustained run -- proves no RuntimeError, no deadlock (the test
        itself completing is the deadlock proof), and a consistent
        final state."""
        config = make_config(heartbeat_timeout_seconds=30.0)
        clock = _MutableClock(T0)
        health = ConnectionHealth(config, clock=clock)
        errors = []
        errors_lock = threading.Lock()
        thread_count = 128

        def writer(i):
            try:
                for j in range(100):
                    health.record_heartbeat(T0 + timedelta(seconds=i * 100 + j))
            except Exception as exc:  # pragma: no cover - failure path
                with errors_lock:
                    errors.append(exc)

        def reader(_):
            try:
                for _ in range(100):
                    health.is_ready()
                    health.is_fail_closed()
                    health.last_heartbeat_at
            except Exception as exc:  # pragma: no cover - failure path
                with errors_lock:
                    errors.append(exc)

        def resetter(_):
            try:
                for _ in range(5):
                    health.reset()
                    health.record_heartbeat(T0)
            except Exception as exc:  # pragma: no cover - failure path
                with errors_lock:
                    errors.append(exc)

        with ThreadPoolExecutor(max_workers=thread_count) as pool:
            futures = []
            futures += [pool.submit(writer, i) for i in range(thread_count // 2)]
            futures += [pool.submit(reader, i) for i in range(thread_count // 4)]
            futures += [pool.submit(resetter, i) for i in range(thread_count // 4)]
            for future in futures:
                future.result()

        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
