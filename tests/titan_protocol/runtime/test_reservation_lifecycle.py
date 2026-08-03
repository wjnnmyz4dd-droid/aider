"""Reservation-lifecycle tests (fix for: `RiskEngine.ReservationLedger`
entries were created on every approved trade via `reserve_if()`, but
`release_reservation()` had no production caller -- reservations leaked
permanently until Risk Engine's own portfolio-heat gate began falsely
rejecting legitimate trades).

Ownership model under test: `RuntimeOrchestrator` carries each approved
trade's `reservation_id` through the *existing* `InFlightCommandRegistry`
lifecycle (one authoritative state machine, not two) -- see
`titan_protocol/runtime/in_flight_commands.py`'s own module docstring
for the full design rationale. This file proves every release point in
that lifecycle actually releases, that release is idempotent, and that a
leaked-vs-fixed ledger produces different (and correctly different)
risk decisions.

Existing duplicate-trade-prevention and command-lifecycle tests (item 14
of the verification requirements) are not re-asserted here -- they are
`test_in_flight_commands.py`, `test_bridge_restart_integration.py`, and
the rest of this package's suite, all still green (`python3 -m unittest
discover -s tests/titan_protocol`), unmodified in behavior by this fix
beyond the return-shape changes those files already account for."""

from __future__ import annotations

import dataclasses
import threading
import unittest
from datetime import datetime, timedelta, timezone

from titan_protocol.bridge.command_queue import CommandQueue
from titan_protocol.bridge.connection_health import ConnectionHealth
from titan_protocol.bridge.engine import BridgeEngine
from titan_protocol.bridge.models import ErrorCode, ExecutionReport
from titan_protocol.compliance_engine.models import ComplianceDecision
from titan_protocol.risk_engine.config import RiskEngineConfig
from titan_protocol.risk_engine.engine import RiskEngine
from titan_protocol.risk_engine.models import Direction, OpenPosition, PortfolioState
from titan_protocol.runtime.engine import RuntimeOrchestrator
from titan_protocol.runtime.in_flight_commands import InFlightCommandRegistry
from titan_protocol.runtime.models import CycleOutcome
from tests.titan_protocol.bridge._fixtures import make_command, make_config as make_bridge_config
from tests.titan_protocol.runtime._fixtures import (
    T0,
    make_account_state,
    make_bars,
    make_compliance_snapshot,
    make_config,
    make_evidence_snapshot,
    make_market_safety_inputs,
    make_mi_snapshot,
    make_profile,
    make_qualified_strategy_snapshot,
    make_stub_bridge_submit,
    make_stub_compliance_engine,
    make_stub_evidence_engine,
    make_stub_mi_engine,
    make_stub_strategy_engine,
)


def _build_stack(compliance_decision=ComplianceDecision.APPROVE, approved_size_r=1.25, bridge_error=None):
    """One production-shaped stack: stub Evidence/MI/Strategy (fixed,
    genuinely-qualifying snapshots -- Risk Engine still runs for real),
    a REAL `RiskEngine` (the actual `ReservationLedger` under test), a
    controllable stub Compliance decision, a controllable stub Bridge
    submit result, and a REAL `InFlightCommandRegistry` -- exactly
    `RuntimeOrchestrator`'s production wiring (`deployment_windows/
    start.py`), minus a real Bridge transport (irrelevant to whether
    Runtime carries/releases the reservation_id correctly)."""
    evidence_engine = make_stub_evidence_engine(make_evidence_snapshot(evidence_score=90.0))
    mi_engine = make_stub_mi_engine(make_mi_snapshot())
    strategy_engine = make_stub_strategy_engine(make_qualified_strategy_snapshot())
    risk_engine = RiskEngine(RiskEngineConfig())
    compliance_snapshot = make_compliance_snapshot(decision=compliance_decision, approved_size_r=approved_size_r)
    compliance_engine = make_stub_compliance_engine(compliance_snapshot)
    bridge_submit = make_stub_bridge_submit(error=bridge_error)
    in_flight = InFlightCommandRegistry(ttl_seconds=300.0)
    orchestrator = RuntimeOrchestrator(
        make_config(), evidence_engine, mi_engine, strategy_engine, risk_engine, compliance_engine,
        bridge_submit, in_flight_commands=in_flight,
    )
    return orchestrator, risk_engine, in_flight


