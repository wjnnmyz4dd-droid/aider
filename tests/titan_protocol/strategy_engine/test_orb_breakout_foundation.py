"""ADR-035 Phase 1 + Phase 2 Step 2B -- ORB Strategy tests.

Phase 1 introduced `StrategyId.OPENING_RANGE_BREAKOUT` and
`OrbBreakoutStrategy` for range-formed/valid gating only -- those tests
are carried forward unchanged below (now passing a real, temp-file-
backed `OrbQualificationStore`, since Step 2B gives the strategy its
first, narrowly-scoped instance state). Step 2B adds the full ADR-035
§4 breakout algorithm and the persistent per-`(pair, range_start)`
lockout; `OrbQualificationStore`'s own persistence/concurrency/
corruption contract is tested directly in
`tests/titan_protocol/strategy_state_store/test_store.py` and is not
duplicated here -- these tests exercise the lockout only through
`OrbBreakoutStrategy.qualify()`'s own consumption path.
`test_architecture.py` (unmodified by this file) already scans every
file under `titan_protocol/strategy_engine/` for forbidden imports/
vocabulary, so that coverage is not duplicated here either."""

from __future__ import annotations

import dataclasses
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from typing import Tuple

from titan_protocol.evidence_engine.models import OpeningRangeBarObservation, OpeningRangeState, SessionName
from titan_protocol.strategy_engine.config import DEFAULT_APPROVED_PAIRS_BY_STRATEGY, StrategyEngineConfig
from titan_protocol.strategy_engine.models import QualificationStatus, StrategyId, TradeIntent
from titan_protocol.strategy_engine.strategies import OrbBreakoutStrategy
from titan_protocol.strategy_engine.strategies.base import Strategy
from titan_protocol.strategy_state_store import OrbQualificationStore, StrategyStateStoreConfig
from tests.titan_protocol.strategy_engine._fixtures import (
    T0, make_config, make_evidence_snapshot, make_mi_snapshot, make_volatility_state,
)

_ORB_APPROVED_CONFIG = StrategyEngineConfig(
    approved_pairs_by_strategy=DEFAULT_APPROVED_PAIRS_BY_STRATEGY + ((StrategyId.OPENING_RANGE_BREAKOUT, ("EURUSD",)),),
)

_RANGE_START = T0 - timedelta(minutes=30)
_RANGE_HIGH = 1.105
_RANGE_LOW = 1.095


