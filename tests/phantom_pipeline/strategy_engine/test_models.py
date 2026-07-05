"""CandidateTrade immutability and candidate_id determinism (ADR-003 §6)."""

from __future__ import annotations

import dataclasses
import unittest
from datetime import datetime, timezone

from phantom_pipeline.scanner.models import Direction
from phantom_pipeline.strategy_engine.models import CandidateTrade, Evidence, SupportingObservation, make_candidate_id

T0 = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)


def _candidate(**overrides) -> CandidateTrade:
    fields = dict(
        schema_version=1,
        trace_id="obs-trace",
        candidate_id=make_candidate_id("obs-trace", "TEST", "1.0.0"),
        strategy_id="TEST",
        strategy_version="1.0.0",
        symbol="EURUSD",
        timeframe="M1",
        timestamp=T0,
        direction=Direction.UP,
        entry_concept="zone",
        supporting_observations=(SupportingObservation("trend", "up"),),
        evidence=(Evidence("k", "v"),),
        reason_codes=("R1",),
        reasoning="because",
    )
    fields.update(overrides)
    return CandidateTrade(**fields)


class TestCandidateIdDeterminism(unittest.TestCase):
    def test_identical_arguments_produce_identical_id(self):
        a = make_candidate_id("trace-1", "STRAT", "1.0.0")
        b = make_candidate_id("trace-1", "STRAT", "1.0.0")
        self.assertEqual(a, b)

    def test_different_trace_id_produces_different_candidate_id(self):
        a = make_candidate_id("trace-1", "STRAT", "1.0.0")
        b = make_candidate_id("trace-2", "STRAT", "1.0.0")
        self.assertNotEqual(a, b)

    def test_different_disambiguator_produces_different_candidate_id(self):
        a = make_candidate_id("trace-1", "STRAT", "1.0.0", disambiguator="0")
        b = make_candidate_id("trace-1", "STRAT", "1.0.0", disambiguator="1")
        self.assertNotEqual(a, b)

    def test_never_random_or_wall_clock_dependent(self):
        # Same call, twice, must be identical regardless of when it runs.
        first = make_candidate_id("trace-1", "STRAT", "2.0.0")
        second = make_candidate_id("trace-1", "STRAT", "2.0.0")
        self.assertEqual(first, second)


class TestCandidateTradeImmutability(unittest.TestCase):
    def test_top_level_fields_cannot_be_reassigned(self):
        candidate = _candidate()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            candidate.direction = Direction.DOWN  # type: ignore[misc]

    def test_tuple_fields_are_coerced_to_tuples(self):
        candidate = _candidate(
            supporting_observations=[SupportingObservation("trend", "up")],
            evidence=[Evidence("k", "v")],
            reason_codes=["R1", "R2"],
        )
        self.assertIsInstance(candidate.supporting_observations, tuple)
        self.assertIsInstance(candidate.evidence, tuple)
        self.assertIsInstance(candidate.reason_codes, tuple)

    def test_trace_id_preserves_upstream_lineage(self):
        candidate = _candidate(trace_id="scanner-observation-trace-id")
        self.assertEqual(candidate.trace_id, "scanner-observation-trace-id")


if __name__ == "__main__":
    unittest.main()
