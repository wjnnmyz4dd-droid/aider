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

from titan_protocol.evidence_engine.models import (
    FairValueGap, OpeningRangeBarObservation, OpeningRangeState, SessionName, StructureDirection,
)
from titan_protocol.strategy_engine.config import DEFAULT_APPROVED_PAIRS_BY_STRATEGY, StrategyEngineConfig
from titan_protocol.strategy_engine.models import QualificationStatus, StrategyId, TradeIntent
from titan_protocol.strategy_engine.strategies import OrbBreakoutStrategy
from titan_protocol.strategy_engine.strategies.base import Strategy
from titan_protocol.strategy_state_store import FormationBlackoutStore, OrbQualificationStore, StrategyStateStoreConfig
from tests.titan_protocol.strategy_engine._fixtures import (
    T0, make_config, make_evidence_snapshot, make_liquidity_intelligence, make_market_safety_status,
    make_mi_snapshot, make_pair_news_intelligence, make_pair_safety, make_volatility_state,
)

_ORB_APPROVED_CONFIG = StrategyEngineConfig(
    approved_pairs_by_strategy=DEFAULT_APPROVED_PAIRS_BY_STRATEGY + ((StrategyId.OPENING_RANGE_BREAKOUT, ("EURUSD",)),),
)

_RANGE_START = T0 - timedelta(minutes=30)
_RANGE_HIGH = 1.105
_RANGE_LOW = 1.095


