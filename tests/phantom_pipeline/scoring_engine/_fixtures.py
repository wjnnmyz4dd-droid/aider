"""Shared test-only fixtures for the Scoring Engine test suite."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Tuple

from phantom_pipeline.scanner.models import Direction
from phantom_pipeline.scoring_engine.config import ScoringEngineConfig
from phantom_pipeline.scoring_engine.models import RuleContribution, RuleOutcome
from phantom_pipeline.scoring_engine.rule import ScoringRule, ScoringRuleMetadata
from phantom_pipeline.strategy_engine.models import (
    CandidateTrade,
    Evidence,
    SupportingObservation,
    make_candidate_id,
)

T0 = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)
SYMBOL = "EURUSD"
TIMEFRAME = "M1"


def make_candidate(
    strategy_id: str = "TEST_STRATEGY",
    direction: Direction = Direction.UP,
    n_evidence: int = 2,
    n_supporting: int = 2,
    n_reason: int = 1,
    trace_id: str = "obs-trace-1",
    symbol: str = SYMBOL,
    schema_version: int = 1,
) -> CandidateTrade:
    return CandidateTrade(
        schema_version=schema_version,
        trace_id=trace_id,
        candidate_id=make_candidate_id(trace_id, strategy_id, "1.0.0"),
        strategy_id=strategy_id,
        strategy_version="1.0.0",
        symbol=symbol,
        timeframe=TIMEFRAME,
        timestamp=T0,
        direction=direction,
        entry_concept="fixture entry zone",
        supporting_observations=tuple(
            SupportingObservation("trend", f"detail-{i}") for i in range(n_supporting)
        ),
        evidence=tuple(Evidence(f"key-{i}", f"value-{i}") for i in range(n_evidence)),
        reason_codes=tuple(f"REASON_{i}" for i in range(n_reason)),
        reasoning="fixture reasoning",
    )


def enabled_config(*rule_ids: str, **overrides) -> ScoringEngineConfig:
    return ScoringEngineConfig(enabled_rules={rid: True for rid in rule_ids}, **overrides)


class FlatPointsRule(ScoringRule):
    """Test fixture: always fires with a flat weight-sized contribution."""

    _METADATA = ScoringRuleMetadata("TEST_FLAT", "1.0.0", "test fixture", "test_factor")

    @property
    def metadata(self) -> ScoringRuleMetadata:
        return self._METADATA

    def evaluate(self, candidate, config) -> RuleContribution:
        weight = config.weight_for(self._METADATA.rule_id)
        return RuleContribution(
            rule_id=self._METADATA.rule_id,
            rule_version=self._METADATA.version,
            outcome=RuleOutcome.FIRED,
            points=weight,
            weight=weight,
            evidence=(),
            detail="flat contribution",
        )


class AlwaysAbstainsRule(ScoringRule):
    """Test fixture: always abstains — simulates a genuinely-missing
    required input."""

    _METADATA = ScoringRuleMetadata("TEST_ABSTAINS", "1.0.0", "test fixture", "test_factor")

    @property
    def metadata(self) -> ScoringRuleMetadata:
        return self._METADATA

    def evaluate(self, candidate, config) -> RuleContribution:
        weight = config.weight_for(self._METADATA.rule_id)
        return RuleContribution(
            rule_id=self._METADATA.rule_id,
            rule_version=self._METADATA.version,
            outcome=RuleOutcome.ABSTAINED,
            points=0.0,
            weight=weight,
            evidence=(),
            detail="required input absent",
        )


class ExplodingRule(ScoringRule):
    """A true implementation-bug simulator (ADR-004 §8) — always raises."""

    _METADATA = ScoringRuleMetadata("TEST_EXPLODES", "1.0.0", "test fixture", "test_factor")

    @property
    def metadata(self) -> ScoringRuleMetadata:
        return self._METADATA

    def evaluate(self, candidate, config) -> RuleContribution:
        raise RuntimeError("simulated scoring rule implementation bug")
