"""Runtime's cross-pair opportunity-selection barrier (ADR-037 + Amendment
1, ADR-031 Amendment 1): `run_cycle()`'s own new aggregate-loop sequencing,
distinct from `run_cycle_for_pair()`'s byte-for-byte-preserved per-pair
path (see `test_runtime.py`/`test_regression.py` etc. for that guarantee).

Uses a dedicated, per-pair-configurable strategy-engine stub (the shared
`RecordingStub` in `_fixtures.py` returns one fixed snapshot for every
call, which cannot express "pair A qualifies ORB at 80, pair B qualifies
ORB at 60"); a real `OpportunitySelectionEngine` + `OpportunityWinnerStore`
backed by a temp file, so winner persistence is genuinely exercised, not
mocked; and the shared Risk/Compliance/Bridge stubs from `_fixtures.py`
(the barrier resolution logic never inspects their `pair` field itself --
only `front_half.strategy.pair`, already verified directly against
`_run_back_half`)."""

from __future__ import annotations

import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from typing import Dict, Tuple

from titan_protocol.opportunity_selection_engine.config import (
    EnabledOpportunityWindow,
    OpportunitySelectionEngineConfig,
)
from titan_protocol.opportunity_selection_engine.engine import OpportunitySelectionEngine
from titan_protocol.opportunity_selection_engine.store import OpportunityWinnerStore
from titan_protocol.risk_engine.models import PortfolioState
from titan_protocol.runtime.engine import RuntimeOrchestrator
from titan_protocol.runtime.models import CycleOutcome
from titan_protocol.strategy_engine.config import StrategyEngineConfig
from titan_protocol.strategy_engine.models import (
    QualificationResult,
    QualificationStatus,
    SessionName,
    StrategyId,
    StrategySnapshot,
    TradeIntent,
    WinningStrategy,
)
from tests.titan_protocol.runtime._fixtures import (
    T0,
    make_account_state,
    make_bars,
    make_config,
    make_market_safety_inputs,
    make_profile,
    make_stub_bridge_submit,
    make_stub_compliance_engine,
    make_stub_evidence_engine,
    make_stub_mi_engine,
    make_stub_risk_engine,
)

# The enabled window's anchor matches T0 exactly (13:00 UTC), so
# `now.replace(hour=..., minute=...)` in `run_cycle()` reproduces T0 --
# every ORB qualification below sets `range_start=T0` to land in this
# same window.
_WINDOW_HOUR = 13
_WINDOW_MINUTE = 0


class _PerPairStrategyStub:
    """`.config` mirrors the real `StrategyEngine.config` surface
    (`approved_pairs_for()`), which `run_cycle()`'s own `tracked_pairs`
    computation reads directly. `.evaluate()` returns a caller-supplied
    snapshot per pair (defaulting to a rejected snapshot for any pair not
    explicitly given one) and counts calls per pair -- proving "front half
    runs exactly once per pair regardless of window count"."""

    def __init__(self, snapshots: Dict[str, StrategySnapshot], tracked_pairs: Tuple[str, ...]):
        self._snapshots = snapshots
        self.config = StrategyEngineConfig(
            approved_pairs_by_strategy=((StrategyId.OPENING_RANGE_BREAKOUT, tracked_pairs),),
        )
        self.call_count_by_pair: Dict[str, int] = {}

    def evaluate(self, pair, evidence, market_intelligence, now=None) -> StrategySnapshot:
        self.call_count_by_pair[pair] = self.call_count_by_pair.get(pair, 0) + 1
        return self._snapshots.get(pair, _rejected_snapshot(pair))


def _rejected_snapshot(pair: str) -> StrategySnapshot:
    return StrategySnapshot(
        pair=pair, generated_at=T0, winning_strategy=None, all_qualifications=(),
        rejected=True, rejection_reason="no strategy qualified",
        supporting_evidence_summary="test", supporting_market_intelligence_summary="test",
    )


def _orb_snapshot(pair: str, score: float, range_start=T0) -> StrategySnapshot:
    qualification = QualificationResult(
        strategy_id=StrategyId.OPENING_RANGE_BREAKOUT, pair=pair, status=QualificationStatus.QUALIFIED,
        score=score, confidence=0.8, reason="test breakout", strengths=("breakout",), weaknesses=(),
        trade_intent=TradeIntent.BUY, range_start=range_start,
    )
    winning = WinningStrategy(strategy_id=StrategyId.OPENING_RANGE_BREAKOUT, qualification=qualification)
    return StrategySnapshot(
        pair=pair, generated_at=T0, winning_strategy=winning, all_qualifications=(qualification,),
        rejected=False, rejection_reason=None,
        supporting_evidence_summary="test", supporting_market_intelligence_summary="test", trade_intent=TradeIntent.BUY,
    )


