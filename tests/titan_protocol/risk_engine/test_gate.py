"""Unit tests: the 65-point evidence hard gate (ADR-027 Hard Rule 1)."""

from __future__ import annotations

import unittest

from titan_protocol.risk_engine.gate import check_evidence_gate
from titan_protocol.risk_engine.models import RejectionReason
from tests.titan_protocol.risk_engine._fixtures import make_config, make_evidence_snapshot


class TestEvidenceGate(unittest.TestCase):
    def test_below_threshold_rejects(self):
        config = make_config()
        evidence = make_evidence_snapshot(evidence_score=64.999)
        self.assertEqual(check_evidence_gate(evidence, config), RejectionReason.INSUFFICIENT_EVIDENCE)

    def test_at_threshold_passes(self):
        config = make_config()
        evidence = make_evidence_snapshot(evidence_score=65.0)
        self.assertIsNone(check_evidence_gate(evidence, config))

    def test_above_threshold_passes(self):
        config = make_config()
        evidence = make_evidence_snapshot(evidence_score=99.9)
        self.assertIsNone(check_evidence_gate(evidence, config))

    def test_zero_score_rejects(self):
        config = make_config()
        evidence = make_evidence_snapshot(evidence_score=0.0)
        self.assertEqual(check_evidence_gate(evidence, config), RejectionReason.INSUFFICIENT_EVIDENCE)

    def test_configurable_threshold(self):
        config = make_config(minimum_evidence_score=80.0)
        evidence = make_evidence_snapshot(evidence_score=70.0)
        self.assertEqual(check_evidence_gate(evidence, config), RejectionReason.INSUFFICIENT_EVIDENCE)
        evidence_high = make_evidence_snapshot(evidence_score=80.0)
        self.assertIsNone(check_evidence_gate(evidence_high, config))


if __name__ == "__main__":
    unittest.main()