def _run_cycle(orchestrator, pair="EURUSD", now=T0, cycle_id="CYCLE-1", portfolio_state=None):
    return orchestrator.run_cycle_for_pair(
        pair, make_bars(), (), 1.0, 1.0, make_market_safety_inputs(),
        portfolio_state or PortfolioState(), None, make_account_state(), make_profile(), now, cycle_id,
    )


class TestReleasePoints(unittest.TestCase):
    """Required tests 1-6, 8: every documented release point actually
    releases, and release is idempotent."""

    def test_1_compliance_rejection_releases_reservation(self):
        orchestrator, risk_engine, _ = _build_stack(compliance_decision=ComplianceDecision.REJECT)
        record = _run_cycle(orchestrator)
        self.assertEqual(record.outcome, CycleOutcome.COMPLIANCE_REJECTED)
        self.assertEqual(risk_engine.pending_reservation_count(), 0)

    def test_2_command_submission_failure_releases_reservation(self):
        orchestrator, risk_engine, in_flight = _build_stack(bridge_error=ErrorCode.BRIDGE_NOT_READY)
        record = _run_cycle(orchestrator)
        self.assertEqual(record.outcome, CycleOutcome.BRIDGE_ERROR)
        self.assertEqual(risk_engine.pending_reservation_count(), 0)
        # Ownership never transferred: BRIDGE_ERROR means record_submission()
        # was never called (see engine.py's own comment on this branch).
        self.assertEqual(in_flight.in_flight_count(), 0)

    def test_3_command_abandonment_releases_reservation(self):
        orchestrator, risk_engine, in_flight = _build_stack()
        _run_cycle(orchestrator)
        self.assertEqual(risk_engine.pending_reservation_count(), 1, "submission must reserve exactly once")
        later = T0 + timedelta(seconds=16)
        outcome = in_flight.reconcile(later, is_resolved=lambda cid: False, is_abandoned=lambda cid: True)
        self.assertEqual(outcome.dropped_count, 1)
        self.assertEqual(len(outcome.released_reservation_ids), 1)
        for reservation_id in outcome.released_reservation_ids:
            risk_engine.release_reservation(reservation_id)
        self.assertEqual(risk_engine.pending_reservation_count(), 0)

    def test_4_execution_rejection_releases_reservation(self):
        orchestrator, risk_engine, in_flight = _build_stack()
        _run_cycle(orchestrator)
        self.assertEqual(risk_engine.pending_reservation_count(), 1)
        outcome = in_flight.reconcile(
            T0 + timedelta(seconds=2), is_resolved=lambda cid: True, execution_succeeded=lambda cid: False,
        )
        self.assertEqual(outcome.dropped_count, 1)
        self.assertEqual(len(outcome.released_reservation_ids), 1)
        for reservation_id in outcome.released_reservation_ids:
            risk_engine.release_reservation(reservation_id)
        self.assertEqual(risk_engine.pending_reservation_count(), 0)

    def test_5_execution_success_retains_reservation_until_confirmation(self):
        orchestrator, risk_engine, in_flight = _build_stack()
        _run_cycle(orchestrator)
        self.assertEqual(risk_engine.pending_reservation_count(), 1)
        outcome = in_flight.reconcile(
            T0 + timedelta(seconds=2), is_resolved=lambda cid: True, execution_succeeded=lambda cid: True,
        )
        self.assertEqual(outcome.dropped_count, 1)
        self.assertEqual(outcome.released_reservation_ids, ())
        self.assertTrue(in_flight.is_awaiting_position_confirmation("EURUSD"))
        # Not released -- still 1 pending, exactly what proves the fix
        # never releases on execution success alone.
        self.assertEqual(risk_engine.pending_reservation_count(), 1)

    def test_6_position_confirmation_releases_reservation(self):
        orchestrator, risk_engine, in_flight = _build_stack()
        _run_cycle(orchestrator)
        in_flight.reconcile(T0 + timedelta(seconds=2), is_resolved=lambda cid: True, execution_succeeded=lambda cid: True)
        self.assertEqual(risk_engine.pending_reservation_count(), 1)
        confirmed = in_flight.confirm_position_report(T0 + timedelta(seconds=5))
        self.assertEqual(len(confirmed), 1)
        for reservation_id in confirmed:
            self.assertIsNotNone(reservation_id)
            risk_engine.release_reservation(reservation_id)
        self.assertEqual(risk_engine.pending_reservation_count(), 0)
        self.assertFalse(in_flight.has_unresolved("EURUSD", T0 + timedelta(seconds=5)))

    def test_8_repeated_release_is_harmless(self):
        orchestrator, risk_engine, in_flight = _build_stack()
        _run_cycle(orchestrator)
        in_flight.reconcile(T0 + timedelta(seconds=2), is_resolved=lambda cid: True, execution_succeeded=lambda cid: True)
        (reservation_id,) = in_flight.confirm_position_report(T0 + timedelta(seconds=5))
        first = risk_engine.release_reservation(reservation_id)
        second = risk_engine.release_reservation(reservation_id)
        third = risk_engine.release_reservation("never-existed")
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertFalse(third)
        self.assertEqual(risk_engine.pending_reservation_count(), 0)


