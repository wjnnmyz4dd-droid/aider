"""Boundary/type-level and immutability tests (ADR-007 §4, §12)."""

from __future__ import annotations

import dataclasses
import unittest

from phantom_pipeline.execution_validator.models import (
    AccountState,
    BrokerState,
    CheckEvaluation,
    CheckStatus,
    ExecutionDecision,
    Verdict,
)
from phantom_pipeline.scanner.models import Direction
from tests.phantom_pipeline.execution_validator._fixtures import T0

FORBIDDEN_FIELD_NAME_FRAGMENTS = (
    "lot_size",
    "score",
    "risk_percent",
    "risk_amount",
    "order_instruction",
    "position_size",
)


def _make_decision(verdict: Verdict = Verdict.APPROVE) -> ExecutionDecision:
    return ExecutionDecision(
        schema_version=1,
        trace_id="t1",
        candidate_id="c1",
        strategy_id="S1",
        symbol="EURUSD",
        timeframe="M1",
        timestamp=T0,
        direction=Direction.UP,
        verdict=verdict,
        blocking_reasons=(),
        reason_codes=("nominal",),
        warnings=(),
        check_evaluations=(CheckEvaluation("MARKET_OPEN", CheckStatus.PASSED, "ok"),),
        execution_validator_version="1.0.0-phase1",
    )


class TestExecutionDecisionImmutability(unittest.TestCase):
    def test_top_level_fields_cannot_be_reassigned(self):
        decision = _make_decision()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            decision.verdict = Verdict.REJECT  # type: ignore[misc]

    def test_check_evaluations_coerced_to_tuple(self):
        decision = _make_decision()
        self.assertIsInstance(decision.check_evaluations, tuple)

    def test_check_evaluation_is_immutable(self):
        evaluation = CheckEvaluation("MARKET_OPEN", CheckStatus.PASSED, "ok")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            evaluation.status = CheckStatus.FAILED  # type: ignore[misc]


class TestCheckEvaluationBlocks(unittest.TestCase):
    def test_passed_does_not_block(self):
        self.assertFalse(CheckEvaluation("X", CheckStatus.PASSED, "").blocks)

    def test_failed_blocks(self):
        self.assertTrue(CheckEvaluation("X", CheckStatus.FAILED, "").blocks)

    def test_unevaluable_blocks(self):
        self.assertTrue(CheckEvaluation("X", CheckStatus.UNEVALUABLE, "").blocks)

    def test_warning_does_not_affect_blocking(self):
        self.assertFalse(CheckEvaluation("X", CheckStatus.PASSED, "", warning="close to threshold").blocks)


class TestBoundaryTypeLevel(unittest.TestCase):
    """`ExecutionDecision` is structurally incapable of holding a
    forbidden field (ADR-007 §4)."""

    def test_no_forbidden_field_names_on_execution_decision(self):
        field_names = {f.name for f in dataclasses.fields(ExecutionDecision)}
        for fragment in FORBIDDEN_FIELD_NAME_FRAGMENTS:
            for name in field_names:
                self.assertNotIn(fragment, name, f"forbidden fragment '{fragment}' found in field '{name}'")

    def test_no_forbidden_field_names_on_check_evaluation(self):
        field_names = {f.name for f in dataclasses.fields(CheckEvaluation)}
        for fragment in FORBIDDEN_FIELD_NAME_FRAGMENTS:
            for name in field_names:
                self.assertNotIn(fragment, name)


class TestAccountStateAndBrokerState(unittest.TestCase):
    def test_account_state_frozen(self):
        state = AccountState(equity=1.0, available_margin=1.0)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            state.equity = 2.0  # type: ignore[misc]

    def test_broker_state_frozen(self):
        state = BrokerState(connected=True, symbol_tradable=True)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            state.connected = False  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