class _OrbTestCase(unittest.TestCase):
    """Every test gets its own fresh, temp-file-backed
    `OrbQualificationStore` and `FormationBlackoutStore` -- no shared
    lockout or formation-blackout state between tests. Phase 1/2's own
    tests below never observe a formation-time blackout in their own
    fixtures, so the fresh, empty `FormationBlackoutStore` has no effect
    on their existing assertions (Phase 7's own non-interference
    requirement, §P10/§P14)."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.store = OrbQualificationStore(
            StrategyStateStoreConfig(state_file=Path(self._tmpdir.name) / "orb_state.json")
        )
        self.formation_blackout_store = FormationBlackoutStore(
            StrategyStateStoreConfig(state_file=Path(self._tmpdir.name) / "orb_formation_blackout_state.json")
        )

    def make_strategy(self, store=None, formation_blackout_store=None) -> OrbBreakoutStrategy:
        return OrbBreakoutStrategy(
            store=store or self.store,
            formation_blackout_store=formation_blackout_store or self.formation_blackout_store,
        )


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


def _breakout_evidence(
    candidate: OpeningRangeBarObservation, opening_range: OpeningRangeState, is_expansion: bool = True, atr: float = 0.001,
    volatility_score: float = 80.0, fair_value_gaps: Tuple[FairValueGap, ...] = (),
):
    evidence = _evidence_with_ranges(
        dataclasses.replace(opening_range, post_range_bars=opening_range.post_range_bars or (candidate,)),
        volatility=make_volatility_state(atr=atr, is_expansion=is_expansion, volatility_score=volatility_score),
    )
    return dataclasses.replace(evidence, fair_value_gaps=fair_value_gaps)


def _fvg(
    direction: StructureDirection, start_index: int, end_index: int, gap_high: float, gap_low: float, filled: bool = False,
) -> FairValueGap:
    return FairValueGap(
        direction=direction, start_index=start_index, end_index=end_index,
        gap_high=gap_high, gap_low=gap_low, filled=filled, fill_index=None,
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

    def test_orb_breakout_strategy_instance_state_is_exactly_the_injected_stores(self):
        """(ADR-035 §6's anticipated exception to Strategy Engine's
        stateless convention, Phase 2 Step 2B, extended by Phase 7)
        -- `_store` and `_formation_blackout_store` are the only two,
        narrowly-scoped instance fields; nothing else."""
        strategy = self.make_strategy()
        self.assertEqual(set(vars(strategy).keys()), {"_store", "_formation_blackout_store"})


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
        self.assertEqual(
            result.reason,
            "Multiple opening ranges are simultaneously relevant "
            "(unreachable under current anchor-overlap validation; retained as defense-in-depth)",
        )


class TestRangeSelection(_OrbTestCase):
    """ADR-035 Phase 4 -- examples A, C, E (docs/plans/adr-035-phase4-mi-eligibility-integration.md
    §6). Example B (single range unaffected) is already exercised by every
    other single-range test in this file; example D (genuine tie) is
    `TestMultipleRanges` above, whose fixture already constructs a tie under
    the new rule."""

    def test_most_recently_formed_range_is_selected_over_an_older_one(self):
        strategy = self.make_strategy()
        older_range = _make_opening_range(range_start=_RANGE_START, is_formed=True, is_valid=True)  # no post_range_bars
        candidate = _bar(6, 0, 1.100, 1.108, 1.099, 1.108)
        newer_range = dataclasses.replace(
            _make_opening_range(range_start=_RANGE_START + timedelta(hours=1), is_formed=True, is_valid=True),
            post_range_bars=(candidate,),
        )
        evidence = _evidence_with_ranges(
            older_range, newer_range,
            volatility=make_volatility_state(atr=0.001, is_expansion=True, volatility_score=90.0),
        )
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        # Only the newer range has post_range_bars; QUALIFIED is only possible
        # if the newer (greatest range_end) range was the one selected.
        self.assertEqual(result.status, QualificationStatus.QUALIFIED)

    def test_no_formed_range_among_multiple_returns_the_precise_reason(self):
        strategy = self.make_strategy()
        evidence = _evidence_with_ranges(
            _make_opening_range(range_start=_RANGE_START, is_formed=False, is_valid=True),
        )
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)
        self.assertEqual(result.reason, "No opening range currently relevant (none yet formed)")

    def test_invalid_newest_range_does_not_fall_back_to_an_older_valid_range(self):
        strategy = self.make_strategy()
        candidate = _bar(6, 0, 1.100, 1.108, 1.099, 1.108)
        older_valid_range = dataclasses.replace(
            _make_opening_range(range_start=_RANGE_START, is_formed=True, is_valid=True),
            post_range_bars=(candidate,),
        )
        newer_invalid_range = _make_opening_range(range_start=_RANGE_START + timedelta(hours=1), is_formed=True, is_valid=False)
        evidence = _evidence_with_ranges(
            older_valid_range, newer_invalid_range,
            volatility=make_volatility_state(atr=0.001, is_expansion=True, volatility_score=90.0),
        )
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        # If ORB had fallen back to the older, valid range (which has a
        # genuine qualifying candidate), this would be QUALIFIED instead.
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)
        self.assertEqual(result.reason, "Opening range invalidated by a data gap or insufficient bar count")


class TestMarketIntelligenceEligibility(_OrbTestCase):
    """ADR-035 Phase 4 -- examples F, F', G-K
    (docs/plans/adr-035-phase4-mi-eligibility-integration.md §6)."""

    def _qualifying_evidence(self):
        opening_range = _make_opening_range()
        candidate = _bar(6, 0, 1.100, 1.108, 1.099, 1.108)
        return _breakout_evidence(candidate, opening_range, atr=0.001, volatility_score=90.0)

    def test_market_closed_is_not_qualified(self):
        strategy = self.make_strategy()
        mi = make_mi_snapshot(pair_safety=make_pair_safety(market_safety=make_market_safety_status(closed=True)))
        result = strategy.qualify("EURUSD", self._qualifying_evidence(), mi, _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)
        self.assertEqual(result.reason, "Market closed")

    def test_holiday_is_not_qualified_independently_of_market_closed(self):
        strategy = self.make_strategy()
        mi = make_mi_snapshot(pair_safety=make_pair_safety(market_safety=make_market_safety_status(closed=False, holiday=True)))
        result = strategy.qualify("EURUSD", self._qualifying_evidence(), mi, _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)
        self.assertEqual(result.reason, "Holiday")

    def test_news_blackout_is_not_qualified(self):
        strategy = self.make_strategy()
        mi = make_mi_snapshot(pair_safety=make_pair_safety(news=make_pair_news_intelligence(blackout_active=True)))
        result = strategy.qualify("EURUSD", self._qualifying_evidence(), mi, _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)
        self.assertEqual(result.reason, "News blackout active")

    def test_spread_exactly_at_maximum_passes(self):
        strategy = self.make_strategy()
        mi = make_mi_snapshot(pair_safety=make_pair_safety(liquidity=make_liquidity_intelligence(current_spread=3.0)))
        result = strategy.qualify("EURUSD", self._qualifying_evidence(), mi, _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.QUALIFIED)

    def test_spread_above_maximum_is_not_qualified(self):
        strategy = self.make_strategy()
        mi = make_mi_snapshot(pair_safety=make_pair_safety(liquidity=make_liquidity_intelligence(current_spread=3.5)))
        result = strategy.qualify("EURUSD", self._qualifying_evidence(), mi, _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)
        self.assertEqual(result.reason, "Spread 3.5 exceeds maximum 3.0")

    def test_liquidity_exactly_at_minimum_passes(self):
        strategy = self.make_strategy()
        mi = make_mi_snapshot(pair_safety=make_pair_safety(liquidity=make_liquidity_intelligence(liquidity_score=60.0)))
        result = strategy.qualify("EURUSD", self._qualifying_evidence(), mi, _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.QUALIFIED)

    def test_liquidity_below_minimum_is_not_qualified(self):
        strategy = self.make_strategy()
        mi = make_mi_snapshot(pair_safety=make_pair_safety(liquidity=make_liquidity_intelligence(liquidity_score=59.9)))
        result = strategy.qualify("EURUSD", self._qualifying_evidence(), mi, _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)
        self.assertEqual(result.reason, "Liquidity score 59.9 below minimum 60.0")

    def test_all_gates_pass_with_fvg_present_is_qualified(self):
        strategy = self.make_strategy()
        opening_range = _make_opening_range()
        candidate = _bar(10, 0, 1.100, 1.108, 1.099, 1.108)
        gap = _fvg(StructureDirection.BULLISH, start_index=2, end_index=8, gap_high=1.107, gap_low=1.1065)
        evidence = _breakout_evidence(candidate, opening_range, atr=0.001, volatility_score=90.0, fair_value_gaps=(gap,))
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.QUALIFIED)
        self.assertTrue(any("FVG" in s for s in result.strengths))

    def test_lockout_unaffected_by_multi_gate_pass_through(self):
        strategy = self.make_strategy()
        evidence = self._qualifying_evidence()
        first = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        second = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertEqual(first.status, QualificationStatus.QUALIFIED)
        self.assertEqual(second.status, QualificationStatus.NOT_QUALIFIED)
        self.assertEqual(second.reason, "Already qualified for this opening range")


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

    def test_close_exactly_at_range_high_boundary_is_not_qualified(self):
        """Locks in the strict `>` (never `>=`) direction-determination
        operator choice (ADR-035 §5.1, Plan §5.1): a close exactly on the
        boundary is not yet a breakout."""
        strategy = self.make_strategy()
        opening_range = _make_opening_range()
        candidate = _bar(6, 0, 1.100, 1.106, 1.099, _RANGE_HIGH)  # close == range_high exactly
        evidence = _breakout_evidence(candidate, opening_range)
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)
        self.assertEqual(result.reason, "No breakout: close within range")

    def test_bearish_wick_only_crossing_close_does_not_confirm_is_not_qualified(self):
        strategy = self.make_strategy()
        opening_range = _make_opening_range()
        # low crosses range_low, but close stays inside the range.
        candidate = _bar(6, 0, 1.100, 1.102, 1.091, 1.096)
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
    _BEARISH_CANDIDATE = _bar(6, 0, 1.0945, 1.0950, 1.0915, 1.092)  # close = range_low - 0.003

    def test_non_positive_atr_is_not_qualified(self):
        # ADR-035 Phase 4 (docs/plans/adr-035-phase4-mi-eligibility-integration.md
        # §3a): the new range-quality gate's own non-positive-ATR guard is
        # unconditional (no config field can bypass it, by design -- an
        # unconditional fail-closed guard must not be config-disableable) and
        # runs strictly before this test's original breakout-distance check, so
        # it is this gate's reason string that now fires for atr=0.0, not the
        # later breakout-distance-specific one. No orb_min_range_atr_ratio
        # override can change this, unlike the two below-threshold tests below.
        strategy = self.make_strategy()
        evidence = _breakout_evidence(self._CANDIDATE, _make_opening_range(), atr=0.0)
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)
        self.assertEqual(result.reason, "Insufficient volatility evidence to assess range quality (non-positive ATR)")

    def test_distance_below_threshold_is_not_qualified(self):
        # distance = 0.003; threshold = 0.15 * atr; atr=0.03 -> threshold 0.0045 > 0.003
        # ADR-035 Phase 4 (§3a): atr=0.03 against this class's shared 0.010-width
        # range also trips the new range-quality gate (ratio 0.333 < default 0.5)
        # strictly before this check runs, so this test isolates the
        # breakout-distance threshold via a locally-permissive
        # orb_min_range_atr_ratio override -- fixture value and reason string
        # both unchanged.
        strategy = self.make_strategy()
        config = dataclasses.replace(_ORB_APPROVED_CONFIG, orb_min_range_atr_ratio=0.01)
        evidence = _breakout_evidence(self._CANDIDATE, _make_opening_range(), atr=0.03)
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), config)
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)
        self.assertEqual(result.reason, "Breakout distance below ATR-relative threshold")

    def test_distance_exactly_at_threshold_passes(self):
        # distance = 0.003; atr chosen so 0.15*atr == 0.003 exactly -> atr = 0.02
        strategy = self.make_strategy()
        evidence = _breakout_evidence(self._CANDIDATE, _make_opening_range(), atr=0.02, volatility_score=90.0)
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.QUALIFIED)

    def test_distance_above_threshold_proceeds(self):
        strategy = self.make_strategy()
        evidence = _breakout_evidence(self._CANDIDATE, _make_opening_range(), atr=0.001, volatility_score=90.0)
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.QUALIFIED)

    def test_bearish_distance_below_threshold_is_not_qualified(self):
        # distance = 0.003; threshold = 0.15 * atr; atr=0.03 -> threshold 0.0045 > 0.003
        # ADR-035 Phase 4 (§3a): same range-quality-gate override as the
        # bullish case above, for the same reason.
        strategy = self.make_strategy()
        config = dataclasses.replace(_ORB_APPROVED_CONFIG, orb_min_range_atr_ratio=0.01)
        evidence = _breakout_evidence(self._BEARISH_CANDIDATE, _make_opening_range(), atr=0.03)
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), config)
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)
        self.assertEqual(result.reason, "Breakout distance below ATR-relative threshold")


class TestRangeQualityGate(_OrbTestCase):
    """ADR-035 Phase 4 -- range-width/ATR gate, examples L/L'/M
    (docs/plans/adr-035-phase4-mi-eligibility-integration.md §3a). Runs
    before post_range_bars is even inspected, so a non-positive ATR is
    caught here rather than at the later breakout-distance check."""

    def test_ratio_exactly_at_threshold_passes(self):
        # range width = 0.010 (_RANGE_HIGH - _RANGE_LOW); atr chosen so
        # 0.010 / atr == 0.5 exactly -> atr = 0.02.
        strategy = self.make_strategy()
        opening_range = _make_opening_range()
        candidate = _bar(6, 0, 1.100, 1.108, 1.099, 1.108)
        evidence = _breakout_evidence(candidate, opening_range, atr=0.02, volatility_score=90.0)
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.QUALIFIED)

    def test_ratio_below_threshold_is_not_qualified(self):
        # range width = 0.010; atr = 0.03 -> ratio = 0.333... < 0.5
        strategy = self.make_strategy()
        opening_range = _make_opening_range()
        candidate = _bar(6, 0, 1.100, 1.108, 1.099, 1.108)
        evidence = _breakout_evidence(candidate, opening_range, atr=0.03, volatility_score=90.0)
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)
        self.assertEqual(result.reason, "Range width/ATR ratio 0.33 below minimum 0.5")

    def test_non_positive_atr_is_not_qualified_before_post_range_bars_checked(self):
        strategy = self.make_strategy()
        opening_range = _make_opening_range()  # no post_range_bars at all
        evidence = _evidence_with_ranges(
            opening_range, volatility=make_volatility_state(atr=0.0, is_expansion=True, volatility_score=90.0),
        )
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)
        self.assertEqual(result.reason, "Insufficient volatility evidence to assess range quality (non-positive ATR)")


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

    def test_bearish_ratio_below_threshold_is_not_qualified(self):
        # body=abs(1.0918-1.0921)=0.0003; range=1.0980-1.0910=0.0070; ratio needed 0.5*0.0070=0.0035 > 0.0003
        strategy = self.make_strategy()
        evidence = self._evidence_for(1.0921, 1.0980, 1.0910, 1.0918)
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), _ORB_APPROVED_CONFIG)
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)
        self.assertEqual(result.reason, "Body/wick ratio below threshold")


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

    def test_invalid_fvg_max_age_bars_raises(self):
        with self.assertRaises(ValueError):
            StrategyEngineConfig(orb_fvg_max_age_bars=0)

    def test_invalid_fvg_min_size_atr_multiple_raises(self):
        with self.assertRaises(ValueError):
            StrategyEngineConfig(orb_fvg_min_size_atr_multiple=0.0)

    def test_invalid_fvg_score_weight_raises(self):
        with self.assertRaises(ValueError):
            StrategyEngineConfig(orb_fvg_score_weight=1.01)
        with self.assertRaises(ValueError):
            StrategyEngineConfig(orb_fvg_score_weight=-0.01)

    def test_invalid_min_range_atr_ratio_raises(self):
        with self.assertRaises(ValueError):
            StrategyEngineConfig(orb_min_range_atr_ratio=0.0)

    def test_invalid_max_spread_pips_raises(self):
        with self.assertRaises(ValueError):
            StrategyEngineConfig(orb_max_spread_pips=0.0)

    def test_invalid_min_liquidity_score_raises(self):
        with self.assertRaises(ValueError):
            StrategyEngineConfig(orb_min_liquidity_score=100.01)
        with self.assertRaises(ValueError):
            StrategyEngineConfig(orb_min_liquidity_score=-0.01)

    def test_defaults_match_adr_035(self):
        config = StrategyEngineConfig()
        self.assertEqual(config.orb_min_breakout_distance_atr_multiple, 0.15)
        self.assertEqual(config.orb_min_body_to_range_ratio, 0.5)
        self.assertEqual(config.orb_min_confirmation_candles, 1)
        self.assertEqual(config.orb_max_qualifications_per_range, 1)
        self.assertEqual(config.orb_fvg_max_age_bars, 10)
        self.assertEqual(config.orb_fvg_min_size_atr_multiple, 0.1)
        self.assertEqual(config.orb_fvg_score_weight, 0.15)
        self.assertEqual(config.orb_min_range_atr_ratio, 0.5)
        self.assertEqual(config.orb_max_spread_pips, 3.0)
        self.assertEqual(config.orb_min_liquidity_score, 60.0)


class TestFvgConfirmation(_OrbTestCase):
    """ADR-035 §5, Phase 3 -- FVG confirmation is score-only and never a
    qualification gate. Examples A-N mirror the accepted Plan exactly
    (docs/plans/adr-035-phase3-fvg-confirmation.md §5), including its
    shared fixture values."""

    _CONFIG = StrategyEngineConfig(
        approved_pairs_by_strategy=_ORB_APPROVED_CONFIG.approved_pairs_by_strategy,
        orb_fvg_max_age_bars=3, orb_fvg_min_size_atr_multiple=0.1, orb_fvg_score_weight=0.15,
    )
    _CANDIDATE = _bar(10, 0, 1.100, 1.108, 1.099, 1.108)  # bullish breakout, close=1.108, index=10
    _BEARISH_CANDIDATE = _bar(10, 0, 1.0940, 1.0945, 1.0900, 1.0910)  # bearish breakout, close=1.0910, index=10

    def _fresh_strategy(self) -> OrbBreakoutStrategy:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        store = OrbQualificationStore(StrategyStateStoreConfig(state_file=Path(tmpdir.name) / "orb_state.json"))
        return self.make_strategy(store=store)

    def _qualify(self, opening_range, fair_value_gaps, candidate=None, config=None):
        strategy = self._fresh_strategy()
        evidence = _breakout_evidence(
            candidate or self._CANDIDATE, opening_range, atr=0.001, volatility_score=80.0, fair_value_gaps=fair_value_gaps,
        )
        return strategy.qualify("EURUSD", evidence, make_mi_snapshot(), config or self._CONFIG)

    def test_no_fvg_contributes_no_score_bonus(self):
        opening_range = _make_opening_range()
        with_default_weight = self._qualify(opening_range, ())
        zero_weight_config = dataclasses.replace(self._CONFIG, orb_fvg_score_weight=0.0)
        with_zero_weight = self._qualify(opening_range, (), config=zero_weight_config)
        self.assertEqual(with_default_weight.status, QualificationStatus.QUALIFIED)
        self.assertEqual(with_default_weight.score, with_zero_weight.score)
        self.assertFalse(any("FVG" in s for s in with_default_weight.strengths))

    def test_wrong_direction_fvg_contributes_no_bonus(self):
        gap = _fvg(StructureDirection.BEARISH, start_index=2, end_index=8, gap_high=1.107, gap_low=1.1065)
        no_fvg = self._qualify(_make_opening_range(), ())
        wrong_direction = self._qualify(_make_opening_range(), (gap,))
        self.assertEqual(wrong_direction.status, QualificationStatus.QUALIFIED)
        self.assertEqual(wrong_direction.score, no_fvg.score)

    def test_exact_age_boundary_passes(self):
        # end_index=7 -> age_bars = candidate.index(10) - 7 = 3 == orb_fvg_max_age_bars -- inclusive pass
        gap = _fvg(StructureDirection.BULLISH, start_index=2, end_index=7, gap_high=1.107, gap_low=1.1065)
        result = self._qualify(_make_opening_range(), (gap,))
        self.assertEqual(result.status, QualificationStatus.QUALIFIED)
        self.assertTrue(any("FVG" in s for s in result.strengths))

    def test_one_bar_too_old_excluded(self):
        # end_index=6 -> age_bars = 10 - 6 = 4 > 3 -- excluded
        gap = _fvg(StructureDirection.BULLISH, start_index=2, end_index=6, gap_high=1.107, gap_low=1.1065)
        no_fvg = self._qualify(_make_opening_range(), ())
        too_old = self._qualify(_make_opening_range(), (gap,))
        self.assertEqual(too_old.status, QualificationStatus.QUALIFIED)
        self.assertEqual(too_old.score, no_fvg.score)

    def test_future_index_excluded_fail_closed(self):
        # end_index=11 -> age_bars = 10 - 11 = -1 -- excluded, never "maximally fresh"
        gap = _fvg(StructureDirection.BULLISH, start_index=2, end_index=11, gap_high=1.107, gap_low=1.1065)
        no_fvg = self._qualify(_make_opening_range(), ())
        future_index = self._qualify(_make_opening_range(), (gap,))
        self.assertEqual(future_index.status, QualificationStatus.QUALIFIED)
        self.assertEqual(future_index.score, no_fvg.score)

    def test_multiple_fvgs_selects_first_qualifying_in_tuple_order(self):
        gap1_wrong_direction = _fvg(StructureDirection.BEARISH, start_index=2, end_index=8, gap_high=1.107, gap_low=1.1065)
        gap2_qualifies = _fvg(StructureDirection.BULLISH, start_index=2, end_index=8, gap_high=1.107, gap_low=1.1065)
        gap3_also_qualifies = _fvg(StructureDirection.BULLISH, start_index=2, end_index=9, gap_high=1.1075, gap_low=1.107)
        result = self._qualify(_make_opening_range(), (gap1_wrong_direction, gap2_qualifies, gap3_also_qualifies))
        self.assertEqual(result.status, QualificationStatus.QUALIFIED)
        self.assertTrue(any("[2-8]" in s for s in result.strengths))
        self.assertFalse(any("[2-9]" in s for s in result.strengths))

    def test_valid_bullish_fvg_adds_bonus_and_strength(self):
        gap = _fvg(StructureDirection.BULLISH, start_index=2, end_index=8, gap_high=1.107, gap_low=1.1065)
        without_fvg = self._qualify(_make_opening_range(), ())
        with_fvg = self._qualify(_make_opening_range(), (gap,))
        self.assertEqual(with_fvg.status, QualificationStatus.QUALIFIED)
        self.assertGreater(with_fvg.score, without_fvg.score)
        self.assertTrue(any("unfilled bullish FVG confirmation [2-8]" in s for s in with_fvg.strengths))

    def test_valid_bearish_fvg_adds_bonus(self):
        opening_range = _make_opening_range()
        gap = _fvg(StructureDirection.BEARISH, start_index=2, end_index=8, gap_high=1.0935, gap_low=1.0925)
        without_fvg = self._qualify(opening_range, (), candidate=self._BEARISH_CANDIDATE)
        with_fvg = self._qualify(opening_range, (gap,), candidate=self._BEARISH_CANDIDATE)
        self.assertEqual(with_fvg.status, QualificationStatus.QUALIFIED)
        self.assertEqual(with_fvg.trade_intent, TradeIntent.SELL)
        self.assertGreater(with_fvg.score, without_fvg.score)

    def test_weight_zero_is_accepted_and_inert(self):
        config = dataclasses.replace(self._CONFIG, orb_fvg_score_weight=0.0)
        gap = _fvg(StructureDirection.BULLISH, start_index=2, end_index=8, gap_high=1.107, gap_low=1.1065)
        no_fvg = self._qualify(_make_opening_range(), (), config=config)
        with_fvg = self._qualify(_make_opening_range(), (gap,), config=config)
        self.assertEqual(with_fvg.score, no_fvg.score)

    def test_weight_one_is_accepted_and_clamped(self):
        config = dataclasses.replace(self._CONFIG, orb_fvg_score_weight=1.0)
        gap = _fvg(StructureDirection.BULLISH, start_index=2, end_index=8, gap_high=1.107, gap_low=1.1065)
        result = self._qualify(_make_opening_range(), (gap,), config=config)
        self.assertEqual(result.status, QualificationStatus.QUALIFIED)
        self.assertLessEqual(result.score, 100.0)

    def test_weight_out_of_range_raises(self):
        with self.assertRaises(ValueError):
            dataclasses.replace(self._CONFIG, orb_fvg_score_weight=1.01)
        with self.assertRaises(ValueError):
            dataclasses.replace(self._CONFIG, orb_fvg_score_weight=-0.01)

    def test_lockout_interaction_unaffected_by_fvg(self):
        strategy = self._fresh_strategy()
        opening_range = _make_opening_range()
        gap = _fvg(StructureDirection.BULLISH, start_index=2, end_index=8, gap_high=1.107, gap_low=1.1065)
        evidence = _breakout_evidence(self._CANDIDATE, opening_range, atr=0.001, volatility_score=80.0, fair_value_gaps=(gap,))
        first = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), self._CONFIG)
        second = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), self._CONFIG)
        self.assertEqual(first.status, QualificationStatus.QUALIFIED)
        self.assertEqual(second.status, QualificationStatus.NOT_QUALIFIED)
        self.assertEqual(second.reason, "Already qualified for this opening range")

    def test_filled_fvg_excluded_expiration(self):
        gap = _fvg(StructureDirection.BULLISH, start_index=2, end_index=8, gap_high=1.107, gap_low=1.1065, filled=True)
        no_fvg = self._qualify(_make_opening_range(), ())
        filled = self._qualify(_make_opening_range(), (gap,))
        self.assertEqual(filled.status, QualificationStatus.QUALIFIED)
        self.assertEqual(filled.score, no_fvg.score)

    def test_undersized_fvg_excluded(self):
        gap = _fvg(StructureDirection.BULLISH, start_index=2, end_index=8, gap_high=1.10505, gap_low=1.10500)
        no_fvg = self._qualify(_make_opening_range(), ())
        undersized = self._qualify(_make_opening_range(), (gap,))
        self.assertEqual(undersized.status, QualificationStatus.QUALIFIED)
        self.assertEqual(undersized.score, no_fvg.score)

    def test_non_overlapping_fvg_excluded(self):
        gap = _fvg(StructureDirection.BULLISH, start_index=2, end_index=8, gap_high=1.1030, gap_low=1.1020)
        no_fvg = self._qualify(_make_opening_range(), ())
        no_overlap = self._qualify(_make_opening_range(), (gap,))
        self.assertEqual(no_overlap.status, QualificationStatus.QUALIFIED)
        self.assertEqual(no_overlap.score, no_fvg.score)

    def test_fvg_formed_before_range_start_excluded(self):
        opening_range = dataclasses.replace(_make_opening_range(), range_start_index=5)
        gap = _fvg(StructureDirection.BULLISH, start_index=3, end_index=8, gap_high=1.107, gap_low=1.1065)
        no_fvg = self._qualify(opening_range, ())
        formed_before_range = self._qualify(opening_range, (gap,))
        self.assertEqual(formed_before_range.status, QualificationStatus.QUALIFIED)
        self.assertEqual(formed_before_range.score, no_fvg.score)


if __name__ == "__main__":
    unittest.main()