class TestExposureAfterConfirmation(unittest.TestCase):
    def test_7_exposure_and_reservation_never_double_counted_after_confirmation(self):
        """Required test 7: once a reservation is released via position
        confirmation, a subsequent `evaluate()` call that supplies the
        now-real position in `PortfolioState` must see exactly that
        position's size -- never the position PLUS a leftover
        reservation for the same risk."""
        orchestrator, risk_engine, in_flight = _build_stack()
        _run_cycle(orchestrator)
        in_flight.reconcile(T0 + timedelta(seconds=2), is_resolved=lambda cid: True, execution_succeeded=lambda cid: True)
        (reservation_id,) = in_flight.confirm_position_report(T0 + timedelta(seconds=5))
        risk_engine.release_reservation(reservation_id)
        self.assertEqual(risk_engine.pending_reservation_total_r(), 0.0)

        # The trade just confirmed is now real, live exposure -- represent
        # it in PortfolioState with the SAME size the engine actually
        # approved (fail-closed sizing with no trade_history caps every
        # approval at config.fail_closed_tier.base_r, not the raw
        # confidence-tier base_r -- see position_sizing.py).
        approved_size_r = RiskEngineConfig().fail_closed_tier.base_r
        portfolio_state = PortfolioState(
            open_positions=(OpenPosition(pair="EURUSD", direction=Direction.LONG, size_r=approved_size_r, opened_at=T0),),
        )
        # Access the real exposure snapshot via a direct evaluate() call
        # (RuntimeAuditRecord itself does not carry exposure_summary).
        # No other reservation is pending at this point, so the exposure
        # this call's own predicate observes (computed BEFORE this call's
        # own candidate is reserved -- see RiskEngine._evaluate()) must
        # show exactly the real position, never the position plus a
        # leftover reservation for the same, already-confirmed risk.
        risk_snapshot = risk_engine.evaluate(
            "EURUSD", make_evidence_snapshot(evidence_score=90.0), make_mi_snapshot(),
            make_qualified_strategy_snapshot(), portfolio_state, None, T0 + timedelta(seconds=10),
        )
        self.assertEqual(risk_snapshot.exposure_summary.portfolio_heat_r, approved_size_r)
        self.assertEqual(risk_snapshot.exposure_summary.pending_reservation_total_r, 0.0)
        if risk_snapshot.reservation_id is not None:
            risk_engine.release_reservation(risk_snapshot.reservation_id)


