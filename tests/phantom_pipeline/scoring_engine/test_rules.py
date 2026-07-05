"""Unit tests for each real scoring rule, in isolation against fixture
CandidateTrades (ADR-004 §14)."""

from __future__ import annotations

import unittest

from phantom_pipeline.scanner.models import Direction
from phantom_pipeline.scoring_engine.config import ScoringEngineConfig
from phantom_pipeline.scoring_engine.models import RuleOutcome
from phantom_pipeline.scoring_engine.rules.directional_clarity import DirectionalClarityRule
from phantom_pipeline.scoring_engine.rules.evidence_count import EvidenceCountRule
from phantom_pipeline.scoring_engine.rules.reason_code_presence import ReasonCodePresenceRule
from phantom_pipeline.scoring_engine.rules.supporting_observation_count import (
    SupportingObservationCountRule,
)
from tests.phantom_pipeline.scoring_engine._fixtures import make_candidate


class TestSupportingObservationCountRule(unittest.TestCase):
    def setUp(self):
        self.rule = SupportingObservationCountRule()
        self.config = ScoringEngineConfig(
            rule_weights={"SUPPORTING_OBSERVATION_COUNT": 2.0}, max_countable_evidence_items=5
        )

    def test_fires_with_points_proportional_to_count(self):
        candidate = make_candidate(n_supporting=3)
        contribution = self.rule.evaluate(candidate, self.config)
        self.assertEqual(contribution.outcome, RuleOutcome.FIRED)
        self.assertEqual(contribution.points, 3 * 2.0)
        self.assertEqual(len(contribution.evidence), 3)

    def test_never_abstains_even_when_empty(self):
        candidate = make_candidate(n_supporting=0)
        contribution = self.rule.evaluate(candidate, self.config)
        self.assertEqual(contribution.outcome, RuleOutcome.FIRED)
        self.assertEqual(contribution.points, 0.0)

    def test_respects_the_configured_cap(self):
        candidate = make_candidate(n_supporting=10)
        config = ScoringEngineConfig(
            rule_weights={"SUPPORTING_OBSERVATION_COUNT": 1.0}, max_countable_evidence_items=3
        )
        contribution = self.rule.evaluate(candidate, config)
        self.assertEqual(contribution.points, 3.0)
        self.assertEqual(len(contribution.evidence), 3)


class TestEvidenceCountRule(unittest.TestCase):
    def setUp(self):
        self.rule = EvidenceCountRule()
        self.config = ScoringEngineConfig(
            rule_weights={"EVIDENCE_COUNT": 1.5}, max_countable_evidence_items=5
        )

    def test_fires_with_points_proportional_to_count(self):
        candidate = make_candidate(n_evidence=2)
        contribution = self.rule.evaluate(candidate, self.config)
        self.assertEqual(contribution.outcome, RuleOutcome.FIRED)
        self.assertEqual(contribution.points, 2 * 1.5)

    def test_never_abstains_even_when_empty(self):
        candidate = make_candidate(n_evidence=0)
        contribution = self.rule.evaluate(candidate, self.config)
        self.assertEqual(contribution.outcome, RuleOutcome.FIRED)
        self.assertEqual(contribution.points, 0.0)


class TestReasonCodePresenceRule(unittest.TestCase):
    def setUp(self):
        self.rule = ReasonCodePresenceRule()
        self.config = ScoringEngineConfig(
            rule_weights={"REASON_CODE_PRESENCE": 3.0}, max_countable_evidence_items=5
        )

    def test_abstains_when_no_reason_codes(self):
        candidate = make_candidate(n_reason=0)
        contribution = self.rule.evaluate(candidate, self.config)
        self.assertEqual(contribution.outcome, RuleOutcome.ABSTAINED)
        self.assertEqual(contribution.points, 0.0)

    def test_fires_with_points_proportional_to_count_when_present(self):
        candidate = make_candidate(n_reason=2)
        contribution = self.rule.evaluate(candidate, self.config)
        self.assertEqual(contribution.outcome, RuleOutcome.FIRED)
        self.assertEqual(contribution.points, 2 * 3.0)


class TestDirectionalClarityRule(unittest.TestCase):
    def setUp(self):
        self.rule = DirectionalClarityRule()
        self.config = ScoringEngineConfig(rule_weights={"DIRECTIONAL_CLARITY": 4.0})

    def test_fires_flat_points_for_up(self):
        contribution = self.rule.evaluate(make_candidate(direction=Direction.UP), self.config)
        self.assertEqual(contribution.outcome, RuleOutcome.FIRED)
        self.assertEqual(contribution.points, 4.0)

    def test_fires_flat_points_for_down(self):
        contribution = self.rule.evaluate(make_candidate(direction=Direction.DOWN), self.config)
        self.assertEqual(contribution.outcome, RuleOutcome.FIRED)
        self.assertEqual(contribution.points, 4.0)

    def test_fires_zero_points_for_neutral(self):
        contribution = self.rule.evaluate(make_candidate(direction=Direction.NEUTRAL), self.config)
        self.assertEqual(contribution.outcome, RuleOutcome.FIRED)
        self.assertEqual(contribution.points, 0.0)

    def test_abstains_for_unknown(self):
        contribution = self.rule.evaluate(make_candidate(direction=Direction.UNKNOWN), self.config)
        self.assertEqual(contribution.outcome, RuleOutcome.ABSTAINED)
        self.assertEqual(contribution.points, 0.0)


class TestRuleWeightSourcedFromConfigNeverHardcoded(unittest.TestCase):
    def test_changing_configured_weight_changes_the_contribution(self):
        candidate = make_candidate(direction=Direction.UP)
        rule = DirectionalClarityRule()

        low = rule.evaluate(candidate, ScoringEngineConfig(rule_weights={"DIRECTIONAL_CLARITY": 1.0}))
        high = rule.evaluate(candidate, ScoringEngineConfig(rule_weights={"DIRECTIONAL_CLARITY": 100.0}))

        self.assertEqual(low.points, 1.0)
        self.assertEqual(high.points, 100.0)


if __name__ == "__main__":
    unittest.main()