def _legacy_winner_snapshot(pair: str, score: float = 80.0) -> StrategySnapshot:
    qualification = QualificationResult(
        strategy_id=StrategyId.TREND_CONTINUATION, pair=pair, status=QualificationStatus.QUALIFIED,
        score=score, confidence=0.8, reason="test trend", strengths=("trend",), weaknesses=(),
        trade_intent=TradeIntent.BUY,
    )
    winning = WinningStrategy(strategy_id=StrategyId.TREND_CONTINUATION, qualification=qualification)
    return StrategySnapshot(
        pair=pair, generated_at=T0, winning_strategy=winning, all_qualifications=(qualification,),
        rejected=False, rejection_reason=None,
        supporting_evidence_summary="test", supporting_market_intelligence_summary="test", trade_intent=TradeIntent.BUY,
    )


class _BarrierTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.state_file = Path(self._tmpdir.name) / "opportunity_winners.json"

    def _make_selection_engine(self, enabled_windows=(), tie_tolerance=0.5, cross_pair_selection_enabled=False) -> OpportunitySelectionEngine:
        store = OpportunityWinnerStore(self.state_file)
        config = OpportunitySelectionEngineConfig(
            enabled_windows=enabled_windows, tie_tolerance=tie_tolerance,
            cross_pair_selection_enabled=cross_pair_selection_enabled,
        )
        return OpportunitySelectionEngine(config, store)

    def _make_orchestrator(self, strategy_stub, opportunity_selection_engine=None, risk=None, compliance=None) -> RuntimeOrchestrator:
        return RuntimeOrchestrator(
            make_config(), make_stub_evidence_engine(), make_stub_mi_engine(), strategy_stub,
            make_stub_risk_engine(risk), make_stub_compliance_engine(compliance), make_stub_bridge_submit(),
            opportunity_selection_engine=opportunity_selection_engine,
        )

    def _one_window(self):
        return (EnabledOpportunityWindow(session_name=_SESSION, anchor_hour_utc=_WINDOW_HOUR, anchor_minute_utc=_WINDOW_MINUTE),)


_SESSION = SessionName.LONDON_NEW_YORK_OVERLAP


class TestScoreOnlyWinnerSelection(_BarrierTestCase):
    def test_highest_score_wins_and_is_the_only_one_reaching_risk(self):
        pairs = ("EURUSD", "GBPUSD")
        strategy_stub = _PerPairStrategyStub(
            {"EURUSD": _orb_snapshot("EURUSD", 80.0), "GBPUSD": _orb_snapshot("GBPUSD", 60.0)}, pairs,
        )
        engine = self._make_selection_engine(enabled_windows=self._one_window())
        orchestrator = self._make_orchestrator(strategy_stub, engine)
        profile = make_profile(allowed_pairs=pairs)
        inputs = {
            pair: (make_bars(), (), 1.0, 1.0, make_market_safety_inputs(), PortfolioState(), None, make_account_state())
            for pair in pairs
        }
        report = orchestrator.run_cycle(pairs, profile, inputs, T0, "CYCLE-1")

        by_pair = {r.pair: r for r in report.records}
        self.assertEqual(by_pair["EURUSD"].outcome, CycleOutcome.SUBMITTED)
        self.assertEqual(by_pair["GBPUSD"].outcome, CycleOutcome.NOT_SELECTED_OPPORTUNITY_WINDOW)
        self.assertEqual(orchestrator.risk_engine.call_count, 1)


