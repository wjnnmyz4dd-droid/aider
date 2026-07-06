"""BullBearDebateAgent tests — bull/bear/neutral thesis, transparent
confidence scoring, and the structural never-a-signal guarantee
(ADR-021 item 2, Hard Rule 6)."""

from __future__ import annotations

import dataclasses
import unittest

from phantom_pipeline.research_desk.debate import BullBearDebateAgent
from phantom_pipeline.research_desk.models import DebateStance, DebateThesis, ThesisCase
from phantom_pipeline.scanner.models import Direction, MarketPhase, StructureTrendState, SwingSequenceType

from tests.phantom_pipeline.research_desk._fixtures import NOW, make_scanner_observation


class TestGenerateThesis(unittest.TestCase):
    def test_all_bullish_signals_yield_high_bullish_confidence(self):
        obs = make_scanner_observation(phase=MarketPhase.MARKUP)
        thesis = BullBearDebateAgent().generate_thesis("r1", "EURUSD", obs, NOW)

        self.assertGreater(thesis.confidence_score, 0.5)
        self.assertIn("bullish", thesis.final_summary.lower())
        self.assertTrue(thesis.bullish_case.supporting_evidence)

    def test_bearish_phase_yields_bearish_leaning_thesis(self):
        obs_bearish_fields = make_scanner_observation(phase=MarketPhase.MARKDOWN)
        obs = dataclasses.replace(
            obs_bearish_fields,
            external_structure=StructureTrendState(Direction.DOWN, SwingSequenceType.LOWER_HIGHS_LOWER_LOWS),
            internal_structure=StructureTrendState(Direction.DOWN, SwingSequenceType.LOWER_HIGHS_LOWER_LOWS),
        )
        thesis = BullBearDebateAgent().generate_thesis("r1", "EURUSD", obs, NOW)

        self.assertIn("bearish", thesis.final_summary.lower())
        self.assertTrue(thesis.bearish_case.supporting_evidence)

    def test_no_signals_yields_zero_confidence_and_neutral_case(self):
        obs = dataclasses.replace(
            make_scanner_observation(phase=MarketPhase.UNKNOWN),
            external_structure=StructureTrendState(Direction.UNKNOWN, SwingSequenceType.INSUFFICIENT_DATA),
            internal_structure=StructureTrendState(Direction.UNKNOWN, SwingSequenceType.INSUFFICIENT_DATA),
            trend={},
        )
        thesis = BullBearDebateAgent().generate_thesis("r1", "EURUSD", obs, NOW)

        self.assertEqual(thesis.confidence_score, 0.0)
        self.assertIn("not a trading signal", thesis.final_summary)

    def test_thesis_is_deterministic(self):
        obs = make_scanner_observation(phase=MarketPhase.MARKUP)
        thesis_a = BullBearDebateAgent().generate_thesis("r1", "EURUSD", obs, NOW)
        thesis_b = BullBearDebateAgent().generate_thesis("r1", "EURUSD", obs, NOW)
        self.assertEqual(thesis_a, thesis_b)

    def test_symbol_and_report_id_propagated(self):
        obs = make_scanner_observation(phase=MarketPhase.MARKUP)
        thesis = BullBearDebateAgent().generate_thesis("report-42", "GBPUSD", obs, NOW)
        self.assertEqual(thesis.symbol, "GBPUSD")
        self.assertEqual(thesis.report_id, "report-42")

    def test_tied_signals_yield_neutral_stance(self):
        obs = dataclasses.replace(
            make_scanner_observation(phase=MarketPhase.UNKNOWN),
            external_structure=StructureTrendState(Direction.UP, SwingSequenceType.HIGHER_HIGHS_HIGHER_LOWS),
            internal_structure=StructureTrendState(Direction.DOWN, SwingSequenceType.LOWER_HIGHS_LOWER_LOWS),
            trend={},
        )
        thesis = BullBearDebateAgent().generate_thesis("r1", "EURUSD", obs, NOW)
        self.assertIn("neutral", thesis.final_summary.lower())


class TestNeverATradingSignal(unittest.TestCase):
    """ADR-021 Hard Rule 6, verified structurally."""

    def test_debate_thesis_has_no_signal_shaped_field(self):
        forbidden = ("direction", "lot_size", "entry_price", "stop_loss", "take_profit", "size")
        for f in dataclasses.fields(DebateThesis):
            self.assertNotIn(f.name, forbidden)

    def test_thesis_case_has_no_signal_shaped_field(self):
        forbidden = ("direction", "lot_size", "entry_price", "stop_loss", "take_profit", "size")
        for f in dataclasses.fields(ThesisCase):
            self.assertNotIn(f.name, forbidden)

    def test_confidence_score_bounded_zero_to_one(self):
        obs = make_scanner_observation(phase=MarketPhase.MARKUP)
        thesis = BullBearDebateAgent().generate_thesis("r1", "EURUSD", obs, NOW)
        self.assertGreaterEqual(thesis.confidence_score, 0.0)
        self.assertLessEqual(thesis.confidence_score, 1.0)


if __name__ == "__main__":
    unittest.main()
