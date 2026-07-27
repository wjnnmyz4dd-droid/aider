"""ADR-035 Phase 6 -- Full-suite validation (docs/plans/adr-035-phase6-full-suite-validation.md).

Exercises the *real* production factory (`build_default_registry()`/
`build_default_registry(store)`) and the *real* `StrategyEngine` --
never a hand-assembled `StrategyRegistry()` standing in for either.

Test-only ORB eligibility (Plan §P7a): several tests below need ORB to
be pair-eligible to reach its own qualification logic, since the
production default (`DEFAULT_APPROVED_PAIRS_BY_STRATEGY`, untouched by
this phase) leaves it `NOT_ELIGIBLE` for every pair. Those tests build
`_ORB_ELIGIBLE_CONFIG` via `make_config(approved_pairs_by_strategy=
DEFAULT_APPROVED_PAIRS_BY_STRATEGY + (...))` -- extending the real,
imported default rather than retyping it, and touching no production
file. Tests proving the production default itself (registry cardinality,
the NOT_ELIGIBLE-under-default proof, and the legacy-strategy regression
proof) deliberately do NOT use this override."""

from __future__ import annotations

import dataclasses
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from titan_protocol.evidence_engine.models import TrendClassification
from titan_protocol.strategy_engine.config import DEFAULT_APPROVED_PAIRS_BY_STRATEGY
from titan_protocol.strategy_engine.engine import StrategyEngine
from titan_protocol.strategy_engine.models import QualificationStatus, StrategyId
from titan_protocol.strategy_engine.strategies import build_default_registry
from titan_protocol.strategy_state_store import OrbQualificationStore, StrategyStateStoreConfig
from titan_protocol.strategy_state_store.models import CorruptStateError

from tests.titan_protocol.strategy_engine._fixtures import (
    make_config,
    make_evidence_snapshot,
    make_market_safety_status,
    make_mi_snapshot,
    make_pair_safety,
    make_structure_result,
)
from tests.titan_protocol.strategy_engine.test_orb_breakout_foundation import (
    _bar,
    _breakout_evidence,
    _evidence_with_ranges,
    _make_opening_range,
)

_ORB_ELIGIBLE_CONFIG = make_config(
    approved_pairs_by_strategy=DEFAULT_APPROVED_PAIRS_BY_STRATEGY
    + ((StrategyId.OPENING_RANGE_BREAKOUT, ("EURUSD",)),),
)


def _fresh_store(tmp_path: Path, filename: str = "orb_qualifications.json") -> OrbQualificationStore:
    return OrbQualificationStore(StrategyStateStoreConfig(state_file=tmp_path / filename))


def _orb_result(snapshot):
    return next(q for q in snapshot.all_qualifications if q.strategy_id == StrategyId.OPENING_RANGE_BREAKOUT)