class TestRealisticPostFormationTimingSelectsAWinner(_BarrierTestCase):
    """Post-implementation conformance re-review correction: every other
    test in this file historically called `run_cycle(..., T0, ...)` with
    `now == T0 == range_start`, which the now-removed duration-based
    staleness gate happened to tolerate -- masking the fact that a real
    ORB candidate can only ever exist once `now >= range_start +
    opening_range_duration_minutes` (`orb_breakout.py`'s own `is_formed`
    gate). This proves the full production path (`run_cycle()` -> barrier
    -> `OpportunitySelectionEngine` -> `OpportunityWinnerStore`) still
    selects and persists a winner when `now` reflects that reality."""

    def test_winner_selected_when_now_is_realistically_past_formation(self):
        pairs = ("EURUSD", "GBPUSD")
        strategy_stub = _PerPairStrategyStub(
            {"EURUSD": _orb_snapshot("EURUSD", 80.0), "GBPUSD": _orb_snapshot("GBPUSD", 60.0)}, pairs,
        )
        engine = self._make_selection_engine(enabled_windows=self._one_window())
        orchestrator = self._make_orchestrator(strategy_stub, engine)
        profile = make_profile(allowed_pairs=pairs)
        inputs = {
            pair: (make_bars(), (), 1.0, 1.0, make_market_safety_inputs(), PortfolioState(), None, make_account_state())
            for pair in pairs
        }
        # now.replace(hour=_WINDOW_HOUR, minute=_WINDOW_MINUTE, ...) still
        # reproduces T0 regardless of now's own hour/minute (same
        # calendar day) -- this is a realistic post-formation `now`, not
        # `now == range_start`.
        realistic_now = T0 + timedelta(minutes=31)
        report = orchestrator.run_cycle(pairs, profile, inputs, realistic_now, "CYCLE-1")

        by_pair = {r.pair: r for r in report.records}
        self.assertEqual(by_pair["EURUSD"].outcome, CycleOutcome.SUBMITTED)
        self.assertEqual(by_pair["GBPUSD"].outcome, CycleOutcome.NOT_SELECTED_OPPORTUNITY_WINDOW)
        self.assertEqual(orchestrator.risk_engine.call_count, 1)

    def test_persisted_winner_still_wins_a_much_later_same_day_cycle(self):
        pairs = ("EURUSD", "GBPUSD")
        engine = self._make_selection_engine(enabled_windows=self._one_window())

        strategy_stub_1 = _PerPairStrategyStub(
            {"EURUSD": _orb_snapshot("EURUSD", 60.0), "GBPUSD": _orb_snapshot("GBPUSD", 50.0)}, pairs,
        )
        orchestrator_1 = self._make_orchestrator(strategy_stub_1, engine)
        profile = make_profile(allowed_pairs=pairs)
        inputs = {
            pair: (make_bars(), (), 1.0, 1.0, make_market_safety_inputs(), PortfolioState(), None, make_account_state())
            for pair in pairs
        }
        first_cycle_now = T0 + timedelta(minutes=31)
        report1 = orchestrator_1.run_cycle(pairs, profile, inputs, first_cycle_now, "CYCLE-1")
        self.assertEqual({r.pair: r.outcome for r in report1.records}["EURUSD"], CycleOutcome.SUBMITTED)

        strategy_stub_2 = _PerPairStrategyStub(
            {"EURUSD": _orb_snapshot("EURUSD", 10.0), "GBPUSD": _orb_snapshot("GBPUSD", 99.0)}, pairs,
        )
        orchestrator_2 = self._make_orchestrator(strategy_stub_2, engine)
        much_later_same_day_now = T0 + timedelta(hours=6)
        report2 = orchestrator_2.run_cycle(pairs, profile, inputs, much_later_same_day_now, "CYCLE-2")
        outcome2 = {r.pair: r.outcome for r in report2.records}
        self.assertEqual(outcome2["EURUSD"], CycleOutcome.SUBMITTED, "the persisted winner must not be masked as stale")
        self.assertEqual(outcome2["GBPUSD"], CycleOutcome.NOT_SELECTED_OPPORTUNITY_WINDOW)


class TestTieProducesNoWinner(_BarrierTestCase):
    def test_tie_within_tolerance_neither_pair_reaches_risk(self):
        pairs = ("EURUSD", "GBPUSD")
        strategy_stub = _PerPairStrategyStub(
            {"EURUSD": _orb_snapshot("EURUSD", 80.0), "GBPUSD": _orb_snapshot("GBPUSD", 79.6)}, pairs,
        )
        engine = self._make_selection_engine(enabled_windows=self._one_window(), tie_tolerance=0.5)
        orchestrator = self._make_orchestrator(strategy_stub, engine)
        profile = make_profile(allowed_pairs=pairs)
        inputs = {
            pair: (make_bars(), (), 1.0, 1.0, make_market_safety_inputs(), PortfolioState(), None, make_account_state())
            for pair in pairs
        }
        report = orchestrator.run_cycle(pairs, profile, inputs, T0, "CYCLE-1")
        for record in report.records:
            self.assertEqual(record.outcome, CycleOutcome.NOT_SELECTED_OPPORTUNITY_WINDOW)
        self.assertEqual(orchestrator.risk_engine.call_count, 0)


class TestNonParticipatingPairsUnaffected(_BarrierTestCase):
    def test_legacy_strategy_winner_proceeds_immediately_never_waits(self):
        pairs = ("EURUSD", "GBPUSD")
        strategy_stub = _PerPairStrategyStub(
            {"EURUSD": _legacy_winner_snapshot("EURUSD"), "GBPUSD": _orb_snapshot("GBPUSD", 60.0)}, pairs,
        )
        engine = self._make_selection_engine(enabled_windows=self._one_window())
        orchestrator = self._make_orchestrator(strategy_stub, engine)
        profile = make_profile(allowed_pairs=pairs)
        inputs = {
            pair: (make_bars(), (), 1.0, 1.0, make_market_safety_inputs(), PortfolioState(), None, make_account_state())
            for pair in pairs
        }
        report = orchestrator.run_cycle(pairs, profile, inputs, T0, "CYCLE-1")
        by_pair = {r.pair: r for r in report.records}
        # EURUSD (legacy strategy, non-participating) reaches Risk
        # regardless of GBPUSD's own ORB barrier outcome.
        self.assertEqual(by_pair["EURUSD"].outcome, CycleOutcome.SUBMITTED)


class TestZeroSelectionEngineConfigured(_BarrierTestCase):
    def test_no_opportunity_selection_engine_all_pairs_proceed_as_before(self):
        pairs = ("EURUSD", "GBPUSD")
        strategy_stub = _PerPairStrategyStub(
            {"EURUSD": _orb_snapshot("EURUSD", 80.0), "GBPUSD": _orb_snapshot("GBPUSD", 60.0)}, pairs,
        )
        orchestrator = self._make_orchestrator(strategy_stub, opportunity_selection_engine=None)
        profile = make_profile(allowed_pairs=pairs)
        inputs = {
            pair: (make_bars(), (), 1.0, 1.0, make_market_safety_inputs(), PortfolioState(), None, make_account_state())
            for pair in pairs
        }
        report = orchestrator.run_cycle(pairs, profile, inputs, T0, "CYCLE-1")
        for record in report.records:
            self.assertEqual(record.outcome, CycleOutcome.SUBMITTED)


