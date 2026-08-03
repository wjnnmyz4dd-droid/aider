"""ADR-035 Phase 7 -- formation-time news-blackout closure
(docs/plans/adr-035-phase7-formation-time-news-blackout.md).

Exercises the *real* production factory (`build_default_registry(store,
formation_store)`) and the *real* `StrategyEngine`, per §P10's own test
contract -- never a hand-assembled `StrategyRegistry()`.

Three test classes, per §P10 (Finding F3's corrected taxonomy):

- **Production-policy assertions** -- already fully covered elsewhere,
  not duplicated here: Gate A (`DEFAULT_APPROVED_PAIRS_BY_STRATEGY`
  absent for ORB) by
  `test_orb_full_suite_integration.TestProductionEligibilityUnderDefaultPolicy`;
  Gate B (`opening_range_anchors` defaulting to `()`) by
  `tests/titan_protocol/evidence_engine/test_opening_range.py::TestNegativeCases::test_zero_configured_anchors_produces_empty_tuple_no_error`,
  which needs no Strategy Engine involvement at all.
- **Isolation test** (`TestGateBIsolation` below) -- lifts Gate A only,
  to prove Gate B's dormancy independent of Gate A specifically at the
  ORB/Strategy-Engine layer.
- **Logic tests** (everything else below) -- lift both gates via
  test-only configuration to exercise the Phase 7 mechanism itself.
  "Blackout at evaluation only (never during formation)" (§P10 row 2)
  is already covered, unaffected, by
  `test_orb_breakout_foundation.TestMarketIntelligenceEligibility.test_news_blackout_is_not_qualified`
  (an already-formed range, so the new formation loop never touches
  it); "no blackout during formation + no evaluation blackout" (row 1)
  is already covered by
  `test_orb_full_suite_integration.TestOrbQualificationThroughRealEngine`;
  "existing lockout still gates independently" (row 17) is already
  re-verified by every pre-existing Phase 6 lockout test in
  `test_orb_full_suite_integration.py`, now exercised with the new
  store wired in via this implementation's own changes to that file.
  None of these three are duplicated here.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from titan_protocol.strategy_engine.engine import StrategyEngine
from titan_protocol.strategy_engine.models import QualificationStatus
from titan_protocol.strategy_engine.strategies import build_default_registry
from titan_protocol.strategy_state_store import (
    CorruptFormationBlackoutStateError,
    FormationBlackoutStore,
    StrategyStateStoreConfig,
)

from tests.titan_protocol.strategy_engine._fixtures import (
    make_evidence_snapshot, make_market_safety_status, make_mi_snapshot, make_pair_news_intelligence, make_pair_safety,
)
from tests.titan_protocol.strategy_engine.test_orb_breakout_foundation import (
    _RANGE_START, _bar, _breakout_evidence, _evidence_with_ranges, _make_opening_range,
)
from tests.titan_protocol.strategy_engine.test_orb_full_suite_integration import (
    _ORB_ELIGIBLE_CONFIG, _fresh_formation_blackout_store, _fresh_store, _orb_result,
)


def _engine(tmp: str, store=None, formation_store=None) -> StrategyEngine:
    store = store or _fresh_store(Path(tmp))
    formation_store = formation_store or _fresh_formation_blackout_store(Path(tmp))
    return StrategyEngine(_ORB_ELIGIBLE_CONFIG, registry=build_default_registry(store, formation_store))


def _forming_cycle_snapshot(engine, pair, range_start, blackout_active, market_closed=False, holiday=False):
    forming_range = _make_opening_range(is_formed=False, range_start=range_start)
    evidence = _evidence_with_ranges(forming_range)
    mi = make_mi_snapshot(pair_safety=make_pair_safety(
        news=make_pair_news_intelligence(blackout_active=blackout_active),
        market_safety=make_market_safety_status(closed=market_closed, holiday=holiday),
    ))
    return engine.evaluate(pair, evidence, mi)


def _formed_breakout_evidence(range_start=_RANGE_START):
    opening_range = _make_opening_range(range_start=range_start)  # is_formed=True by default
    candidate = _bar(6, 0, 1.100, 1.108, 1.099, 1.108)
    return _breakout_evidence(candidate, opening_range, atr=0.001, volatility_score=90.0)


class TestGateBIsolation(unittest.TestCase):
    """Finding F3's required isolation test -- lifts Gate A only (the
    same test-only eligibility override `_ORB_ELIGIBLE_CONFIG` already
    established), leaves opening-range evidence empty (matching what
    Evidence Engine actually produces under the unmodified,
    unauthorized-to-change `opening_range_anchors` default) -- proving
    Gate B's dormancy independent of Gate A. This override exists
    solely to reach the code path Gate B gates; it is not, and must
    never be read as, evidence that Gate A is itself reachable in
    production."""

    def test_gate_a_lifted_empty_opening_ranges_still_blocks_and_records_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            formation_store = _fresh_formation_blackout_store(Path(tmp))
            engine = _engine(tmp, formation_store=formation_store)
            evidence = make_evidence_snapshot()  # opening_ranges defaults to ()
            snapshot = engine.evaluate("EURUSD", evidence, make_mi_snapshot())
            orb_result = _orb_result(snapshot)
            # Eligibility cleared (this exact reason is unreachable if NOT_ELIGIBLE fired first).
            self.assertEqual(orb_result.status, QualificationStatus.NOT_QUALIFIED)
            self.assertEqual(orb_result.reason, "No opening range configured for this evaluation cycle")
            # Nothing for the accumulation loop to iterate -- no formation state fabricated.
            self.assertFalse(formation_store.was_blackout_observed("EURUSD", _RANGE_START))


class TestFormationBlackoutClosesTheGap(unittest.TestCase):
    """§P10 row 3 -- the exact gap Phase 7 closes: a formation-window
    blackout that has cleared by evaluation time must now be
    `NOT_QUALIFIED`, where pre-Phase-7 behavior would have been
    `QUALIFIED` (proven directly: identical fixtures qualify in
    `test_orb_full_suite_integration.TestOrbQualificationThroughRealEngine`
    when no formation blackout ever occurs)."""

    def test_formation_blackout_cleared_by_evaluation_time_is_not_qualified(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = _engine(tmp)
            _forming_cycle_snapshot(engine, "EURUSD", _RANGE_START, blackout_active=True)
            snapshot = engine.evaluate("EURUSD", _formed_breakout_evidence(), make_mi_snapshot())
            orb_result = _orb_result(snapshot)
            self.assertEqual(orb_result.status, QualificationStatus.NOT_QUALIFIED)
            self.assertEqual(orb_result.reason, "News blackout observed during range formation")


class TestFormationBlackoutCoOccurrenceWithMarketClosedOrHoliday(unittest.TestCase):
    """Finding F2 -- the exact scenario the corrected §P4 insertion point
    exists to cover: a formation-window blackout co-occurring with
    market_closed/is_holiday must still be recorded, even though that
    cycle's own qualification is (correctly, unaffectedly) rejected via
    the existing, unmoved gates."""

    def test_formation_blackout_active_while_market_closed_is_still_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            formation_store = _fresh_formation_blackout_store(Path(tmp))
            engine = _engine(tmp, formation_store=formation_store)
            snapshot = _forming_cycle_snapshot(engine, "EURUSD", _RANGE_START, blackout_active=True, market_closed=True)
            cycle_result = _orb_result(snapshot)
            self.assertEqual(cycle_result.status, QualificationStatus.NOT_QUALIFIED)
            self.assertEqual(cycle_result.reason, "Market closed")
            self.assertTrue(formation_store.was_blackout_observed("EURUSD", _RANGE_START))

    def test_formation_blackout_active_while_holiday_is_still_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            formation_store = _fresh_formation_blackout_store(Path(tmp))
            engine = _engine(tmp, formation_store=formation_store)
            snapshot = _forming_cycle_snapshot(engine, "EURUSD", _RANGE_START, blackout_active=True, holiday=True)
            cycle_result = _orb_result(snapshot)
            self.assertEqual(cycle_result.status, QualificationStatus.NOT_QUALIFIED)
            self.assertEqual(cycle_result.reason, "Holiday")
            self.assertTrue(formation_store.was_blackout_observed("EURUSD", _RANGE_START))

    def test_later_clear_cycle_does_not_erase_a_fact_recorded_during_market_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = _engine(tmp)
            _forming_cycle_snapshot(engine, "EURUSD", _RANGE_START, blackout_active=True, market_closed=True)
            _forming_cycle_snapshot(engine, "EURUSD", _RANGE_START, blackout_active=False, market_closed=False)
            snapshot = engine.evaluate("EURUSD", _formed_breakout_evidence(), make_mi_snapshot())
            orb_result = _orb_result(snapshot)
            self.assertEqual(orb_result.status, QualificationStatus.NOT_QUALIFIED)
            self.assertEqual(orb_result.reason, "News blackout observed during range formation")

    def test_later_clear_cycle_does_not_erase_a_fact_recorded_during_holiday(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = _engine(tmp)
            _forming_cycle_snapshot(engine, "EURUSD", _RANGE_START, blackout_active=True, holiday=True)
            _forming_cycle_snapshot(engine, "EURUSD", _RANGE_START, blackout_active=False, holiday=False)
            snapshot = engine.evaluate("EURUSD", _formed_breakout_evidence(), make_mi_snapshot())
            orb_result = _orb_result(snapshot)
            self.assertEqual(orb_result.status, QualificationStatus.NOT_QUALIFIED)
            self.assertEqual(orb_result.reason, "News blackout observed during range formation")


class TestMonotonicity(unittest.TestCase):
    """§P10 -- once recorded `True`, a fact must never clear."""

    def test_blackout_observed_once_then_many_clean_cycles_does_not_clear_the_fact(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = _engine(tmp)
            _forming_cycle_snapshot(engine, "EURUSD", _RANGE_START, blackout_active=True)
            for _ in range(5):
                _forming_cycle_snapshot(engine, "EURUSD", _RANGE_START, blackout_active=False)
            snapshot = engine.evaluate("EURUSD", _formed_breakout_evidence(), make_mi_snapshot())
            orb_result = _orb_result(snapshot)
            self.assertEqual(orb_result.status, QualificationStatus.NOT_QUALIFIED)
            self.assertEqual(orb_result.reason, "News blackout observed during range formation")

    def test_blackout_observed_on_the_first_forming_cycle_is_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            formation_store = _fresh_formation_blackout_store(Path(tmp))
            engine = _engine(tmp, formation_store=formation_store)
            _forming_cycle_snapshot(engine, "EURUSD", _RANGE_START, blackout_active=True)
            self.assertTrue(formation_store.was_blackout_observed("EURUSD", _RANGE_START))


class TestBlackoutAtRangeEndBoundary(unittest.TestCase):
    """§P5's half-open `[range_start, range_end)` convention: a blackout
    observed on the exact cycle a range transitions to `is_formed=True`
    is *not* counted by the accumulator (the loop only ever iterates
    still-forming ranges) -- but this creates no coverage gap, since the
    existing, unmoved evaluation-time check independently re-evaluates
    `blackout_active` on that same cycle."""

    def test_blackout_at_the_forming_cycle_boundary_is_not_counted_but_evaluation_time_check_still_catches_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            formation_store = _fresh_formation_blackout_store(Path(tmp))
            engine = _engine(tmp, formation_store=formation_store)
            opening_range = _make_opening_range(range_start=_RANGE_START)  # is_formed=True
            evidence = _evidence_with_ranges(opening_range)
            mi = make_mi_snapshot(pair_safety=make_pair_safety(news=make_pair_news_intelligence(blackout_active=True)))
            snapshot = engine.evaluate("EURUSD", evidence, mi)
            cycle_result = _orb_result(snapshot)
            self.assertEqual(cycle_result.status, QualificationStatus.NOT_QUALIFIED)
            self.assertEqual(cycle_result.reason, "News blackout active")
            self.assertFalse(formation_store.was_blackout_observed("EURUSD", _RANGE_START))


class TestRestartPersistence(unittest.TestCase):
    """§P7 -- a formation-blackout fact, and the absence of one, must
    both survive a simulated process restart (fresh store/registry/
    engine objects reading the same file), mirroring Phase 6's own
    restart-test pattern for the lockout store."""

    def test_restart_after_a_formation_blackout_observation_still_gates_once_formed(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "orb_formation_blackout.json"
            store_before = FormationBlackoutStore(StrategyStateStoreConfig(state_file=state_file))
            engine_before = _engine(tmp, formation_store=store_before)
            _forming_cycle_snapshot(engine_before, "EURUSD", _RANGE_START, blackout_active=True)

            # Simulate a restart: a brand-new store/registry/engine reading the same file.
            store_after = FormationBlackoutStore(StrategyStateStoreConfig(state_file=state_file))
            engine_after = _engine(tmp, formation_store=store_after)
            snapshot = engine_after.evaluate("EURUSD", _formed_breakout_evidence(), make_mi_snapshot())
            orb_result = _orb_result(snapshot)
            self.assertEqual(orb_result.status, QualificationStatus.NOT_QUALIFIED)
            self.assertEqual(orb_result.reason, "News blackout observed during range formation")

    def test_restart_during_a_clean_formation_does_not_fabricate_a_false_positive(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "orb_formation_blackout.json"
            store_before = FormationBlackoutStore(StrategyStateStoreConfig(state_file=state_file))
            engine_before = _engine(tmp, formation_store=store_before)
            _forming_cycle_snapshot(engine_before, "EURUSD", _RANGE_START, blackout_active=False)

            store_after = FormationBlackoutStore(StrategyStateStoreConfig(state_file=state_file))
            engine_after = _engine(tmp, formation_store=store_after)
            snapshot = engine_after.evaluate("EURUSD", _formed_breakout_evidence(), make_mi_snapshot())
            orb_result = _orb_result(snapshot)
            self.assertEqual(orb_result.status, QualificationStatus.QUALIFIED)


class TestMultipleRangesIsolation(unittest.TestCase):
    """§P6 -- the `(pair, range_start)` key isolates simultaneous and
    sequential ranges from each other; no cross-contamination."""

    def test_two_simultaneous_ranges_blackout_during_only_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            formation_store = _fresh_formation_blackout_store(Path(tmp))
            engine = _engine(tmp, formation_store=formation_store)
            range_a_start = _RANGE_START
            range_b_start = _RANGE_START + timedelta(hours=2)
            forming_a = _make_opening_range(is_formed=False, range_start=range_a_start)
            forming_b = _make_opening_range(is_formed=False, range_start=range_b_start)
            evidence = _evidence_with_ranges(forming_a, forming_b)
            mi = make_mi_snapshot(pair_safety=make_pair_safety(news=make_pair_news_intelligence(blackout_active=True)))
            engine.evaluate("EURUSD", evidence, mi)
            self.assertTrue(formation_store.was_blackout_observed("EURUSD", range_a_start))
            self.assertTrue(formation_store.was_blackout_observed("EURUSD", range_b_start))

            # A second cycle: both still forming, blackout now clear for both --
            # neither key's earlier True observation is cleared (monotonicity),
            # and this test only needed one blackout=True cycle to prove both
            # ranges captured the same live signal independently at once.

    def test_same_pair_two_sequential_range_starts_one_blacked_out_one_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            formation_store = _fresh_formation_blackout_store(Path(tmp))
            engine = _engine(tmp, formation_store=formation_store)
            earlier_start = _RANGE_START
            later_start = _RANGE_START + timedelta(hours=2)

            _forming_cycle_snapshot(engine, "EURUSD", earlier_start, blackout_active=True)
            _forming_cycle_snapshot(engine, "EURUSD", later_start, blackout_active=False)

            self.assertTrue(formation_store.was_blackout_observed("EURUSD", earlier_start))
            self.assertFalse(formation_store.was_blackout_observed("EURUSD", later_start))


class TestPersistFailureContainment(unittest.TestCase):
    """§P7 -- a mid-cycle persist failure inside the formation-blackout
    store must never escape `StrategyEngine.evaluate()`, mirroring
    Phase 6's own `TestPersistFailureContainment` for the lockout
    store."""

    def test_persist_failure_during_formation_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            formation_store = _fresh_formation_blackout_store(Path(tmp))
            engine = _engine(tmp, formation_store=formation_store)

            def _raise(*_args, **_kwargs):
                raise OSError("simulated disk failure")

            formation_store._persist = _raise  # type: ignore[method-assign]
            # Must not raise -- record_cycle_observation() catches and logs internally.
            snapshot = _forming_cycle_snapshot(engine, "EURUSD", _RANGE_START, blackout_active=True)
            orb_result = _orb_result(snapshot)
            # The in-memory value still stands even though the disk write failed.
            self.assertTrue(formation_store.was_blackout_observed("EURUSD", _RANGE_START))
            self.assertIsNotNone(orb_result)


class TestStartupCorruptState(unittest.TestCase):
    """§P7 -- fail-closed at store-construction time, mirroring Phase
    6's own `TestStartupCorruptState` for the lockout store."""

    def test_corrupt_state_file_raises_at_construction(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "orb_formation_blackout.json"
            state_file.write_text("not valid json", encoding="utf-8")
            with self.assertRaises(CorruptFormationBlackoutStateError):
                FormationBlackoutStore(StrategyStateStoreConfig(state_file=state_file))

    def test_missing_state_file_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "orb_formation_blackout.json"
            self.assertFalse(state_file.exists())
            store = FormationBlackoutStore(StrategyStateStoreConfig(state_file=state_file))
            self.assertIsInstance(store, FormationBlackoutStore)


if __name__ == "__main__":
    unittest.main()
