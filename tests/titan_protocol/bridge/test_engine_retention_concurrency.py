"""Concurrency coverage for `BridgeEngine`'s Phase 1.6 bounded audit logs.

`_errors` and `_trade_transactions` moved from an unbounded `list` to a
`deque(maxlen=...)` in the Phase 1.6 long-run retention hardening pass.
`deque.append()` is documented as atomic under CPython's GIL (the same
guarantee the `list.append()` it replaced already relied on), so no new
lock was added -- this test empirically confirms that claim holds under
real concurrent load from many threads, and that the bound is respected
even while being hammered.
"""

from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor

from titan_protocol.bridge.command_queue import CommandQueue
from titan_protocol.bridge.connection_health import ConnectionHealth
from titan_protocol.bridge.engine import BridgeEngine
from titan_protocol.bridge.models import ErrorReport, SCHEMA_VERSION, TradeTransactionReport
from tests.titan_protocol.bridge._fixtures import T0, make_config

WORKER_COUNT = 32
ITERATIONS_PER_WORKER = 200
MAX_HISTORY = 50


def make_engine():
    config = make_config(max_error_history=MAX_HISTORY, max_trade_transaction_history=MAX_HISTORY)
    queue = CommandQueue(config)
    health = ConnectionHealth(config, clock=lambda: T0)
    engine = BridgeEngine(config, queue, health, clock=lambda: T0)
    return engine


def _make_error(i: int) -> ErrorReport:
    return ErrorReport(
        schema_version=SCHEMA_VERSION, magic_number=20260709, error_code="WEBREQUEST_FAILED",
        message=f"error-{i}", context="OnTimer", reported_at=T0,
    )


def _make_transaction(i: int) -> TradeTransactionReport:
    return TradeTransactionReport(
        schema_version=SCHEMA_VERSION, magic_number=20260709, symbol="EURUSD",
        deal_ticket=None, order_ticket=None, transaction_type="ORDER_ADD",
        volume=0.1, price=1.1, reported_at=T0,
    )


class TestConcurrentBoundedAuditLogs(unittest.TestCase):
    def test_concurrent_errors_never_raise_and_stay_bounded(self):
        engine = make_engine()
        total = WORKER_COUNT * ITERATIONS_PER_WORKER

        def worker(start):
            for i in range(start, start + ITERATIONS_PER_WORKER):
                engine.handle_error(_make_error(i))

        starts = [w * ITERATIONS_PER_WORKER for w in range(WORKER_COUNT)]
        with ThreadPoolExecutor(max_workers=WORKER_COUNT) as pool:
            list(pool.map(worker, starts))

        self.assertEqual(len(engine.errors), MAX_HISTORY)
        self.assertLessEqual(len(engine.errors), MAX_HISTORY)

    def test_concurrent_trade_transactions_never_raise_and_stay_bounded(self):
        engine = make_engine()

        def worker(start):
            for i in range(start, start + ITERATIONS_PER_WORKER):
                engine.handle_trade_transaction(_make_transaction(i))

        starts = [w * ITERATIONS_PER_WORKER for w in range(WORKER_COUNT)]
        with ThreadPoolExecutor(max_workers=WORKER_COUNT) as pool:
            list(pool.map(worker, starts))

        self.assertEqual(len(engine.trade_transactions), MAX_HISTORY)
        self.assertLessEqual(len(engine.trade_transactions), MAX_HISTORY)

    def test_mixed_concurrent_errors_and_transactions_no_corruption(self):
        engine = make_engine()

        def error_worker(start):
            for i in range(start, start + ITERATIONS_PER_WORKER):
                engine.handle_error(_make_error(i))

        def transaction_worker(start):
            for i in range(start, start + ITERATIONS_PER_WORKER):
                engine.handle_trade_transaction(_make_transaction(i))

        starts = [w * ITERATIONS_PER_WORKER for w in range(WORKER_COUNT)]
        with ThreadPoolExecutor(max_workers=WORKER_COUNT * 2) as pool:
            futures = [pool.submit(error_worker, s) for s in starts]
            futures += [pool.submit(transaction_worker, s) for s in starts]
            for f in futures:
                f.result()

        self.assertEqual(len(engine.errors), MAX_HISTORY)
        self.assertEqual(len(engine.trade_transactions), MAX_HISTORY)


if __name__ == "__main__":
    unittest.main()