class TestFrontHalfInvokedExactlyOnce(_BarrierTestCase):
    def test_front_half_runs_once_per_pair_regardless_of_window_count(self):
        pairs = ("EURUSD",)
        strategy_stub = _PerPairStrategyStub({"EURUSD": _orb_snapshot("EURUSD", 80.0)}, pairs)
        windows = tuple(
            EnabledOpportunityWindow(session_name=_SESSION, anchor_hour_utc=h, anchor_minute_utc=0)
            for h in (1, 5, 9, 13)
        )
        engine = self._make_selection_engine(enabled_windows=windows)
        orchestrator = self._make_orchestrator(strategy_stub, engine)
        profile = make_profile(allowed_pairs=pairs)
        inputs = {"EURUSD": (make_bars(), (), 1.0, 1.0, make_market_safety_inputs(), PortfolioState(), None, make_account_state())}
        orchestrator.run_cycle(pairs, profile, inputs, T0, "CYCLE-1")
        self.assertEqual(strategy_stub.call_count_by_pair["EURUSD"], 1)


class TestWindowCardinality(_BarrierTestCase):
    def _run_with_n_windows(self, n: int):
        pairs = ("EURUSD",)
        strategy_stub = _PerPairStrategyStub({"EURUSD": _orb_snapshot("EURUSD", 80.0)}, pairs)
        windows = tuple(
            EnabledOpportunityWindow(session_name=_SESSION, anchor_hour_utc=h, anchor_minute_utc=0)
            for h in range(n)
        ) if n else ()
        engine = self._make_selection_engine(enabled_windows=windows) if n else None
        orchestrator = self._make_orchestrator(strategy_stub, engine)
        profile = make_profile(allowed_pairs=pairs)
        inputs = {"EURUSD": (make_bars(), (), 1.0, 1.0, make_market_safety_inputs(), PortfolioState(), None, make_account_state())}
        return orchestrator.run_cycle(pairs, profile, inputs, T0, "CYCLE-1")

    def test_zero_windows(self):
        report = self._run_with_n_windows(0)
        self.assertEqual(len(report.records), 1)

    def test_one_window(self):
        report = self._run_with_n_windows(1)
        self.assertEqual(len(report.records), 1)

    def test_two_windows(self):
        report = self._run_with_n_windows(2)
        self.assertEqual(len(report.records), 1)

    def test_three_windows(self):
        report = self._run_with_n_windows(3)
        self.assertEqual(len(report.records), 1)

    def test_more_than_three_windows(self):
        report = self._run_with_n_windows(5)
        self.assertEqual(len(report.records), 1)


class TestIncompleteScanFailsClosed(_BarrierTestCase):
    def test_a_tracked_pair_that_never_reaches_strategy_completion_closes_the_whole_window(self):
        """`GBPUSD` is tracked (approved for ORB) but its front half fails
        before Strategy ever completes -- `strategy_completed=False` --
        so the window-wide scan is judged incomplete and even EURUSD's own
        genuine ORB candidate must be rejected, never passed to the
        engine at all."""
        pairs = ("EURUSD", "GBPUSD")
        strategy_stub = _PerPairStrategyStub({"EURUSD": _orb_snapshot("EURUSD", 80.0)}, pairs)  # GBPUSD -> rejected (pre-Strategy-style stand-in)

        # Simulate GBPUSD never completing Strategy by having its evidence
        # engine raise -- forces a pre-Strategy FAILED record for GBPUSD,
        # which the real `_run_front_half` correctly marks incomplete.
        class _FailingEvidenceForGBP:
            call_count = 0

            def evaluate_snapshot(self, pair, bars, now):
                self.call_count += 1
                if pair == "GBPUSD":
                    raise RuntimeError("simulated evidence failure")
                from tests.titan_protocol.risk_engine._fixtures import make_evidence_snapshot
                return make_evidence_snapshot(symbol=pair, now=now)

        engine = self._make_selection_engine(enabled_windows=self._one_window())
        orchestrator = RuntimeOrchestrator(
            make_config(), _FailingEvidenceForGBP(), make_stub_mi_engine(), strategy_stub,
            make_stub_risk_engine(), make_stub_compliance_engine(), make_stub_bridge_submit(),
            opportunity_selection_engine=engine,
        )
        profile = make_profile(allowed_pairs=pairs)
        inputs = {
            pair: (make_bars(), (), 1.0, 1.0, make_market_safety_inputs(), PortfolioState(), None, make_account_state())
            for pair in pairs
        }
        report = orchestrator.run_cycle(pairs, profile, inputs, T0, "CYCLE-1")
        by_pair = {r.pair: r for r in report.records}
        self.assertEqual(by_pair["GBPUSD"].outcome, CycleOutcome.FAILED)
        self.assertEqual(by_pair["EURUSD"].outcome, CycleOutcome.NOT_SELECTED_OPPORTUNITY_WINDOW)
        self.assertIn("incomplete", by_pair["EURUSD"].reasons[0])


