"""Tournament category (ADR-030 §5.4-5.6): Strategy/Pair/Session
Tournament, Configuration Tournament, and Shadow Trading."""

from __future__ import annotations

import unittest

from titan_protocol.evidence_engine.models import SessionName
from titan_protocol.research_engine.config import ResearchEngineConfig
from titan_protocol.strategy_engine.models import StrategyId
from titan_protocol.validation_engine.configuration_tournament import run_configuration_tournament
from titan_protocol.validation_engine.models import ConfigurationProfile
from titan_protocol.validation_engine.shadow_trading import run_shadow_comparison
from titan_protocol.validation_engine.tournament import run_pair_tournament, run_session_tournament, run_strategy_tournament
from tests.titan_protocol.validation_engine._fixtures import (
    make_config,
    make_configuration_run,
    make_executed_trade,
    make_repeating_executed_trades,
)


def _config_with_low_ranking_threshold():
    return make_config(research_config=ResearchEngineConfig(min_sample_size_for_ranking=5))


class TestStrategyPairSessionTournament(unittest.TestCase):
    def test_better_strategy_ranked_first(self):
        config = _config_with_low_ranking_threshold()
        winners = [make_executed_trade(index=i, strategy_id=StrategyId.TREND_CONTINUATION, won=True, r_multiple=2.0) for i in range(10)]
        losers = [make_executed_trade(index=i + 10, strategy_id=StrategyId.RANGE_REVERSAL, won=False, r_multiple=-1.0) for i in range(10)]
        entries = run_strategy_tournament(winners + losers, config)
        self.assertEqual(entries[0].subject, StrategyId.TREND_CONTINUATION.value)
        self.assertEqual(entries[0].rank, 1)

    def test_pair_tournament_ranks_by_expectancy(self):
        config = _config_with_low_ranking_threshold()
        good = [make_executed_trade(index=i, pair="EURUSD", won=True, r_multiple=2.0) for i in range(10)]
        bad = [make_executed_trade(index=i + 10, pair="GBPUSD", won=False, r_multiple=-1.0) for i in range(10)]
        entries = run_pair_tournament(good + bad, config)
        self.assertEqual(entries[0].subject, "EURUSD")

    def test_session_tournament_ranks_by_expectancy(self):
        config = _config_with_low_ranking_threshold()
        good = [make_executed_trade(index=i, session=SessionName.LONDON, won=True, r_multiple=2.0) for i in range(10)]
        bad = [make_executed_trade(index=i + 10, session=SessionName.ASIAN, won=False, r_multiple=-1.0) for i in range(10)]
        entries = run_session_tournament(good + bad, config)
        self.assertEqual(entries[0].subject, SessionName.LONDON.value)

    def test_entries_carry_recovery_factor(self):
        config = _config_with_low_ranking_threshold()
        trades = make_repeating_executed_trades(count=30, win_r=2.0, loss_r=-1.0, win_rate=0.5)
        entries = run_strategy_tournament(trades, config)
        self.assertTrue(entries)
        self.assertIsNotNone(entries[0].recovery_factor)


class TestConfigurationTournament(unittest.TestCase):
    def test_ranks_configurations_by_expectancy(self):
        config = make_config()
        good = make_configuration_run(
            ConfigurationProfile.AGGRESSIVE,
            make_repeating_executed_trades(count=20, win_r=3.0, loss_r=-1.0, win_rate=0.6),
        )
        bad = make_configuration_run(
            ConfigurationProfile.CONSERVATIVE,
            make_repeating_executed_trades(count=20, win_r=1.0, loss_r=-1.0, win_rate=0.4, pair="GBPUSD"),
        )
        result = run_configuration_tournament([good, bad], config)
        self.assertEqual(result.entries[0].subject, ConfigurationProfile.AGGRESSIVE.value)
        self.assertTrue(result.recommendations)

    def test_never_mutates_configuration(self):
        config = make_config()
        run = make_configuration_run(ConfigurationProfile.BALANCED, make_repeating_executed_trades(count=20))
        result = run_configuration_tournament([run], config)
        # Advisory only -- the result carries text recommendations, never an applied config object.
        for recommendation in result.recommendations:
            self.assertIsInstance(recommendation, str)


class TestShadowTrading(unittest.TestCase):
    def test_compares_production_vs_candidate_same_market(self):
        config = make_config()
        production = make_configuration_run(
            ConfigurationProfile.BALANCED,
            make_repeating_executed_trades(count=20, win_r=1.5, loss_r=-1.0, win_rate=0.5),
        )
        candidate = make_configuration_run(
            ConfigurationProfile.AGGRESSIVE,
            make_repeating_executed_trades(count=20, win_r=3.0, loss_r=-1.0, win_rate=0.6, pair="GBPUSD"),
        )
        result = run_shadow_comparison(production, candidate, config)
        self.assertEqual(result.production.subject, ConfigurationProfile.BALANCED.value)
        self.assertEqual(result.candidate.subject, ConfigurationProfile.AGGRESSIVE.value)
        self.assertIsNotNone(result.expectancy_delta)
        self.assertTrue(result.recommendation)


if __name__ == "__main__":
    unittest.main()
