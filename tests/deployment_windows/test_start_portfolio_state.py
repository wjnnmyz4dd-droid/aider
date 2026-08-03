"""Tests for start.py's PositionReport -> OpenPosition adapter and its use
in check_position_limits() (fixes: the live-cycle loop previously built
PortfolioState() with no arguments every cycle, so
portfolio_state.open_positions was permanently empty and
check_position_limits() could never reject a duplicate entry for an
already-open pair -- see deployment_windows/KNOWN_GAPS.md section 3)."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from ._fixtures import DEPLOYMENT_DIR  # noqa: F401 -- ensures deployment_windows/ is on sys.path

import start

from titan_protocol.bridge.models import PositionDirection, PositionReport
from titan_protocol.compliance_engine.models import (
    AccountState,
    ComplianceLockState,
    ComplianceRuleProfile,
)
from titan_protocol.compliance_engine.position_limits import check_position_limits
from titan_protocol.risk_engine.models import Direction, PortfolioState

_NOW = datetime(2026, 7, 20, tzinfo=timezone.utc)


def _report(position_id="P1", symbol="EURUSD", direction=PositionDirection.BUY, **kw):
    defaults = dict(
        schema_version=1,
        position_id=position_id,
        symbol=symbol,
        direction=direction,
        volume=0.1,
        open_price=1.1000,
        stop_loss=None,
        take_profit=None,
        unrealized_pnl=None,
        magic_number=20260710,
        received_at=_NOW,
    )
    defaults.update(kw)
    return PositionReport(**defaults)


def _account_state(**kw):
    defaults = dict(
        account_balance=10_000.0,
        daily_starting_balance=10_000.0,
        peak_balance=10_000.0,
        compliance_lock=ComplianceLockState(),
    )
    defaults.update(kw)
    return AccountState(**defaults)


class TestMapBridgePositionsToOpenPositions(unittest.TestCase):
    def test_zero_positions_maps_to_empty_tuple(self):
        self.assertEqual(start._map_bridge_positions_to_open_positions(()), ())

    def test_one_long_position_maps_correctly(self):
        mapped = start._map_bridge_positions_to_open_positions(
            (_report(direction=PositionDirection.BUY),)
        )
        self.assertEqual(len(mapped), 1)
        self.assertEqual(mapped[0].pair, "EURUSD")
        self.assertEqual(mapped[0].direction, Direction.LONG)

    def test_one_short_position_maps_correctly(self):
        mapped = start._map_bridge_positions_to_open_positions(
            (_report(direction=PositionDirection.SELL),)
        )
        self.assertEqual(len(mapped), 1)
        self.assertEqual(mapped[0].direction, Direction.SHORT)

    def test_multiple_positions_map_correctly(self):
        reports = (
            _report(position_id="P1", symbol="EURUSD", direction=PositionDirection.BUY),
            _report(position_id="P2", symbol="GBPUSD", direction=PositionDirection.SELL),
        )
        mapped = start._map_bridge_positions_to_open_positions(reports)
        self.assertEqual(len(mapped), 2)
        self.assertEqual({p.pair for p in mapped}, {"EURUSD", "GBPUSD"})
        by_pair = {p.pair: p for p in mapped}
        self.assertEqual(by_pair["EURUSD"].direction, Direction.LONG)
        self.assertEqual(by_pair["GBPUSD"].direction, Direction.SHORT)

    def test_malformed_record_missing_symbol_is_skipped_not_fatal(self):
        reports = (
            _report(position_id="BAD", symbol=""),
            _report(position_id="P2", symbol="GBPUSD"),
        )
        mapped = start._map_bridge_positions_to_open_positions(reports)
        self.assertEqual(len(mapped), 1)
        self.assertEqual(mapped[0].pair, "GBPUSD")

    def test_known_gap_size_r_is_zero_and_opened_at_is_received_at(self):
        """Documents, rather than hides, the two approximations this
        adapter makes -- see its docstring and KNOWN_GAPS.md section 3."""
        mapped = start._map_bridge_positions_to_open_positions((_report(),))
        self.assertEqual(mapped[0].size_r, 0.0)
        self.assertEqual(mapped[0].opened_at, _NOW)


class TestCheckPositionLimitsWithMappedPortfolioState(unittest.TestCase):
    def test_rejects_new_command_when_pair_already_at_limit(self):
        profile = ComplianceRuleProfile(max_positions_per_pair=1, max_open_positions=10)
        mapped = start._map_bridge_positions_to_open_positions((_report(symbol="EURUSD"),))
        portfolio = PortfolioState(open_positions=mapped)
        account = _account_state()

        violation, _exposure = check_position_limits("EURUSD", 1.0, portfolio, account, profile)

        from titan_protocol.compliance_engine.models import ComplianceRuleId
        self.assertEqual(violation, ComplianceRuleId.MAX_POSITIONS_PER_PAIR_EXCEEDED)

    def test_allows_new_command_for_a_different_pair(self):
        profile = ComplianceRuleProfile(max_positions_per_pair=1, max_open_positions=10)
        mapped = start._map_bridge_positions_to_open_positions((_report(symbol="EURUSD"),))
        portfolio = PortfolioState(open_positions=mapped)
        account = _account_state()

        violation, _exposure = check_position_limits("GBPUSD", 1.0, portfolio, account, profile)

        self.assertIsNone(violation)

    def test_zero_positions_still_allows_normal_trading(self):
        profile = ComplianceRuleProfile(max_positions_per_pair=1, max_open_positions=10)
        portfolio = PortfolioState(open_positions=())
        account = _account_state()

        violation, _exposure = check_position_limits("EURUSD", 1.0, portfolio, account, profile)

        self.assertIsNone(violation)


if __name__ == "__main__":
    unittest.main()
