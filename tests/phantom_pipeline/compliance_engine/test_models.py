"""Boundary/type-level and immutability tests (ADR-006 §4, §18)."""

from __future__ import annotations

import dataclasses
import unittest

from phantom_pipeline.compliance_engine.models import (
    AccountState,
    CheckEvaluation,
    CheckStatus,
    ComplianceDecision,
    NewsCalendarState,
    OpenPosition,
    Verdict,
)
from phantom_pipeline.scanner.models import Direction
from tests.phantom_pipeline.compliance_engine._fixtures import T0


FORBIDDEN_FIELD_NAME_FRAGMENTS = (
    "lot_size",
    "stop_loss",
    "take_profit",
    "score",
    "order",
    "execution",
    "position_size",
    "sl",
    "tp",
)


def _make_decision(verdict: Verdict = Verdict.APPROVE) -> ComplianceDecision:
    return ComplianceDecision(
        schema_version=1,
        trace_id="t1",
        candidate_id="c1",
        strategy_id="S1",
        symbol="EURUSD",
        timeframe="M1",
        timestamp=T0,
        direction=Direction.UP,
        verdict=verdict,
        blocking_rules=(),
        reason_codes=("nominal",),
        check_evaluations=(CheckEvaluation("KILL_SWITCH", CheckStatus.PASSED, "ok"),),
        compliance_engine_version="1.0.0-phase1",
    )


class TestComplianceDecisionImmutability(unittest.TestCase):
    def test_top_level_fields_cannot_be_reassigned(self):
        decision = _make_decision()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            decision.verdict = Verdict.BLOCK  # type: ignore[misc]

    def test_check_evaluations_coerced_to_tuple(self):
        decision = _make_decision()
        self.assertIsInstance(decision.check_evaluations, tuple)

    def test_check_evaluation_is_immutable(self):
        evaluation = CheckEvaluation("KILL_SWITCH", CheckStatus.PASSED, "ok")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            evaluation.status = CheckStatus.FAILED  # type: ignore[misc]


class TestCheckEvaluationBlocks(unittest.TestCase):
    def test_passed_does_not_block(self):
        self.assertFalse(CheckEvaluation("X", CheckStatus.PASSED, "").blocks)

    def test_failed_blocks(self):
        self.assertTrue(CheckEvaluation("X", CheckStatus.FAILED, "").blocks)

    def test_unevaluable_blocks(self):
        self.assertTrue(CheckEvaluation("X", CheckStatus.UNEVALUABLE, "").blocks)


class TestBoundaryTypeLevel(unittest.TestCase):
    """`ComplianceDecision` is structurally incapable of holding a
    forbidden field (ADR-006 §4)."""

    def test_no_forbidden_field_names_on_compliance_decision(self):
        field_names = {f.name for f in dataclasses.fields(ComplianceDecision)}
        for fragment in FORBIDDEN_FIELD_NAME_FRAGMENTS:
            for name in field_names:
                self.assertNotIn(
                    fragment,
                    name,
                    f"forbidden fragment '{fragment}' found in field '{name}'",
                )

    def test_no_forbidden_field_names_on_check_evaluation(self):
        field_names = {f.name for f in dataclasses.fields(CheckEvaluation)}
        for fragment in FORBIDDEN_FIELD_NAME_FRAGMENTS:
            for name in field_names:
                self.assertNotIn(fragment, name)


class TestAccountState(unittest.TestCase):
    def test_open_positions_coerced_to_tuple(self):
        state = AccountState(
            equity=1.0,
            balance=1.0,
            daily_drawdown_pct=0.0,
            total_drawdown_pct=0.0,
            open_positions=[OpenPosition("EURUSD", Direction.UP)],
        )
        self.assertIsInstance(state.open_positions, tuple)

    def test_frozen(self):
        state = AccountState(
            equity=1.0, balance=1.0, daily_drawdown_pct=0.0, total_drawdown_pct=0.0, open_positions=()
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            state.equity = 2.0  # type: ignore[misc]


class TestNewsCalendarState(unittest.TestCase):
    def test_blackout_windows_coerced_to_tuple(self):
        state = NewsCalendarState(feed_stale=False, blackout_windows=[])
        self.assertIsInstance(state.blackout_windows, tuple)


if __name__ == "__main__":
    unittest.main()