class TestRegistryCardinality(unittest.TestCase):
    """P8 item 1."""

    def test_no_store_returns_five_legacy_strategies(self):
        registry = build_default_registry()
        ids = [s.definition.strategy_id for s in registry.all()]
        self.assertEqual(len(ids), 5)
        self.assertNotIn(StrategyId.OPENING_RANGE_BREAKOUT, ids)

    def test_with_store_returns_six_including_orb_exactly_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _fresh_store(Path(tmp))
            registry = build_default_registry(store)
            ids = [s.definition.strategy_id for s in registry.all()]
            self.assertEqual(len(ids), 6)
            self.assertEqual(ids.count(StrategyId.OPENING_RANGE_BREAKOUT), 1)

    def test_orb_strategy_holds_the_exact_supplied_store_instance(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _fresh_store(Path(tmp))
            registry = build_default_registry(store)
            orb_strategy = registry.get(StrategyId.OPENING_RANGE_BREAKOUT)
            self.assertIs(orb_strategy._store, store)


class TestLegacyStrategyRegressionThroughRealEngine(unittest.TestCase):
    """P8 item 2 -- deliberately uses the unmodified production default
    config (no test-only eligibility override): the point is proving
    the *other five* strategies are unaffected by ORB's mere presence,
    regardless of ORB's own eligibility outcome."""

    def test_legacy_qualification_results_identical_with_and_without_orb_registered(self):
        evidence = make_evidence_snapshot(
            structure=make_structure_result(trend=TrendClassification.TRENDING_UP),
            component_overrides={"trend": {"value": 90.0, "confidence": 0.9}},
        )
        mi = make_mi_snapshot()

        five_strategy_engine = StrategyEngine(make_config())
        five_snapshot = five_strategy_engine.evaluate("EURUSD", evidence, mi)

        with tempfile.TemporaryDirectory() as tmp:
            store = _fresh_store(Path(tmp))
            six_strategy_engine = StrategyEngine(make_config(), registry=build_default_registry(store))
            six_snapshot = six_strategy_engine.evaluate("EURUSD", evidence, mi)

        five_by_id = {q.strategy_id: q for q in five_snapshot.all_qualifications}
        six_by_id = {q.strategy_id: q for q in six_snapshot.all_qualifications}
        for strategy_id, five_result in five_by_id.items():
            six_result = six_by_id[strategy_id]
            self.assertEqual(five_result.status, six_result.status)
            self.assertEqual(five_result.score, six_result.score)
            self.assertEqual(five_result.reason, six_result.reason)

        self.assertEqual(six_snapshot.winning_strategy.strategy_id, five_snapshot.winning_strategy.strategy_id)
        self.assertEqual(len(five_snapshot.all_qualifications), 5)
        self.assertEqual(len(six_snapshot.all_qualifications), 6)


class TestProductionEligibilityUnderDefaultPolicy(unittest.TestCase):
    """P8 item 6 -- deliberately uses the unmodified production default
    config; using the test-only override here would defeat this test's
    own purpose."""

    def test_orb_is_not_eligible_for_any_pair_under_the_shipped_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _fresh_store(Path(tmp))
            engine = StrategyEngine(make_config(), registry=build_default_registry(store))
            for pair in ("EURUSD", "GBPUSD", "AUDNZD"):
                snapshot = engine.evaluate(pair, make_evidence_snapshot(symbol=pair), make_mi_snapshot(pair=pair))
                orb_result = _orb_result(snapshot)
                self.assertEqual(orb_result.status, QualificationStatus.NOT_ELIGIBLE)


class TestOrbQualificationThroughRealEngine(unittest.TestCase):
    """P8 item 7 (real six-strategy evaluation / explicitly eligible ORB
    through the cascade) -- uses the test-only eligibility override."""

    def test_orb_qualifies_through_the_real_engine_with_test_only_eligibility(self):
        opening_range = _make_opening_range()
        candidate = _bar(6, 0, 1.100, 1.108, 1.099, 1.108)
        evidence = _breakout_evidence(candidate, opening_range, atr=0.001, volatility_score=90.0)

        with tempfile.TemporaryDirectory() as tmp:
            store = _fresh_store(Path(tmp))
            engine = StrategyEngine(_ORB_ELIGIBLE_CONFIG, registry=build_default_registry(store))
            snapshot = engine.evaluate("EURUSD", evidence, make_mi_snapshot())
            orb_result = _orb_result(snapshot)
            self.assertEqual(orb_result.status, QualificationStatus.QUALIFIED)


class TestLockoutThroughRealEngine(unittest.TestCase):
    """P8 item 8 -- lockout/persistence exercised through the real
    engine construction path (build_default_registry(store)), not by
    calling OrbBreakoutStrategy.qualify() directly. Uses the test-only
    eligibility override."""

    def test_repeated_evaluation_of_the_same_range_locks_out_after_first_qualification(self):
        opening_range = _make_opening_range()
        candidate = _bar(6, 0, 1.100, 1.108, 1.099, 1.108)
        evidence = _breakout_evidence(candidate, opening_range, atr=0.001, volatility_score=90.0)

        with tempfile.TemporaryDirectory() as tmp:
            store = _fresh_store(Path(tmp))
            engine = StrategyEngine(_ORB_ELIGIBLE_CONFIG, registry=build_default_registry(store))
            first = _orb_result(engine.evaluate("EURUSD", evidence, make_mi_snapshot()))
            second = _orb_result(engine.evaluate("EURUSD", evidence, make_mi_snapshot()))
            self.assertEqual(first.status, QualificationStatus.QUALIFIED)
            self.assertEqual(second.status, QualificationStatus.NOT_QUALIFIED)
            self.assertEqual(second.reason, "Already qualified for this opening range")

    def test_lockout_survives_a_process_restart_through_the_real_engine(self):
        opening_range = _make_opening_range()
        candidate = _bar(6, 0, 1.100, 1.108, 1.099, 1.108)
        evidence = _breakout_evidence(candidate, opening_range, atr=0.001, volatility_score=90.0)

        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "orb_qualifications.json"
            store_before_restart = OrbQualificationStore(StrategyStateStoreConfig(state_file=state_file))
            engine_before_restart = StrategyEngine(
                _ORB_ELIGIBLE_CONFIG, registry=build_default_registry(store_before_restart),
            )
            first = _orb_result(engine_before_restart.evaluate("EURUSD", evidence, make_mi_snapshot()))
            self.assertEqual(first.status, QualificationStatus.QUALIFIED)

            # Simulate a restart: a brand-new store/registry/engine reading the same file.
            store_after_restart = OrbQualificationStore(StrategyStateStoreConfig(state_file=state_file))
            engine_after_restart = StrategyEngine(
                _ORB_ELIGIBLE_CONFIG, registry=build_default_registry(store_after_restart),
            )
            second = _orb_result(engine_after_restart.evaluate("EURUSD", evidence, make_mi_snapshot()))
            self.assertEqual(second.status, QualificationStatus.NOT_QUALIFIED)
            self.assertEqual(second.reason, "Already qualified for this opening range")

    def test_distinct_pair_is_independent_of_an_already_locked_out_pair(self):
        opening_range = _make_opening_range()
        candidate = _bar(6, 0, 1.100, 1.108, 1.099, 1.108)
        evidence_eurusd = _breakout_evidence(candidate, opening_range, atr=0.001, volatility_score=90.0)
        evidence_gbpusd = _breakout_evidence(candidate, opening_range, atr=0.001, volatility_score=90.0)
        evidence_gbpusd = dataclasses.replace(
            evidence_gbpusd, report=dataclasses.replace(evidence_gbpusd.report, symbol="GBPUSD"),
        )

        eligible_config = make_config(
            approved_pairs_by_strategy=DEFAULT_APPROVED_PAIRS_BY_STRATEGY
            + ((StrategyId.OPENING_RANGE_BREAKOUT, ("EURUSD", "GBPUSD")),),
        )
        with tempfile.TemporaryDirectory() as tmp:
            store = _fresh_store(Path(tmp))
            engine = StrategyEngine(eligible_config, registry=build_default_registry(store))
            eurusd_first = _orb_result(engine.evaluate("EURUSD", evidence_eurusd, make_mi_snapshot(pair="EURUSD")))
            eurusd_second = _orb_result(engine.evaluate("EURUSD", evidence_eurusd, make_mi_snapshot(pair="EURUSD")))
            gbpusd_first = _orb_result(engine.evaluate("GBPUSD", evidence_gbpusd, make_mi_snapshot(pair="GBPUSD")))

            self.assertEqual(eurusd_first.status, QualificationStatus.QUALIFIED)
            self.assertEqual(eurusd_second.status, QualificationStatus.NOT_QUALIFIED)
            self.assertEqual(gbpusd_first.status, QualificationStatus.QUALIFIED)


class TestStartupCorruptState(unittest.TestCase):
    """P8 item 4 -- fail-closed at store-construction time, mirroring
    ComplianceStateStore's existing, unguarded treatment in start.py."""

    def test_corrupt_state_file_raises_at_construction(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "orb_qualifications.json"
            state_file.write_text("not valid json", encoding="utf-8")
            with self.assertRaises(CorruptStateError):
                OrbQualificationStore(StrategyStateStoreConfig(state_file=state_file))

    def test_missing_state_file_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "orb_qualifications.json"
            self.assertFalse(state_file.exists())
            store = OrbQualificationStore(StrategyStateStoreConfig(state_file=state_file))
            self.assertIsInstance(store, OrbQualificationStore)


class TestPersistFailureContainment(unittest.TestCase):
    """P8 item 5 -- a mid-cycle persist failure must never escape
    StrategyEngine.evaluate(), proving store.py's own documented
    containment contract holds when reached through the real engine,
    not merely when store.try_consume() is called directly."""

    def test_persist_failure_during_evaluate_does_not_raise(self):
        opening_range = _make_opening_range()
        candidate = _bar(6, 0, 1.100, 1.108, 1.099, 1.108)
        evidence = _breakout_evidence(candidate, opening_range, atr=0.001, volatility_score=90.0)

        with tempfile.TemporaryDirectory() as tmp:
            store = _fresh_store(Path(tmp))

            def _raise(*_args, **_kwargs):
                raise OSError("simulated disk failure")

            store._persist = _raise  # type: ignore[method-assign]
            engine = StrategyEngine(_ORB_ELIGIBLE_CONFIG, registry=build_default_registry(store))
            # Must not raise -- try_consume() catches and logs internally.
            snapshot = engine.evaluate("EURUSD", evidence, make_mi_snapshot())
            orb_result = _orb_result(snapshot)
            self.assertEqual(orb_result.status, QualificationStatus.QUALIFIED)


class TestSection15EdgeCasesThroughRealEngine(unittest.TestCase):
    """ADR-035 §15 edge cases, exercised end-to-end through the real
    six-strategy StrategyEngine (Plan §P7). Uses the test-only ORB
    eligibility override -- these are the six rows §P7a names."""

    def test_gap_invalidated_range_orb_not_qualified_others_unaffected(self):
        # is_valid=False models a temporal gap inside the range window
        # (§15 "gap open"/"missing candles" -- both resolve to the same
        # is_valid=False path, per ADR-035 §3's own gap check). qualify()
        # checks is_valid before ever looking at post-range bars, so no
        # candidate/breakout evidence is needed to reach this path.
        opening_range = _make_opening_range(is_valid=False)
        evidence = _evidence_with_ranges(opening_range)

        with tempfile.TemporaryDirectory() as tmp:
            store = _fresh_store(Path(tmp))
            engine = StrategyEngine(_ORB_ELIGIBLE_CONFIG, registry=build_default_registry(store))
            snapshot = engine.evaluate("EURUSD", evidence, make_mi_snapshot())
            orb_result = _orb_result(snapshot)
            self.assertEqual(orb_result.status, QualificationStatus.NOT_QUALIFIED)
            self.assertEqual(orb_result.reason, "Opening range invalidated by a data gap or insufficient bar count")
            # The other five strategies still produced a real (non-crashed) result.
            self.assertEqual(len(snapshot.all_qualifications), 6)

    def test_session_reconnect_no_bars_missed_forms_normally(self):
        opening_range = _make_opening_range()  # is_formed=True, is_valid=True by default
        candidate = _bar(6, 0, 1.100, 1.108, 1.099, 1.108)
        evidence = _breakout_evidence(candidate, opening_range, atr=0.001, volatility_score=90.0)

        with tempfile.TemporaryDirectory() as tmp:
            store = _fresh_store(Path(tmp))
            engine = StrategyEngine(_ORB_ELIGIBLE_CONFIG, registry=build_default_registry(store))
            snapshot = engine.evaluate("EURUSD", evidence, make_mi_snapshot())
            orb_result = _orb_result(snapshot)
            self.assertEqual(orb_result.status, QualificationStatus.QUALIFIED)

    def test_session_reconnect_bars_missed_range_invalid(self):
        # A reconnect that missed bars inside the range window -- same
        # is_valid=False path as the gap case above, from the
        # reconnect's own perspective (§15 "session reconnect").
        opening_range = _make_opening_range(is_valid=False)
        candidate = _bar(6, 0, 1.100, 1.108, 1.099, 1.108)
        evidence = _breakout_evidence(candidate, opening_range, atr=0.001, volatility_score=90.0)

        with tempfile.TemporaryDirectory() as tmp:
            store = _fresh_store(Path(tmp))
            engine = StrategyEngine(_ORB_ELIGIBLE_CONFIG, registry=build_default_registry(store))
            snapshot = engine.evaluate("EURUSD", evidence, make_mi_snapshot())
            orb_result = _orb_result(snapshot)
            self.assertEqual(orb_result.status, QualificationStatus.NOT_QUALIFIED)

    def test_holiday_orb_not_qualified_via_market_intelligence_gate(self):
        opening_range = _make_opening_range()
        candidate = _bar(6, 0, 1.100, 1.108, 1.099, 1.108)
        evidence = _breakout_evidence(candidate, opening_range, atr=0.001, volatility_score=90.0)
        mi = make_mi_snapshot(pair_safety=make_pair_safety(market_safety=make_market_safety_status(holiday=True)))

        with tempfile.TemporaryDirectory() as tmp:
            store = _fresh_store(Path(tmp))
            engine = StrategyEngine(_ORB_ELIGIBLE_CONFIG, registry=build_default_registry(store))
            snapshot = engine.evaluate("EURUSD", evidence, mi)
            orb_result = _orb_result(snapshot)
            self.assertEqual(orb_result.status, QualificationStatus.NOT_QUALIFIED)
            self.assertEqual(orb_result.reason, "Holiday")
            self.assertEqual(len(snapshot.all_qualifications), 6)

    def test_multiple_ranges_two_anchors_through_real_engine(self):
        from tests.titan_protocol.strategy_engine.test_orb_breakout_foundation import _RANGE_START

        earlier_range = _make_opening_range(range_start=_RANGE_START - timedelta(hours=2))
        later_range = _make_opening_range()  # the "currently relevant" one (latest range_end)
        candidate = _bar(6, 0, 1.100, 1.108, 1.099, 1.108)
        breakout_evidence = _breakout_evidence(candidate, later_range, atr=0.001, volatility_score=90.0)
        later_range_with_bars = breakout_evidence.opening_ranges[0]
        evidence = dataclasses.replace(breakout_evidence, opening_ranges=(earlier_range, later_range_with_bars))

        with tempfile.TemporaryDirectory() as tmp:
            store = _fresh_store(Path(tmp))
            engine = StrategyEngine(_ORB_ELIGIBLE_CONFIG, registry=build_default_registry(store))
            snapshot = engine.evaluate("EURUSD", evidence, make_mi_snapshot())
            orb_result = _orb_result(snapshot)
            self.assertEqual(orb_result.status, QualificationStatus.QUALIFIED)

    def test_partial_trading_day_no_post_range_bars_never_qualifies(self):
        # Early close -- no further bars ever arrive after the range
        # forms, so ORB fails closed via the ordinary "no post-range
        # evidence" path (ADR-035 §15: "the range simply never forms
        # ... not a special case to code for").
        opening_range = _make_opening_range(post_range_bars=())
        evidence = _evidence_with_ranges(opening_range)

        with tempfile.TemporaryDirectory() as tmp:
            store = _fresh_store(Path(tmp))
            engine = StrategyEngine(_ORB_ELIGIBLE_CONFIG, registry=build_default_registry(store))
            snapshot = engine.evaluate("EURUSD", evidence, make_mi_snapshot())
            orb_result = _orb_result(snapshot)
            self.assertEqual(orb_result.status, QualificationStatus.NOT_QUALIFIED)
            self.assertEqual(orb_result.reason, "No post-range evidence available yet")


if __name__ == "__main__":
    unittest.main()