class TestDuplicateExecutionReports(unittest.TestCase):
    def test_9_duplicate_execution_reports_do_not_corrupt_state(self):
        """Required test 9: a real `BridgeEngine`/`CommandQueue` so
        `handle_execution_report()`'s own dedup (`CommandQueue.
        record_result()`) is exercised, not simulated."""
        config = make_bridge_config()
        health = ConnectionHealth(config, lambda: T0)
        health.record_heartbeat(T0)
        bridge_engine = BridgeEngine(config, CommandQueue(config), health, lambda: T0)
        in_flight = InFlightCommandRegistry(ttl_seconds=300.0)
        risk_engine = RiskEngine(RiskEngineConfig())

        risk_snapshot = risk_engine.evaluate(
            "EURUSD", make_evidence_snapshot(evidence_score=90.0), make_mi_snapshot(),
            make_qualified_strategy_snapshot(), PortfolioState(), None, T0,
        )
        self.assertTrue(risk_snapshot.approved)
        command = make_command(correlation_id="corr-1", issued_at=T0)
        self.assertIsNone(bridge_engine.submit_command(command, T0))
        in_flight.record_submission("EURUSD", "corr-1", T0, reservation_id=risk_snapshot.reservation_id)
        bridge_engine.poll_commands(T0 + timedelta(seconds=1))

        report = ExecutionReport(
            schema_version=1, correlation_id="corr-1", magic_number=20260709,
            success=True, broker_ticket="1", filled_price=1.1, filled_volume=0.1,
            error_code=None, reported_at=T0 + timedelta(seconds=2),
        )
        self.assertTrue(bridge_engine.handle_execution_report(report))
        duplicate = ExecutionReport(
            schema_version=1, correlation_id="corr-1", magic_number=20260709,
            success=False, broker_ticket="2", filled_price=1.2, filled_volume=0.2,
            error_code=None, reported_at=T0 + timedelta(seconds=3),
        )
        self.assertFalse(bridge_engine.handle_execution_report(duplicate), "a second report for a resolved id must never overwrite the first")

        outcome = in_flight.reconcile(
            T0 + timedelta(seconds=4), bridge_engine.command_resolved, execution_succeeded=bridge_engine.execution_succeeded,
        )
        # The FIRST (successful) report is authoritative -- the entry
        # moves to awaiting-confirmation, not released outright, and the
        # duplicate's contradicting `success=False` never influenced it.
        self.assertEqual(outcome.dropped_count, 1)
        self.assertEqual(outcome.released_reservation_ids, ())
        self.assertEqual(risk_engine.pending_reservation_count(), 1)

        confirmed = in_flight.confirm_position_report(T0 + timedelta(seconds=5))
        self.assertEqual(len(confirmed), 1)
        risk_engine.release_reservation(confirmed[0])
        self.assertEqual(risk_engine.pending_reservation_count(), 0)

        # Reconciling again finds nothing left to drop/release for this
        # pair -- no double-release, no negative/corrupted count.
        second_outcome = in_flight.reconcile(
            T0 + timedelta(seconds=6), bridge_engine.command_resolved, execution_succeeded=bridge_engine.execution_succeeded,
        )
        self.assertEqual(second_outcome.dropped_count, 0)
        self.assertEqual(second_outcome.released_reservation_ids, ())
        self.assertEqual(risk_engine.pending_reservation_count(), 0)


class TestRestartOwnership(unittest.TestCase):
    def test_10_restart_reconciles_reservation_ownership_safely(self):
        """Required test 10: `ReservationLedger` starts empty after every
        restart by design (in-memory only, never persisted) -- a
        restored entry's `reservation_id` therefore refers to nothing in
        the fresh engine. Confirms this is a harmless, correct no-op
        (never a crash, never a phantom release against a wrong id),
        while the pair-level block itself IS correctly restored."""
        orchestrator, risk_engine, in_flight = _build_stack()
        _run_cycle(orchestrator)
        self.assertEqual(risk_engine.pending_reservation_count(), 1)
        snapshot = in_flight.snapshot_for_persistence()
        self.assertEqual(len(snapshot), 1)
        old_reservation_id = snapshot[0].reservation_id
        self.assertIsNotNone(old_reservation_id)

        restarted_registry = InFlightCommandRegistry(ttl_seconds=300.0)
        restarted_risk_engine = RiskEngine(RiskEngineConfig())  # fresh process, fresh empty ledger
        restart_time = T0 + timedelta(seconds=5)
        restored_count = restarted_registry.restore(snapshot, restart_time)
        self.assertEqual(restored_count, 1)
        self.assertTrue(restarted_registry.has_unresolved("EURUSD", restart_time))

        # The old id means nothing to the new, empty ledger -- release
        # must be a harmless no-op, never an exception or a corruption.
        released = restarted_risk_engine.release_reservation(old_reservation_id)
        self.assertFalse(released)
        self.assertEqual(restarted_risk_engine.pending_reservation_count(), 0)


class TestManyLifecyclesLedgerSize(unittest.TestCase):
    def test_11_ledger_returns_to_correct_count_after_many_lifecycles(self):
        """Required test 11: the exact defect this fix closes -- before
        it, this loop would leave `pending_reservation_count()` growing
        by one every iteration, never returning to zero."""
        orchestrator, risk_engine, in_flight = _build_stack()
        now = T0
        for i in range(10):
            record = _run_cycle(orchestrator, now=now, cycle_id=f"CYCLE-{i}")
            self.assertEqual(record.outcome, CycleOutcome.SUBMITTED)
            outcome = in_flight.reconcile(
                now + timedelta(seconds=1), is_resolved=lambda cid: True, execution_succeeded=lambda cid: True,
            )
            self.assertEqual(outcome.dropped_count, 1)
            confirmed = in_flight.confirm_position_report(now + timedelta(seconds=2))
            self.assertEqual(len(confirmed), 1)
            risk_engine.release_reservation(confirmed[0])
            now += timedelta(seconds=5)

        self.assertEqual(risk_engine.pending_reservation_count(), 0)
        self.assertEqual(in_flight.in_flight_count(), 0)
        self.assertEqual(in_flight.awaiting_position_confirmation_count(), 0)