class TestSelectorFailureClosesWindow(_BarrierTestCase):
    def test_selector_exception_terminates_every_pending_candidate(self):
        pairs = ("EURUSD",)
        strategy_stub = _PerPairStrategyStub({"EURUSD": _orb_snapshot("EURUSD", 80.0)}, pairs)
        engine = self._make_selection_engine(enabled_windows=self._one_window())

        def _boom(*args, **kwargs):
            raise RuntimeError("simulated selector failure")

        engine.evaluate_window = _boom
        orchestrator = self._make_orchestrator(strategy_stub, engine)
        profile = make_profile(allowed_pairs=pairs)
        inputs = {"EURUSD": (make_bars(), (), 1.0, 1.0, make_market_safety_inputs(), PortfolioState(), None, make_account_state())}
        report = orchestrator.run_cycle(pairs, profile, inputs, T0, "CYCLE-1")
        self.assertEqual(report.records[0].outcome, CycleOutcome.NOT_SELECTED_OPPORTUNITY_WINDOW)
        self.assertIn("failed", report.records[0].reasons[0])


class TestWinnerImmutabilityAcrossCycles(_BarrierTestCase):
    def test_a_second_cycle_with_a_higher_scoring_candidate_cannot_displace_the_first_winner(self):
        pairs = ("EURUSD", "GBPUSD")
        engine = self._make_selection_engine(enabled_windows=self._one_window())

        strategy_stub_1 = _PerPairStrategyStub(
            {"EURUSD": _orb_snapshot("EURUSD", 60.0), "GBPUSD": _orb_snapshot("GBPUSD", 50.0)}, pairs,
        )
        orchestrator_1 = self._make_orchestrator(strategy_stub_1, engine)
        profile = make_profile(allowed_pairs=pairs)
        inputs = {
            pair: (make_bars(), (), 1.0, 1.0, make_market_safety_inputs(), PortfolioState(), None, make_account_state())
            for pair in pairs
        }
        report1 = orchestrator_1.run_cycle(pairs, profile, inputs, T0, "CYCLE-1")
        winner1 = {r.pair: r.outcome for r in report1.records}
        self.assertEqual(winner1["EURUSD"], CycleOutcome.SUBMITTED)

        strategy_stub_2 = _PerPairStrategyStub(
            {"EURUSD": _orb_snapshot("EURUSD", 10.0), "GBPUSD": _orb_snapshot("GBPUSD", 99.0)}, pairs,
        )
        orchestrator_2 = self._make_orchestrator(strategy_stub_2, engine)
        report2 = orchestrator_2.run_cycle(pairs, profile, inputs, T0, "CYCLE-2")
        winner2 = {r.pair: r.outcome for r in report2.records}
        # EURUSD is still the durable winner for this range_start, despite
        # GBPUSD's dramatically higher score this cycle.
        self.assertEqual(winner2["EURUSD"], CycleOutcome.SUBMITTED)
        self.assertEqual(winner2["GBPUSD"], CycleOutcome.NOT_SELECTED_OPPORTUNITY_WINDOW)


class TestAnchorNotEnabledForSelectionFailsClosedWithDistinctSignal(_BarrierTestCase):
    """ADR-037 SS11 item 2 / SS12's defense-in-depth backstop (adversarial-
    review row 18, post-implementation correction): a genuine, currently-
    relevant ORB win whose range_start matches no enabled window, while
    `cross_pair_selection_enabled` is `True`, must (a) emit a distinct
    runtime signal, never conflated with ordinary non-participating
    observability, and (b) never reach Risk -- fail closed, exactly as
    SS12's "Absolute requirement" states."""

    def test_pair_never_reaches_risk_and_distinct_signal_is_emitted(self):
        pairs = ("EURUSD",)
        strategy_stub = _PerPairStrategyStub({"EURUSD": _orb_snapshot("EURUSD", 80.0)}, pairs)
        # No enabled windows at all -- EURUSD's own range_start (T0)
        # cannot match anything, exactly the "anchor not enabled"
        # scenario, with selection declared active.
        engine = self._make_selection_engine(enabled_windows=(), cross_pair_selection_enabled=True)
        risk_stub = make_stub_risk_engine()
        orchestrator = self._make_orchestrator(strategy_stub, engine)
        orchestrator.risk_engine = risk_stub
        profile = make_profile(allowed_pairs=pairs)
        inputs = {"EURUSD": (make_bars(), (), 1.0, 1.0, make_market_safety_inputs(), PortfolioState(), None, make_account_state())}

        with self.assertLogs("titan_protocol.runtime.engine", level="ERROR") as logs:
            report = orchestrator.run_cycle(pairs, profile, inputs, T0, "CYCLE-1")

        self.assertEqual(len(report.records), 1)
        record = report.records[0]
        self.assertEqual(record.outcome, CycleOutcome.NOT_SELECTED_OPPORTUNITY_WINDOW)
        self.assertIn("not enabled for cross-pair selection", record.reasons[0])
        self.assertEqual(risk_stub.call_count, 0, "the pair must never reach Risk in this scenario")
        self.assertTrue(
            any("opportunity_anchor_not_enabled_for_selection" in line for line in logs.output),
            f"expected the distinct SS12 signal in logs, got: {logs.output}",
        )


