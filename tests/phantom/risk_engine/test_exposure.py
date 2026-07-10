"""Portfolio tests: exposure summary (heat, currency/symbol/long/short/
net exposure, pending reservations, unknown-state fail-closed tagging)."""

from __future__ import annotations

import unittest

from phantom.risk_engine.exposure import compute_exposure_summary, split_currency_pair
from phantom.risk_engine.models import DataQuality, Direction
from phantom.risk_engine.reservation import Reservation
from datetime import datetime, timezone
from tests.phantom.risk_engine._fixtures import make_open_position, make_portfolio_state


class TestSplitCurrencyPair(unittest.TestCase):
    def test_splits_six_letter_symbol(self):
        self.assertEqual(split_currency_pair("EURUSD"), ("EUR", "USD"))
        self.assertEqual(split_currency_pair("gbpjpy"), ("GBP", "JPY"))


class TestExposureSummary(unittest.TestCase):
    def test_unknown_portfolio_state_tagged_unknown(self):
        summary = compute_exposure_summary(None, ())
        self.assertEqual(summary.data_quality, DataQuality.UNKNOWN)
        self.assertEqual(summary.portfolio_heat_r, 0.0)

    def test_known_empty_portfolio_is_zero_heat(self):
        summary = compute_exposure_summary(make_portfolio_state([]), ())
        self.assertEqual(summary.data_quality, DataQuality.KNOWN)
        self.assertEqual(summary.portfolio_heat_r, 0.0)

    def test_long_short_net_exposure(self):
        positions = [
            make_open_position(pair="EURUSD", direction=Direction.LONG, size_r=1.0),
            make_open_position(pair="GBPUSD", direction=Direction.SHORT, size_r=0.5),
        ]
        summary = compute_exposure_summary(make_portfolio_state(positions), ())
        self.assertAlmostEqual(summary.long_exposure_r, 1.0)
        self.assertAlmostEqual(summary.short_exposure_r, 0.5)
        self.assertAlmostEqual(summary.net_exposure_r, 0.5)
        self.assertAlmostEqual(summary.portfolio_heat_r, 1.5)

    def test_currency_exposure_signed_by_direction(self):
        positions = [make_open_position(pair="EURUSD", direction=Direction.LONG, size_r=1.0)]
        summary = compute_exposure_summary(make_portfolio_state(positions), ())
        currency_map = dict(summary.currency_exposure_r)
        self.assertAlmostEqual(currency_map["EUR"], 1.0)
        self.assertAlmostEqual(currency_map["USD"], -1.0)

    def test_pending_reservations_included_in_heat_and_symbol_exposure(self):
        reservation = Reservation(reservation_id="RSV-1", pair="EURUSD", risk_r=0.5, created_at=datetime.now(timezone.utc))
        summary = compute_exposure_summary(make_portfolio_state([]), (reservation,))
        self.assertAlmostEqual(summary.portfolio_heat_r, 0.5)
        self.assertAlmostEqual(summary.pending_reservation_total_r, 0.5)
        symbol_map = dict(summary.symbol_exposure_r)
        self.assertAlmostEqual(symbol_map["EURUSD"], 0.5)

    def test_sector_exposure_is_future_ready_placeholder(self):
        summary = compute_exposure_summary(make_portfolio_state([]), ())
        self.assertEqual(summary.sector_exposure_r, ())


if __name__ == "__main__":
    unittest.main()