class TestFreshVsLongRunningEngineParity(unittest.TestCase):
    def test_12_fresh_and_fully_resolved_long_running_engine_agree(self):
        """Required test 12: a resolved-and-released reservation leaves
        no residual influence on a future decision -- a brand-new engine
        and a long-running one (having fully cycled through many
        approve/release lifecycles) must decide identically given
        identical inputs."""
        config = RiskEngineConfig()
        fresh_engine = RiskEngine(config)
        used_engine = RiskEngine(config)

        now = T0
        for i in range(5):
            snapshot = used_engine.evaluate(
                "GBPUSD", make_evidence_snapshot(symbol="GBPUSD", evidence_score=90.0),
                make_mi_snapshot(pair="GBPUSD"), make_qualified_strategy_snapshot(pair="GBPUSD"),
                PortfolioState(), None, now,
            )
            if snapshot.reservation_id is not None:
                used_engine.release_reservation(snapshot.reservation_id)
            now += timedelta(seconds=5)

        self.assertEqual(used_engine.pending_reservation_count(), 0)

        evaluate_at = T0 + timedelta(hours=1)
        result_fresh = fresh_engine.evaluate(
            "EURUSD", make_evidence_snapshot(evidence_score=90.0), make_mi_snapshot(),
            make_qualified_strategy_snapshot(), PortfolioState(), None, evaluate_at,
        )
        result_used = used_engine.evaluate(
            "EURUSD", make_evidence_snapshot(evidence_score=90.0), make_mi_snapshot(),
            make_qualified_strategy_snapshot(), PortfolioState(), None, evaluate_at,
        )
        # reservation_id is a fresh identity each call by design -- every
        # other field must be identical.
        self.assertEqual(
            dataclasses.replace(result_fresh, reservation_id=None),
            dataclasses.replace(result_used, reservation_id=None),
        )
        if result_fresh.reservation_id is not None:
            fresh_engine.release_reservation(result_fresh.reservation_id)
        if result_used.reservation_id is not None:
            used_engine.release_reservation(result_used.reservation_id)