class _OrbTestCase(unittest.TestCase):
    """Every test gets its own fresh, temp-file-backed
    `OrbQualificationStore` -- no shared lockout state between tests."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.store = OrbQualificationStore(
            StrategyStateStoreConfig(state_file=Path(self._tmpdir.name) / "orb_state.json")
        )

    def make_strategy(self, store=None) -> OrbBreakoutStrategy:
        return OrbBreakoutStrategy(store=store or self.store)


def _bar(index: int, minutes_after_range_end: int, open_: float, high: float, low: float, close: float) -> OpeningRangeBarObservation:
    return OpeningRangeBarObservation(
        index=index, timestamp=_RANGE_START + timedelta(minutes=30 + minutes_after_range_end),
        open=open_, high=high, low=low, close=close,
    )


def _make_opening_range(
    is_formed: bool = True,
    is_valid: bool = True,
    post_range_bars: Tuple[OpeningRangeBarObservation, ...] = (),
    range_start=_RANGE_START,
    range_high: float = _RANGE_HIGH,
    range_low: float = _RANGE_LOW,
) -> OpeningRangeState:
    return OpeningRangeState(
        session=SessionName.LONDON_NEW_YORK_OVERLAP,
        range_start=range_start,
        range_end=range_start + timedelta(minutes=30),
        range_start_index=0,
        range_end_index=3,
        range_high=range_high,
        range_low=range_low,
        range_midpoint=(range_high + range_low) / 2.0,
        is_formed=is_formed,
        is_valid=is_valid,
        post_range_bars=post_range_bars,
    )


def _evidence_with_ranges(*ranges: OpeningRangeState, volatility=None):
    return dataclasses.replace(
        make_evidence_snapshot(volatility=volatility), opening_ranges=tuple(ranges),
    )


def _breakout_evidence(candidate: OpeningRangeBarObservation, opening_range: OpeningRangeState, is_expansion: bool = True, atr: float = 0.001, volatility_score: float = 80.0):
    return _evidence_with_ranges(
        dataclasses.replace(opening_range, post_range_bars=opening_range.post_range_bars or (candidate,)),
        volatility=make_volatility_state(atr=atr, is_expansion=is_expansion, volatility_score=volatility_score),
    )


class TestStrategyIdMembership(unittest.TestCase):
    def test_opening_range_breakout_exists(self):
        self.assertIn("OPENING_RANGE_BREAKOUT", StrategyId.__members__)
        self.assertEqual(StrategyId.OPENING_RANGE_BREAKOUT.value, "OPENING_RANGE_BREAKOUT")

    def test_five_legacy_strategy_ids_remain(self):
        for name in ("LIQUIDITY_SWEEP_MSS", "BOS_FVG", "TREND_CONTINUATION", "SESSION_BREAKOUT", "RANGE_REVERSAL"):
            self.assertIn(name, StrategyId.__members__)


class TestStrategyContract(_OrbTestCase):
    def test_orb_breakout_strategy_conforms_to_strategy_interface(self):
        strategy = self.make_strategy()
        self.assertIsInstance(strategy, Strategy)
        self.assertEqual(strategy.definition.strategy_id, StrategyId.OPENING_RANGE_BREAKOUT)

    def test_orb_breakout_strategy_instance_state_is_exactly_the_injected_store(self):
        """(ADR-035 §6's anticipated exception to Strategy Engine's
        stateless convention, Phase 2 Step 2B) -- `_store` is the one,
        narrowly-scoped instance field; nothing else."""
        strategy = self.make_strategy()
        self.assertEqual(set(vars(strategy).keys()), {"_store"})


class TestEligibilityGate(_OrbTestCase):
    def test_approved_pairs_for_falls_back_to_empty_with_zero_config(self):
        self.assertEqual(make_config().approved_pairs_for(StrategyId.OPENING_RANGE_BREAKOUT), ())

    def test_unapproved_pair_returns_not_eligible_with_zero_score(self):
        strategy = self.make_strategy()
        result = strategy.qualify("EURUSD", make_evidence_snapshot(), make_mi_snapshot(), make_config())
        self.assertEqual(result.status, QualificationStatus.NOT_ELIGIBLE)
        self.assertEqual(result.score, 0.0)
        self.assertEqual(result.confidence, 0.0)
        self.assertEqual(result.trade_intent, TradeIntent.NONE)


class TestOpeningRangeAbsence(_OrbTestCase):
    def test_no_opening_ranges_returns_not_qualified(self):
        strategy = self.make_strategy()
        evidence = make_evidence_snapshot()  # opening_ranges defaults to ()
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)
        self.assertEqual(result.score, 0.0)
        self.assertEqual(result.confidence, 0.0)
        self.assertEqual(result.trade_intent, TradeIntent.NONE)


class TestUnformedRange(_OrbTestCase):
    def test_unformed_range_returns_not_qualified(self):
        strategy = self.make_strategy()
        evidence = _evidence_with_ranges(_make_opening_range(is_formed=False, is_valid=True))
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)
        self.assertEqual(result.trade_intent, TradeIntent.NONE)


class TestInvalidRange(_OrbTestCase):
    def test_invalid_range_returns_not_qualified(self):
        strategy = self.make_strategy()
        evidence = _evidence_with_ranges(_make_opening_range(is_formed=True, is_valid=False))
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)
        self.assertEqual(result.trade_intent, TradeIntent.NONE)


class TestMultipleRanges(_OrbTestCase):
    def test_multiple_opening_ranges_returns_not_qualified_regardless_of_state(self):
        strategy = self.make_strategy()
        evidence = _evidence_with_ranges(
            _make_opening_range(is_formed=True, is_valid=True),
            _make_opening_range(is_formed=True, is_valid=True),
        )
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)
        self.assertEqual(result.reason, "Multiple opening ranges configured, cannot disambiguate before Phase 4")


class TestNoPostRangeEvidence(_OrbTestCase):
    def test_formed_valid_range_with_no_post_range_bars_is_not_qualified(self):
        strategy = self.make_strategy()
        evidence = _evidence_with_ranges(_make_opening_range())
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)
        self.assertEqual(result.reason, "No post-range evidence available yet")
        self.assertEqual(result.trade_intent, TradeIntent.NONE)


class TestDegenerateGeometry(_OrbTestCase):
    def test_high_equal_to_low_is_not_qualified(self):
        strategy = self.make_strategy()
        opening_range = _make_opening_range()
        candidate = _bar(6, 0, 1.108, 1.108, 1.108, 1.108)
        evidence = _breakout_evidence(candidate, opening_range)
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)
        self.assertEqual(result.reason, "Degenerate candle geometry")


class TestDirectionDetermination(_OrbTestCase):
    def test_close_inside_range_is_not_qualified(self):
        strategy = self.make_strategy()
        opening_range = _make_opening_range()
        candidate = _bar(6, 0, 1.099, 1.101, 1.098, 1.100)  # inside [1.095, 1.105]
        evidence = _breakout_evidence(candidate, opening_range)
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)
        self.assertEqual(result.reason, "No breakout: close within range")

    def test_wick_only_crossing_close_does_not_confirm_is_not_qualified(self):
        strategy = self.make_strategy()
        opening_range = _make_opening_range()
        # high crosses range_high, but close stays inside the range.
        candidate = _bar(6, 0, 1.100, 1.109, 1.098, 1.104)
        evidence = _breakout_evidence(candidate, opening_range)
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)
        self.assertEqual(result.reason, "No breakout: close within range")


class TestMomentum(_OrbTestCase):
    def test_no_volatility_expansion_is_not_qualified(self):
        strategy = self.make_strategy()
        opening_range = _make_opening_range()
        candidate = _bar(6, 0, 1.106, 1.109, 1.1055, 1.108)  # clean bullish breakout
        evidence = _breakout_evidence(candidate, opening_range, is_expansion=False)
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)
        self.assertEqual(result.reason, "No volatility expansion")


class TestAtrDistance(_OrbTestCase):
    _CANDIDATE = _bar(6, 0, 1.1055, 1.1085, 1.1050, 1.108)  # close = range_high + 0.003

    def test_non_positive_atr_is_not_qualified(self):
        strategy = self.make_strategy()
        evidence = _breakout_evidence(self._CANDIDATE, _make_opening_range(), atr=0.0)
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)
        self.assertEqual(result.reason, "Insufficient volatility evidence (non-positive ATR)")

    def test_distance_below_threshold_is_not_qualified(self):
        # distance = 0.003; threshold = 0.15 * atr; atr=0.03 -> threshold 0.0045 > 0.003
        strategy = self.make_strategy()
        evidence = _breakout_evidence(self._CANDIDATE, _make_opening_range(), atr=0.03)
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)
        self.assertEqual(result.reason, "Breakout distance below ATR-relative threshold")

    def test_distance_exactly_at_threshold_passes(self):
        # distance = 0.003; atr chosen so 0.15*atr == 0.003 exactly -> atr = 0.02
        strategy = self.make_strategy()
        evidence = _breakout_evidence(self._CANDIDATE, _make_opening_range(), atr=0.02, volatility_score=90.0)
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertNotEqual(result.reason, "Breakout distance below ATR-relative threshold")

    def test_distance_above_threshold_proceeds(self):
        strategy = self.make_strategy()
        evidence = _breakout_evidence(self._CANDIDATE, _make_opening_range(), atr=0.001, volatility_score=90.0)
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertNotEqual(result.reason, "Breakout distance below ATR-relative threshold")


class TestBodyWickRatio(_OrbTestCase):
    def _evidence_for(self, open_: float, high: float, low: float, close: float):
        candidate = _bar(6, 0, open_, high, low, close)
        return _breakout_evidence(candidate, _make_opening_range(), atr=0.0005, volatility_score=90.0)

    def test_ratio_below_threshold_is_not_qualified(self):
        # body=abs(1.108-1.1077)=0.0003; range=1.109-1.0980=0.0110; ratio needed 0.5*0.0110=0.0055 > 0.0003
        strategy = self.make_strategy()
        evidence = self._evidence_for(1.1077, 1.109, 1.0980, 1.108)
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)
        self.assertEqual(result.reason, "Body/wick ratio below threshold")

    def test_ratio_exactly_at_threshold_passes(self):
        # high-low=0.010; threshold=0.5*0.010=0.005; body=abs(close-open)=0.005 exactly
        strategy = self.make_strategy()
        evidence = self._evidence_for(1.103, 1.108, 1.098, 1.108)
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertNotEqual(result.reason, "Body/wick ratio below threshold")

    def test_ratio_above_threshold_proceeds(self):
        strategy = self.make_strategy()
        evidence = self._evidence_for(1.100, 1.108, 1.099, 1.108)
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertNotEqual(result.reason, "Body/wick ratio below threshold")


class TestConfirmationCount(_OrbTestCase):
    def test_insufficient_confirmation_history_is_not_qualified(self):
        strategy = self.make_strategy()
        opening_range = _make_opening_range(
            post_range_bars=(_bar(6, 0, 1.100, 1.108, 1.099, 1.108),),  # only 1 bar available
        )
        config = StrategyEngineConfig(
            approved_pairs_by_strategy=_ORB_APPROVED_CONFIG.approved_pairs_by_strategy,
            orb_min_confirmation_candles=2,
        )
        evidence = _breakout_evidence(opening_range.post_range_bars[0], opening_range, atr=0.0005, volatility_score=90.0)
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), config)
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)
        self.assertEqual(result.reason, "Insufficient confirmation candles")

    def test_inconsistent_confirmation_direction_is_not_qualified(self):
        strategy = self.make_strategy()
        bars = (
            _bar(6, 0, 1.100, 1.108, 1.099, 1.104),  # inside range -- breaks direction consistency
            _bar(7, 5, 1.100, 1.108, 1.099, 1.108),  # beyond range_high
        )
        opening_range = _make_opening_range(post_range_bars=bars)
        config = StrategyEngineConfig(
            approved_pairs_by_strategy=_ORB_APPROVED_CONFIG.approved_pairs_by_strategy,
            orb_min_confirmation_candles=2,
        )
        evidence = _breakout_evidence(bars[-1], opening_range, atr=0.0005, volatility_score=90.0)
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), config)
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)
        self.assertEqual(result.reason, "Confirmation candles inconsistent with breakout direction")


class TestValidQualification(_OrbTestCase):
    def test_valid_long_breakout_is_qualified(self):
        strategy = self.make_strategy()
        opening_range = _make_opening_range()
        candidate = _bar(6, 0, 1.100, 1.108, 1.099, 1.108)  # body=0.008, range=0.009, ratio ok
        evidence = _breakout_evidence(candidate, opening_range, atr=0.001, volatility_score=90.0)
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.QUALIFIED)
        self.assertEqual(result.trade_intent, TradeIntent.BUY)
        self.assertEqual(result.weaknesses, ())
        self.assertGreater(result.score, 0.0)
        self.assertGreater(result.confidence, 0.0)

    def test_valid_short_breakout_is_qualified(self):
        strategy = self.make_strategy()
        opening_range = _make_opening_range()
        candidate = _bar(6, 0, 1.0940, 1.0945, 1.0900, 1.0910)  # close below range_low=1.095
        evidence = _breakout_evidence(candidate, opening_range, atr=0.001, volatility_score=90.0)
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.QUALIFIED)
        self.assertEqual(result.trade_intent, TradeIntent.SELL)


class TestScoreConfidenceInvariants(_OrbTestCase):
    def test_every_not_qualified_path_has_zero_score_and_confidence_and_none_trade_intent(self):
        strategy = self.make_strategy()
        evidence = make_evidence_snapshot()
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)
        self.assertEqual(result.score, 0.0)
        self.assertEqual(result.confidence, 0.0)
        self.assertEqual(result.trade_intent, TradeIntent.NONE)


class TestLockoutViaStrategy(_OrbTestCase):
    def test_first_qualification_for_a_range_succeeds(self):
        strategy = self.make_strategy()
        opening_range = _make_opening_range()
        candidate = _bar(6, 0, 1.100, 1.108, 1.099, 1.108)
        evidence = _breakout_evidence(candidate, opening_range, atr=0.001, volatility_score=90.0)
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.QUALIFIED)

    def test_second_attempt_at_the_same_range_is_denied_with_max_allowed_one(self):
        strategy = self.make_strategy()
        opening_range = _make_opening_range()
        candidate = _bar(6, 0, 1.100, 1.108, 1.099, 1.108)
        evidence = _breakout_evidence(candidate, opening_range, atr=0.001, volatility_score=90.0)
        strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        second = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertEqual(second.status, QualificationStatus.NOT_QUALIFIED)
        self.assertEqual(second.reason, "Already qualified for this opening range")
        self.assertEqual(second.trade_intent, TradeIntent.NONE)

    def test_not_qualified_result_never_consumes_the_allowance(self):
        strategy = self.make_strategy()
        opening_range = _make_opening_range()
        candidate = _bar(6, 0, 1.099, 1.101, 1.098, 1.100)  # inside range -- never reaches lockout
        evidence = _breakout_evidence(candidate, opening_range)
        strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        # A later genuine breakout for the identical range must still succeed.
        breakout_candidate = _bar(6, 0, 1.100, 1.108, 1.099, 1.108)
        breakout_evidence = _breakout_evidence(breakout_candidate, opening_range, atr=0.001, volatility_score=90.0)
        result = strategy.qualify("EURUSD", breakout_evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.QUALIFIED)

    def test_different_range_start_is_independently_unlocked(self):
        strategy = self.make_strategy()
        first_range = _make_opening_range(range_start=_RANGE_START)
        second_range = _make_opening_range(range_start=_RANGE_START + timedelta(hours=1))
        candidate = _bar(6, 0, 1.100, 1.108, 1.099, 1.108)
        first_evidence = _breakout_evidence(candidate, first_range, atr=0.001, volatility_score=90.0)
        second_evidence = _breakout_evidence(candidate, second_range, atr=0.001, volatility_score=90.0)
        strategy.qualify("EURUSD", first_evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        result = strategy.qualify("EURUSD", second_evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.QUALIFIED)

    def test_max_qualifications_per_range_greater_than_one_permits_repeat_qualification(self):
        config = StrategyEngineConfig(
            approved_pairs_by_strategy=_ORB_APPROVED_CONFIG.approved_pairs_by_strategy,
            orb_max_qualifications_per_range=2,
        )
        strategy = self.make_strategy()
        opening_range = _make_opening_range()
        candidate = _bar(6, 0, 1.100, 1.108, 1.099, 1.108)
        evidence = _breakout_evidence(candidate, opening_range, atr=0.001, volatility_score=90.0)
        first = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), config)
        second = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), config)
        third = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), config)
        self.assertEqual(first.status, QualificationStatus.QUALIFIED)
        self.assertEqual(second.status, QualificationStatus.QUALIFIED)
        self.assertEqual(third.status, QualificationStatus.NOT_QUALIFIED)


class TestConfigValidation(unittest.TestCase):
    def test_invalid_breakout_distance_multiple_raises(self):
        with self.assertRaises(ValueError):
            StrategyEngineConfig(orb_min_breakout_distance_atr_multiple=0.0)

    def test_invalid_body_to_range_ratio_raises(self):
        with self.assertRaises(ValueError):
            StrategyEngineConfig(orb_min_body_to_range_ratio=1.5)

    def test_invalid_confirmation_candles_raises(self):
        with self.assertRaises(ValueError):
            StrategyEngineConfig(orb_min_confirmation_candles=0)

    def test_invalid_max_qualifications_per_range_raises(self):
        with self.assertRaises(ValueError):
            StrategyEngineConfig(orb_max_qualifications_per_range=0)

    def test_defaults_match_adr_035(self):
        config = StrategyEngineConfig()
        self.assertEqual(config.orb_min_breakout_distance_atr_multiple, 0.15)
        self.assertEqual(config.orb_min_body_to_range_ratio, 0.5)
        self.assertEqual(config.orb_min_confirmation_candles, 1)
        self.assertEqual(config.orb_max_qualifications_per_range, 1)


if __name__ == "__main__":
    unittest.main()