class TestAnchorNotEnabledForSelectionInactiveProceedsUnchanged(_BarrierTestCase):
    """Regression proof: when `cross_pair_selection_enabled` is `False`
    (the default, matching production wiring today), the identical
    "anchor matches no enabled window" scenario proceeds exactly as
    before this correction -- immediately, unrestricted -- since SS11
    item 3's narrow/inert flavor never requires suppression."""

    def test_pair_proceeds_to_risk_when_selection_is_not_active(self):
        pairs = ("EURUSD",)
        strategy_stub = _PerPairStrategyStub({"EURUSD": _orb_snapshot("EURUSD", 80.0)}, pairs)
        engine = self._make_selection_engine(enabled_windows=())  # cross_pair_selection_enabled defaults False
        orchestrator = self._make_orchestrator(strategy_stub, engine)
        profile = make_profile(allowed_pairs=pairs)
        inputs = {"EURUSD": (make_bars(), (), 1.0, 1.0, make_market_safety_inputs(), PortfolioState(), None, make_account_state())}

        report = orchestrator.run_cycle(pairs, profile, inputs, T0, "CYCLE-1")

        self.assertEqual(report.records[0].outcome, CycleOutcome.SUBMITTED)

    def test_no_opportunity_selection_engine_at_all_proceeds_unchanged(self):
        pairs = ("EURUSD",)
        strategy_stub = _PerPairStrategyStub({"EURUSD": _orb_snapshot("EURUSD", 80.0)}, pairs)
        orchestrator = self._make_orchestrator(strategy_stub, opportunity_selection_engine=None)
        profile = make_profile(allowed_pairs=pairs)
        inputs = {"EURUSD": (make_bars(), (), 1.0, 1.0, make_market_safety_inputs(), PortfolioState(), None, make_account_state())}

        report = orchestrator.run_cycle(pairs, profile, inputs, T0, "CYCLE-1")

        self.assertEqual(report.records[0].outcome, CycleOutcome.SUBMITTED)


class TestLegacyWinnerUnaffectedWhenSelectionActiveAndAnchorMismatchOccurs(_BarrierTestCase):
    """Proves the correction is isolated: an ordinary legacy-strategy
    winner in the *same* cycle as an anchor-not-enabled ORB suppression
    still proceeds to Risk exactly as always -- the new check never
    touches non-ORB routing."""

    def test_legacy_winner_still_proceeds_while_orb_anchor_mismatch_is_suppressed(self):
        pairs = ("EURUSD", "GBPUSD")
        strategy_stub = _PerPairStrategyStub(
            {"EURUSD": _legacy_winner_snapshot("EURUSD"), "GBPUSD": _orb_snapshot("GBPUSD", 80.0)}, pairs,
        )
        engine = self._make_selection_engine(enabled_windows=(), cross_pair_selection_enabled=True)
        orchestrator = self._make_orchestrator(strategy_stub, engine)
        profile = make_profile(allowed_pairs=pairs)
        inputs = {
            pair: (make_bars(), (), 1.0, 1.0, make_market_safety_inputs(), PortfolioState(), None, make_account_state())
            for pair in pairs
        }

        with self.assertLogs("titan_protocol.runtime.engine", level="ERROR"):
            report = orchestrator.run_cycle(pairs, profile, inputs, T0, "CYCLE-1")

        by_pair = {r.pair: r for r in report.records}
        self.assertEqual(by_pair["EURUSD"].outcome, CycleOutcome.SUBMITTED)
        self.assertEqual(by_pair["GBPUSD"].outcome, CycleOutcome.NOT_SELECTED_OPPORTUNITY_WINDOW)


_ORB_PAIRS_3 = ("EURUSD", "GBPUSD", "USDJPY")
_LONDON_HOUR, _LONDON_MINUTE = 8, 0
_OVERLAP_HOUR, _OVERLAP_MINUTE = 13, 0


