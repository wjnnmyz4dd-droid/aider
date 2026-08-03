"""The 5 reserved ADR-003 §8 placeholder playbooks: reserved Strategy IDs
only, zero hypothesis logic, always abstain."""

from __future__ import annotations

import unittest

from phantom_pipeline.strategy_engine.playbooks.liquidity_reversal import LiquidityReversalPlaybook
from phantom_pipeline.strategy_engine.playbooks.orb import ORBPlaybook
from phantom_pipeline.strategy_engine.playbooks.range_reversal import RangeReversalPlaybook
from phantom_pipeline.strategy_engine.playbooks.session_breakout import SessionBreakoutPlaybook
from phantom_pipeline.strategy_engine.playbooks.trend_continuation import TrendContinuationPlaybook
from tests.phantom_pipeline.strategy_engine._fixtures import nominal_observation

_PLAYBOOK_CLASSES = [
    ORBPlaybook,
    LiquidityReversalPlaybook,
    SessionBreakoutPlaybook,
    TrendContinuationPlaybook,
    RangeReversalPlaybook,
]

_EXPECTED_IDS = {
    "ORB",
    "LIQUIDITY_REVERSAL",
    "SESSION_BREAKOUT",
    "TREND_CONTINUATION",
    "RANGE_REVERSAL",
}


class TestReservedPlaceholders(unittest.TestCase):
    def test_exactly_the_five_adr_003_section_8_ids_are_reserved(self):
        ids = {cls().metadata.strategy_id for cls in _PLAYBOOK_CLASSES}
        self.assertEqual(ids, _EXPECTED_IDS)

    def test_every_placeholder_always_abstains(self):
        observation = nominal_observation()
        for cls in _PLAYBOOK_CLASSES:
            instance = cls()
            result = instance.evaluate(observation, config=None)
            self.assertEqual(result, (), f"{cls.__name__} produced a candidate")

    def test_every_placeholder_declares_no_supported_symbols_or_timeframes(self):
        for cls in _PLAYBOOK_CLASSES:
            metadata = cls().metadata
            self.assertEqual(metadata.supported_symbols, ())
            self.assertEqual(metadata.supported_timeframes, ())

    def test_every_placeholder_reports_disabled_when_unconfigured(self):
        from phantom_pipeline.strategy_engine.config import StrategyEngineConfig
        from phantom_pipeline.strategy_engine.playbook import HealthStatus

        config = StrategyEngineConfig()
        for cls in _PLAYBOOK_CLASSES:
            instance = cls()
            self.assertEqual(instance.health_status(config), HealthStatus.DISABLED)


if __name__ == "__main__":
    unittest.main()