class TestConcurrency(unittest.TestCase):
    def test_13_concurrent_release_confirmation_abandonment_replay_are_race_free(self):
        """Required test 13: hammer the same reservation's release from
        many threads (idempotency under concurrency, ADR-027 Hard Rule 5
        territory) plus concurrent `confirm_position_report()`/
        `expire_stale_position_confirmations()`/`reconcile()` calls
        across independent pairs -- no exception, no corrupted count."""
        risk_engine = RiskEngine(RiskEngineConfig())
        in_flight = InFlightCommandRegistry(ttl_seconds=300.0, position_confirmation_timeout_seconds=5.0)

        pairs = [f"PAIR{i}" for i in range(8)]
        reservation_ids = {}
        for i, pair in enumerate(pairs):
            snapshot = risk_engine.evaluate(
                pair, make_evidence_snapshot(symbol=pair, evidence_score=90.0), make_mi_snapshot(pair=pair),
                make_qualified_strategy_snapshot(pair=pair), PortfolioState(), None, T0,
            )
            self.assertTrue(snapshot.approved)
            in_flight.record_submission(pair, f"corr-{i}", T0, reservation_id=snapshot.reservation_id)
            reservation_ids[pair] = snapshot.reservation_id

        # Half resolve successfully (awaiting confirmation), half abandon.
        resolved_pairs = set(pairs[:4])
        outcome = in_flight.reconcile(
            T0 + timedelta(seconds=1),
            is_resolved=lambda cid: any(cid == f"corr-{i}" for i, p in enumerate(pairs) if p in resolved_pairs),
            is_abandoned=lambda cid: any(cid == f"corr-{i}" for i, p in enumerate(pairs) if p not in resolved_pairs),
            execution_succeeded=lambda cid: True,
        )
        errors = []

        def release_repeatedly(reservation_id):
            try:
                for _ in range(50):
                    risk_engine.release_reservation(reservation_id)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        def confirm_repeatedly():
            try:
                for _ in range(50):
                    in_flight.confirm_position_report(T0 + timedelta(seconds=2))
                    in_flight.expire_stale_position_confirmations(T0 + timedelta(seconds=2))
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=release_repeatedly, args=(rid,)) for rid in outcome.released_reservation_ids]
        threads += [threading.Thread(target=confirm_repeatedly) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        # Drain whatever confirm_position_report() released concurrently.
        for pair in resolved_pairs:
            reservation_id = reservation_ids[pair]
            risk_engine.release_reservation(reservation_id)
        self.assertEqual(risk_engine.pending_reservation_count(), 0)
        self.assertGreaterEqual(risk_engine.pending_reservation_count(), 0)  # never negative


class TestRegressionReproducesOriginalDefect(unittest.TestCase):
    """The regression test the Implementation Rules require: reproduces
    the original leak's observable symptom under the OLD (never-release)
    behavior, then shows the corrected (always-release-on-resolution)
    behavior no longer exhibits it, using this repo's own configured
    `portfolio_heat_limit_r` default (6.0 R) and evidence score 90 (TIER_5,
    base_r=1.25 R per trade -- 5 approvals reach 6.25 R, over the limit)."""

    def _approve_one(self, engine, now):
        return engine.evaluate(
            "EURUSD", make_evidence_snapshot(evidence_score=90.0), make_mi_snapshot(),
            make_qualified_strategy_snapshot(), PortfolioState(), None, now,
        )

    def test_leaked_reservations_eventually_false_reject_then_fixed_flow_approves(self):
        config = RiskEngineConfig()
        self.assertEqual(config.portfolio_heat_limit_r, 6.0)
        # No trade_history is supplied (None) -- fail-closed sizing caps
        # every approval at config.fail_closed_tier.base_r regardless of
        # the evidence score's own confidence tier (position_sizing.py).
        # At the default 0.25R this takes exactly 24 leaked approvals to
        # saturate the 6.0R heat limit -- comfortably inside the 5-60
        # trade range this defect was quantified at using this repo's
        # own config defaults across both fail-closed and full-history
        # sizing.
        approved_size_r = config.fail_closed_tier.base_r
        max_approvals_before_saturation = int(config.portfolio_heat_limit_r // approved_size_r) + 2

        # OLD (buggy) behavior: reservations are never released, even
        # though every one of these represents a fully completed,
        # long-closed trade with zero real remaining exposure.
        leaky_engine = RiskEngine(config)
        now = T0
        approvals = 0
        first_false_rejection = None
        for _ in range(max_approvals_before_saturation):
            snapshot = self._approve_one(leaky_engine, now)
            now += timedelta(minutes=1)
            if snapshot.approved:
                approvals += 1
                continue
            first_false_rejection = snapshot
            break
        self.assertIsNotNone(first_false_rejection, "the leak must eventually saturate the heat gate")
        self.assertGreaterEqual(approvals, 1)
        self.assertLess(approvals, max_approvals_before_saturation)
        # Every prior trade in this simulation is fully closed (no
        # OpenPosition supplied) -- this rejection is FALSE: no real
        # exposure justifies it, only leaked reservations.
        self.assertGreater(
            leaky_engine.pending_reservation_total_r(), config.portfolio_heat_limit_r - approved_size_r,
        )

        # FIXED behavior: the exact same sequence, but each trade's
        # reservation is released once its lifecycle resolves (here:
        # immediately, since the simulated trade is already fully closed
        # with no residual exposure -- the realistic case is
        # confirm_position_report()/reconcile()-driven release, proven
        # by tests 3-6 above; this test isolates the ledger-accounting
        # symptom specifically).
        fixed_engine = RiskEngine(config)
        now = T0
        for _ in range(approvals + 1):
            snapshot = self._approve_one(fixed_engine, now)
            now += timedelta(minutes=1)
            self.assertTrue(snapshot.approved, "with proper release, closed trades never falsely saturate the heat gate")
            if snapshot.reservation_id is not None:
                fixed_engine.release_reservation(snapshot.reservation_id)
        self.assertEqual(fixed_engine.pending_reservation_count(), 0)


if __name__ == "__main__":
    unittest.main()