class TestF1BroadGateARequiresCompleteBarrierCoverage(_BarrierTestCase):
    """ADR-037 Production Activation Plan (bb8b4a6) §4.0/§10, F1: the
    safety-critical finding from the independent Plan review, pinned as
    executable regression proof -- not merely re-asserted from the
    review's own report. `enabled_windows` coverage, not
    `cross_pair_selection_enabled`, is what makes a broadened,
    multi-pair Gate A safe. Every test below constructs the real
    `RuntimeOrchestrator` + `OpportunitySelectionEngine` +
    `OpportunityWinnerStore` (no mocks below the Runtime layer, matching
    this file's own established convention) and asserts actual
    `CycleOutcome`/Risk-reachability, never merely configuration state."""

    def test_broad_gate_a_with_empty_enabled_windows_and_flag_false_is_unarbitrated(self):
        """P6 (forbidden): every independently-qualified ORB pair takes
        the ordinary non-participating path straight into
        `_run_back_half()` -- this is the exact defect the Plan revision
        corrects the activation sequencing to never reach."""
        strategy_stub = _PerPairStrategyStub(
            {p: _orb_snapshot(p, 80.0 - i, range_start=T0) for i, p in enumerate(_ORB_PAIRS_3)}, _ORB_PAIRS_3,
        )
        engine = self._make_selection_engine(enabled_windows=(), cross_pair_selection_enabled=False)
        orchestrator = self._make_orchestrator(strategy_stub, engine)
        profile = make_profile(allowed_pairs=_ORB_PAIRS_3)
        inputs = {
            p: (make_bars(), (), 1.0, 1.0, make_market_safety_inputs(), PortfolioState(), None, make_account_state())
            for p in _ORB_PAIRS_3
        }

        report = orchestrator.run_cycle(_ORB_PAIRS_3, profile, inputs, T0 + timedelta(minutes=31), "CYCLE-1")

        by_pair = {r.pair: r.outcome for r in report.records}
        self.assertEqual(by_pair, {p: CycleOutcome.SUBMITTED for p in _ORB_PAIRS_3})
        self.assertEqual(orchestrator.risk_engine.call_count, len(_ORB_PAIRS_3))

    def test_broad_gate_a_with_partial_enabled_windows_leaves_the_uncovered_window_unarbitrated(self):
        """P7 (forbidden): partial coverage protects only the covered
        window -- candidates sharing an uncovered window's `range_start`
        are exactly as unarbitrated as P6, independent of the flag."""
        pairs = ("EURUSD", "GBPUSD", "USDJPY")
        london_range_start = T0.replace(hour=_LONDON_HOUR, minute=_LONDON_MINUTE)
        overlap_range_start = T0.replace(hour=_OVERLAP_HOUR, minute=_OVERLAP_MINUTE)
        strategy_stub = _PerPairStrategyStub(
            {
                "EURUSD": _orb_snapshot("EURUSD", 80.0, range_start=overlap_range_start),  # covered window
                "GBPUSD": _orb_snapshot("GBPUSD", 75.0, range_start=london_range_start),   # uncovered window
                "USDJPY": _orb_snapshot("USDJPY", 70.0, range_start=london_range_start),   # uncovered window (shared)
            },
            pairs,
        )
        covered_only = (EnabledOpportunityWindow(
            session_name=_SESSION, anchor_hour_utc=_OVERLAP_HOUR, anchor_minute_utc=_OVERLAP_MINUTE,
        ),)
        engine = self._make_selection_engine(enabled_windows=covered_only, cross_pair_selection_enabled=False)
        orchestrator = self._make_orchestrator(strategy_stub, engine)
        profile = make_profile(allowed_pairs=pairs)
        inputs = {
            p: (make_bars(), (), 1.0, 1.0, make_market_safety_inputs(), PortfolioState(), None, make_account_state())
            for p in pairs
        }

        now = T0.replace(hour=_LONDON_HOUR, minute=_LONDON_MINUTE + 31)
        report = orchestrator.run_cycle(pairs, profile, inputs, now, "CYCLE-1")

        by_pair = {r.pair: r.outcome for r in report.records}
        # The covered window's sole candidate proceeds normally (no
        # competitor to arbitrate against); both uncovered-window
        # candidates independently reach Risk -- the exact danger.
        self.assertEqual(by_pair["EURUSD"], CycleOutcome.SUBMITTED)
        self.assertEqual(by_pair["GBPUSD"], CycleOutcome.SUBMITTED)
        self.assertEqual(by_pair["USDJPY"], CycleOutcome.SUBMITTED)
        self.assertEqual(orchestrator.risk_engine.call_count, 3)

    def test_broad_gate_a_with_complete_enabled_windows_and_flag_false_arbitrates(self):
        """P4 (safe): the corrected invariant's positive case -- barrier
        coverage alone, independent of the flag, produces exactly one
        winner."""
        strategy_stub = _PerPairStrategyStub(
            {p: _orb_snapshot(p, 80.0 - i, range_start=T0) for i, p in enumerate(_ORB_PAIRS_3)}, _ORB_PAIRS_3,
        )
        engine = self._make_selection_engine(enabled_windows=self._one_window(), cross_pair_selection_enabled=False)
        orchestrator = self._make_orchestrator(strategy_stub, engine)
        profile = make_profile(allowed_pairs=_ORB_PAIRS_3)
        inputs = {
            p: (make_bars(), (), 1.0, 1.0, make_market_safety_inputs(), PortfolioState(), None, make_account_state())
            for p in _ORB_PAIRS_3
        }

        report = orchestrator.run_cycle(_ORB_PAIRS_3, profile, inputs, T0 + timedelta(minutes=31), "CYCLE-1")

        by_pair = {r.pair: r.outcome for r in report.records}
        submitted = [p for p, o in by_pair.items() if o == CycleOutcome.SUBMITTED]
        self.assertEqual(submitted, ["EURUSD"])  # highest score
        self.assertEqual(orchestrator.risk_engine.call_count, 1)

    def test_broad_gate_a_with_complete_enabled_windows_and_flag_true_arbitrates_identically(self):
        """P5 (safe, final target state): the flag makes no observable
        difference to arbitration once coverage is complete -- proves
        the flag is a defense-in-depth backstop, never the barrier
        itself."""
        strategy_stub = _PerPairStrategyStub(
            {p: _orb_snapshot(p, 80.0 - i, range_start=T0) for i, p in enumerate(_ORB_PAIRS_3)}, _ORB_PAIRS_3,
        )
        engine = self._make_selection_engine(enabled_windows=self._one_window(), cross_pair_selection_enabled=True)
        orchestrator = self._make_orchestrator(strategy_stub, engine)
        profile = make_profile(allowed_pairs=_ORB_PAIRS_3)
        inputs = {
            p: (make_bars(), (), 1.0, 1.0, make_market_safety_inputs(), PortfolioState(), None, make_account_state())
            for p in _ORB_PAIRS_3
        }

        report = orchestrator.run_cycle(_ORB_PAIRS_3, profile, inputs, T0 + timedelta(minutes=31), "CYCLE-1")

        by_pair = {r.pair: r.outcome for r in report.records}
        submitted = [p for p, o in by_pair.items() if o == CycleOutcome.SUBMITTED]
        self.assertEqual(submitted, ["EURUSD"])
        self.assertEqual(orchestrator.risk_engine.call_count, 1)

    def test_gate_a_closed_with_barrier_prepared_leaves_orb_ineligible(self):
        """P2 (safe, the required Phase C staging state): preparing Gate
        B/`enabled_windows` while Gate A stays closed cannot itself
        activate anything -- `check_eligibility()` (not exercised by
        this Runtime-level stub, already independently verified at the
        Strategy Engine layer) would reject every pair for ORB before
        `qualify()` ever runs, so whichever real strategy actually wins
        proceeds ordinarily, exactly as it does today in production."""
        pairs = _ORB_PAIRS_3
        strategy_stub = _PerPairStrategyStub(
            {p: _legacy_winner_snapshot(p) for p in pairs}, tracked_pairs=(),  # Gate A empty
        )
        engine = self._make_selection_engine(enabled_windows=self._one_window(), cross_pair_selection_enabled=False)
        orchestrator = self._make_orchestrator(strategy_stub, engine)
        profile = make_profile(allowed_pairs=pairs)
        inputs = {
            p: (make_bars(), (), 1.0, 1.0, make_market_safety_inputs(), PortfolioState(), None, make_account_state())
            for p in pairs
        }

        report = orchestrator.run_cycle(pairs, profile, inputs, T0 + timedelta(minutes=31), "CYCLE-1")

        by_pair = {r.pair: r.outcome for r in report.records}
        # All 3 independently SUBMITTED -- but as ordinary, unrelated
        # legacy-strategy wins (call_count == 3 is expected and safe
        # here), never as ORB candidates competing for one opportunity.
        self.assertEqual(by_pair, {p: CycleOutcome.SUBMITTED for p in pairs})
        self.assertEqual(orchestrator.risk_engine.call_count, 3)

    def test_rollback_ordering_removing_coverage_reproduces_the_forbidden_state_regardless_of_history(self):
        """Rollback-ordering invariant (Plan §7.0): there is no code-level
        distinction between "`enabled_windows` was never staged" and
        "`enabled_windows` was staged, then removed while Gate A stayed
        broad" -- both produce the byte-identical P6 state. This is the
        proof that the corrected sequencing/rollback discipline must be
        an operational procedure (§6/§7), never a technical guarantee:
        no test, check, or code path can distinguish "forward activation
        skipped a step" from "rollback removed coverage out of order."""
        strategy_stub = _PerPairStrategyStub(
            {p: _orb_snapshot(p, 80.0 - i, range_start=T0) for i, p in enumerate(_ORB_PAIRS_3)}, _ORB_PAIRS_3,
        )
        # Constructing enabled_windows=() directly -- indistinguishable,
        # by construction, from "previously populated, then cleared."
        engine = self._make_selection_engine(enabled_windows=(), cross_pair_selection_enabled=False)
        orchestrator = self._make_orchestrator(strategy_stub, engine)
        profile = make_profile(allowed_pairs=_ORB_PAIRS_3)
        inputs = {
            p: (make_bars(), (), 1.0, 1.0, make_market_safety_inputs(), PortfolioState(), None, make_account_state())
            for p in _ORB_PAIRS_3
        }

        report = orchestrator.run_cycle(_ORB_PAIRS_3, profile, inputs, T0 + timedelta(minutes=31), "CYCLE-1")

        by_pair = {r.pair: r.outcome for r in report.records}
        self.assertEqual(by_pair, {p: CycleOutcome.SUBMITTED for p in _ORB_PAIRS_3})
        self.assertEqual(orchestrator.risk_engine.call_count, len(_ORB_PAIRS_3))


if __name__ == "__main__":
    unittest.main()
