"""Unit + concurrency tests: the pending-exposure reservation ledger
(ADR-027 Hard Rule 5)."""

from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor

from phantom.risk_engine.reservation import ReservationLedger


class TestBasicLedger(unittest.TestCase):
    def test_reserve_and_release(self):
        ledger = ReservationLedger()
        reservation_id = ledger.reserve("EURUSD", 1.0)
        self.assertEqual(ledger.pending_total_r(), 1.0)
        self.assertTrue(ledger.release(reservation_id))
        self.assertEqual(ledger.pending_total_r(), 0.0)

    def test_release_unknown_id_returns_false(self):
        ledger = ReservationLedger()
        self.assertFalse(ledger.release("RSV-999"))

    def test_pending_for_pair(self):
        ledger = ReservationLedger()
        ledger.reserve("EURUSD", 1.0)
        ledger.reserve("GBPUSD", 2.0)
        self.assertEqual(ledger.pending_for_pair_r("EURUSD"), 1.0)
        self.assertEqual(ledger.pending_for_pair_r("GBPUSD"), 2.0)

    def test_len_reflects_reservation_count(self):
        ledger = ReservationLedger()
        ledger.reserve("EURUSD", 1.0)
        ledger.reserve("GBPUSD", 1.0)
        self.assertEqual(len(ledger), 2)


class TestReserveIf(unittest.TestCase):
    def test_predicate_false_does_not_reserve(self):
        ledger = ReservationLedger()
        result = ledger.reserve_if("EURUSD", 1.0, lambda pending: False)
        self.assertIsNone(result)
        self.assertEqual(len(ledger), 0)

    def test_predicate_true_reserves(self):
        ledger = ReservationLedger()
        result = ledger.reserve_if("EURUSD", 1.0, lambda pending: True)
        self.assertIsNotNone(result)
        self.assertEqual(len(ledger), 1)

    def test_predicate_sees_pending_state_before_this_reservation(self):
        ledger = ReservationLedger()
        ledger.reserve("EURUSD", 1.0)
        seen = {}

        def predicate(pending):
            seen["total"] = sum(r.risk_r for r in pending)
            return True

        ledger.reserve_if("GBPUSD", 1.0, predicate)
        self.assertEqual(seen["total"], 1.0)  # only the pre-existing reservation, not the new one


class TestConcurrency(unittest.TestCase):
    def test_concurrent_reserve_if_never_exceeds_limit(self):
        """100 threads race to reserve 1R each against a 10R total cap.
        The atomic check-then-reserve must ensure exactly 10 succeed."""

        ledger = ReservationLedger()
        cap = 10.0

        def worker(_):
            def predicate(pending):
                return sum(r.risk_r for r in pending) + 1.0 <= cap
            return ledger.reserve_if("EURUSD", 1.0, predicate)

        with ThreadPoolExecutor(max_workers=50) as pool:
            results = list(pool.map(worker, range(100)))

        successes = [r for r in results if r is not None]
        self.assertEqual(len(successes), 10)
        self.assertEqual(ledger.pending_total_r(), 10.0)


if __name__ == "__main__":
    unittest.main()
