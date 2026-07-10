"""Phase 3B regime validation audit: verifies -- rather than assumes --
exactly how the Risk Engine relates to "market regime," against the
real, frozen `phantom/risk_engine/` and `phantom/strategy_engine/`
source.

Confirmed facts (by reading the source, not inferred):
  - `phantom/risk_engine/` contains the substring "regime" nowhere at
    all, in any of its own files -- a stronger guarantee than "reads
    regime read-only, never recalculates": Risk Engine does not consume
    regime in any form.
  - `WinningStrategy` (the type `StrategySnapshot.winning_strategy`
    holds, which is what Risk Engine's `evaluate()` actually receives)
    carries only `strategy_id` and `qualification` -- `MarketRegime`
    never even reaches the Risk Engine's input surface, let alone its
    computation. The regime a strategy targets lives on
    `StrategyDefinition.market_regime`, a type Risk Engine's `evaluate()`
    signature does not reference.
  - Risk Engine's real confidence model is Evidence Score -> confidence
    tier -> base R (`confidence.py`), entirely independent of regime.
  - `MarketRegime` (`phantom.strategy_engine.models`) has exactly 4
    members -- TRENDING, RANGING, BREAKOUT, REVERSAL -- no `UNKNOWN`
    member exists. "UNKNOWN regime -> REJECT" (this checklist's own
    aspirational requirement) therefore has no literal code path to
    test; it is recorded here as a Known Limitation, not silently added
    to a frozen engine/enum (Phase 3B's own bug policy: no feature
    additions to a frozen engine).

This is documentation enforced as a regression test: if a future change
ever wires regime into Risk Engine's computation, the empirical test
below (two identical-score qualifications differing only in the
regime their strategy targets) will fail.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from phantom.risk_engine.config import RiskEngineConfig
from phantom.risk_engine.engine import RiskEngine
from phantom.risk_engine.models import PortfolioState
from phantom.strategy_engine.models import MarketRegime, QualificationResult, QualificationStatus, StrategyId, StrategySnapshot, WinningStrategy
from tests.phantom.risk_engine._fixtures import T0, make_evidence_snapshot, make_mi_snapshot

RISK_ENGINE_ROOT = Path(__file__).resolve().parents[3] / "phantom" / "risk_engine"


def _snapshot_for(strategy_id: StrategyId) -> StrategySnapshot:
    qualification = QualificationResult(
        strategy_id=strategy_id, pair="EURUSD", status=QualificationStatus.QUALIFIED,
        score=80.0, confidence=0.8, reason="test", strengths=("strong",), weaknesses=(),
    )
    winning = WinningStrategy(strategy_id=strategy_id, qualification=qualification)
    return StrategySnapshot(
        pair="EURUSD", generated_at=T0, winning_strategy=winning, all_qualifications=(qualification,),
        rejected=False, rejection_reason=None,
        supporting_evidence_summary="test", supporting_market_intelligence_summary="test",
    )


class TestRiskEngineNeverReferencesRegime(unittest.TestCase):
    def test_no_source_file_contains_the_word_regime(self):
        offenders = []
        for path in sorted(RISK_ENGINE_ROOT.rglob("*.py")):
            if "regime" in path.read_text().lower():
                offenders.append(str(path.relative_to(RISK_ENGINE_ROOT)))
        self.assertEqual(offenders, [], f"Risk Engine must never reference regime: {offenders}")

    def test_winning_strategy_type_never_carries_market_regime(self):
        """`WinningStrategy` -- the type Risk Engine's `StrategySnapshot`
        input actually contains -- has no field of type `MarketRegime`
        (or named "regime") at all; the regime a strategy targets lives
        only on `StrategyDefinition`, which never reaches Risk Engine."""
        import dataclasses

        field_names = {f.name for f in dataclasses.fields(WinningStrategy)}
        self.assertEqual(field_names, {"strategy_id", "qualification"})
        self.assertFalse(any("regime" in name.lower() for name in field_names))


class TestMarketRegimeHasNoUnknownMember(unittest.TestCase):
    def test_market_regime_has_exactly_four_members(self):
        self.assertEqual({m.name for m in MarketRegime}, {"TRENDING", "RANGING", "BREAKOUT", "REVERSAL"})

    def test_market_regime_has_no_unknown_member(self):
        """Known Limitation: this checklist's "UNKNOWN regime -> REJECT"
        requirement has no literal code path -- there is no UNKNOWN
        member to ever construct."""
        self.assertNotIn("UNKNOWN", {m.name for m in MarketRegime})


class TestRiskDecisionIsInvariantToTargetedRegime(unittest.TestCase):
    """Empirical proof, not just a source-code grep: two strategies
    targeting different regimes (TRENDING vs. RANGING vs. BREAKOUT vs.
    REVERSAL), given an identical qualification score/confidence, drive
    Risk Engine to an identical decision."""

    def _decide(self, strategy_id: StrategyId):
        engine = RiskEngine(RiskEngineConfig())  # fresh ledger each time -- identical reservation counters
        return engine.evaluate(
            "EURUSD", make_evidence_snapshot(), make_mi_snapshot(), _snapshot_for(strategy_id),
            PortfolioState(), None, T0,
        )

    def test_trending_and_ranging_targeted_strategies_produce_identical_risk_decisions(self):
        trending = self._decide(StrategyId.TREND_CONTINUATION)  # targets MarketRegime.TRENDING
        ranging = self._decide(StrategyId.RANGE_REVERSAL)  # targets MarketRegime.RANGING
        self.assertEqual(trending.approved, ranging.approved)
        self.assertEqual(trending.approved_risk_r, ranging.approved_risk_r)
        self.assertEqual(trending.confidence_tier, ranging.confidence_tier)
        self.assertEqual(trending.recommended_position_size, ranging.recommended_position_size)

    def test_all_four_targeted_regimes_produce_the_same_approved_risk(self):
        by_strategy = {
            StrategyId.TREND_CONTINUATION: MarketRegime.TRENDING,
            StrategyId.RANGE_REVERSAL: MarketRegime.RANGING,
            StrategyId.SESSION_BREAKOUT: MarketRegime.BREAKOUT,
            StrategyId.LIQUIDITY_SWEEP_MSS: MarketRegime.REVERSAL,
        }
        results = {strategy_id: self._decide(strategy_id) for strategy_id in by_strategy}
        approved_risk_values = {r.approved_risk_r for r in results.values()}
        self.assertEqual(len(approved_risk_values), 1, f"regime-dependent risk detected: {results}")


if __name__ == "__main__":
    unittest.main()
