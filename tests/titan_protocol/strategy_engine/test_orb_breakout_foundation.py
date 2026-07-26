"""ADR-035 Phase 1 -- ORB Strategy Foundation tests.

Phase 1 introduces `StrategyId.OPENING_RANGE_BREAKOUT` and
`OrbBreakoutStrategy` for range-formed/valid gating only -- no
breakout-qualification rule exists yet (Phase 2's own scope), so
`OrbBreakoutStrategy.qualify()` must never return `QUALIFIED` under any
input. `test_architecture.py` (unmodified) already scans every file
under `titan_protocol/strategy_engine/` -- including this phase's new
`orb_breakout.py` -- for forbidden imports/vocabulary, so that coverage
is not duplicated here."""

from __future__ import annotations

import dataclasses
import unittest
from datetime import timedelta

from titan_protocol.evidence_engine.models import OpeningRangeState, SessionName
from titan_protocol.strategy_engine.config import DEFAULT_APPROVED_PAIRS_BY_STRATEGY, StrategyEngineConfig
from titan_protocol.strategy_engine.models import QualificationStatus, StrategyId, TradeIntent
from titan_protocol.strategy_engine.strategies import OrbBreakoutStrategy
from titan_protocol.strategy_engine.strategies.base import Strategy
from tests.titan_protocol.strategy_engine._fixtures import T0, make_config, make_evidence_snapshot, make_mi_snapshot

_ORB_APPROVED_CONFIG = StrategyEngineConfig(
    approved_pairs_by_strategy=DEFAULT_APPROVED_PAIRS_BY_STRATEGY + ((StrategyId.OPENING_RANGE_BREAKOUT, ("EURUSD",)),),
)


def _make_opening_range(is_formed: bool, is_valid: bool) -> OpeningRangeState:
    range_start = T0 - timedelta(minutes=30)
    return OpeningRangeState(
        session=SessionName.LONDON_NEW_YORK_OVERLAP,
        range_start=range_start,
        range_end=T0,
        range_start_index=0,
        range_end_index=3,
        range_high=1.105,
        range_low=1.095,
        range_midpoint=1.10,
        is_formed=is_formed,
        is_valid=is_valid,
    )


def _evidence_with_ranges(*ranges: OpeningRangeState):
    return dataclasses.replace(make_evidence_snapshot(), opening_ranges=tuple(ranges))


class TestStrategyIdMembership(unittest.TestCase):
    def test_opening_range_breakout_exists(self):
        self.assertIn("OPENING_RANGE_BREAKOUT", StrategyId.__members__)
        self.assertEqual(StrategyId.OPENING_RANGE_BREAKOUT.value, "OPENING_RANGE_BREAKOUT")

    def test_five_legacy_strategy_ids_remain(self):
        for name in ("LIQUIDITY_SWEEP_MSS", "BOS_FVG", "TREND_CONTINUATION", "SESSION_BREAKOUT", "RANGE_REVERSAL"):
            self.assertIn(name, StrategyId.__members__)


class TestStrategyContract(unittest.TestCase):
    def test_orb_breakout_strategy_conforms_to_strategy_interface(self):
        strategy = OrbBreakoutStrategy()
        self.assertIsInstance(strategy, Strategy)
        self.assertEqual(strategy.definition.strategy_id, StrategyId.OPENING_RANGE_BREAKOUT)

    def test_orb_breakout_strategy_is_stateless(self):
        strategy = OrbBreakoutStrategy()
        self.assertEqual(vars(strategy), {}, "OrbBreakoutStrategy must hold no instance state in Phase 1")


class TestEligibilityGate(unittest.TestCase):
    def test_approved_pairs_for_falls_back_to_empty_with_zero_config(self):
        self.assertEqual(make_config().approved_pairs_for(StrategyId.OPENING_RANGE_BREAKOUT), ())

    def test_unapproved_pair_returns_not_eligible_with_zero_score(self):
        strategy = OrbBreakoutStrategy()
        result = strategy.qualify("EURUSD", make_evidence_snapshot(), make_mi_snapshot(), make_config())
        self.assertEqual(result.status, QualificationStatus.NOT_ELIGIBLE)
        self.assertEqual(result.score, 0.0)
        self.assertEqual(result.confidence, 0.0)
        self.assertEqual(result.trade_intent, TradeIntent.NONE)


class TestOpeningRangeAbsence(unittest.TestCase):
    def test_no_opening_ranges_returns_not_qualified(self):
        strategy = OrbBreakoutStrategy()
        evidence = make_evidence_snapshot()  # opening_ranges defaults to ()
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)
        self.assertEqual(result.score, 0.0)
        self.assertEqual(result.confidence, 0.0)
        self.assertEqual(result.trade_intent, TradeIntent.NONE)


class TestUnformedRange(unittest.TestCase):
    def test_unformed_range_returns_not_qualified(self):
        strategy = OrbBreakoutStrategy()
        evidence = _evidence_with_ranges(_make_opening_range(is_formed=False, is_valid=True))
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)
        self.assertEqual(result.score, 0.0)
        self.assertEqual(result.confidence, 0.0)
        self.assertEqual(result.trade_intent, TradeIntent.NONE)


class TestInvalidRange(unittest.TestCase):
    def test_invalid_range_returns_not_qualified(self):
        strategy = OrbBreakoutStrategy()
        evidence = _evidence_with_ranges(_make_opening_range(is_formed=True, is_valid=False))
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)
        self.assertEqual(result.score, 0.0)
        self.assertEqual(result.confidence, 0.0)
        self.assertEqual(result.trade_intent, TradeIntent.NONE)


class TestFormedValidRange(unittest.TestCase):
    """The central capital-preservation test for Phase 1 (independent
    review finding F1): a genuinely well-formed, valid opening range is
    evidence availability, not a breakout signal, and must still return
    NOT_QUALIFIED since no breakout-qualification rule exists until
    Phase 2."""

    def test_formed_valid_opening_range_still_not_qualified_without_breakout_logic(self):
        strategy = OrbBreakoutStrategy()
        evidence = _evidence_with_ranges(_make_opening_range(is_formed=True, is_valid=True))
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)
        self.assertEqual(result.score, 0.0)
        self.assertEqual(result.confidence, 0.0)
        self.assertEqual(result.trade_intent, TradeIntent.NONE)


class TestMultipleRanges(unittest.TestCase):
    def test_multiple_opening_ranges_returns_not_qualified_regardless_of_state(self):
        strategy = OrbBreakoutStrategy()
        evidence = _evidence_with_ranges(
            _make_opening_range(is_formed=True, is_valid=True),
            _make_opening_range(is_formed=True, is_valid=True),
        )
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)
        self.assertEqual(result.score, 0.0)
        self.assertEqual(result.confidence, 0.0)
        self.assertEqual(result.trade_intent, TradeIntent.NONE)


if __name__ == "__main__":
    unittest.main()
