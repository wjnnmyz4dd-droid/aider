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

    def _make_selection_engine(self, enabled_windows=(), tie_tolerance=0.5) -> OpportunitySelectionEngine:
        store = OpportunityWinnerStore(self.state_file)
        config = OpportunitySelectionEngineConfig(enabled_windows=enabled_windows, tie_tolerance=tie_tolerance)
        return OpportunitySelectionEngine(config, store, opening_range_duration_minutes=30)

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


if __name__ == "__main__":
    unittest.main()
