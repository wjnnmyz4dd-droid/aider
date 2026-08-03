"""Shared test-only fixtures for the Strategy Engine test suite.

These playbooks are deliberately **not** part of
`phantom_pipeline.strategy_engine.playbooks` (the real, auto-discovered,
production package) — they exist only to exercise the engine's mechanics
(multi-candidate handling, conflict handling, failure isolation,
insufficient-data handling) without implementing any of ADR-003 §8's
reserved, out-of-scope playbook logic. Mirrors how Scanner's own test
suite uses fixture bars rather than real market data.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Tuple

from phantom_pipeline.data_pipeline.models import (
    DataQuality,
    MarketSnapshot,
    NormalizedBar,
    SCHEMA_VERSION as PIPELINE_SCHEMA_VERSION,
)
from phantom_pipeline.scanner import Scanner, ScannerConfig
from phantom_pipeline.scanner.models import Direction, SCHEMA_VERSION as SCANNER_SCHEMA_VERSION
from phantom_pipeline.strategy_engine.config import StrategyEngineConfig
from phantom_pipeline.strategy_engine.models import CandidateTrade, Evidence, SupportingObservation, make_candidate_id
from phantom_pipeline.strategy_engine.playbook import HealthStatus, Playbook, PlaybookMetadata

T0 = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)
SYMBOL = "EURUSD"
TIMEFRAME = "M1"


def _bar(i: int, price: float) -> NormalizedBar:
    return NormalizedBar(
        schema_version=PIPELINE_SCHEMA_VERSION,
        trace_id=f"b{i}",
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        timestamp=T0 + timedelta(minutes=i),
        open=price,
        high=price + 0.001,
        low=price - 0.001,
        close=price,
        volume=1.0,
        quality=DataQuality.NOMINAL,
        is_repaired=False,
        source="test",
    )


def nominal_observation(bar_count: int = 120):
    """A NOMINAL-quality `ScannerObservation`, built through a real
    `Scanner.scan()` call (not hand-constructed) so it reflects real
    Scanner behavior."""
    bars = [_bar(i, 1.1000 + (i % 20) * 0.0002) for i in range(bar_count)]
    snapshot = MarketSnapshot(
        schema_version=PIPELINE_SCHEMA_VERSION,
        trace_id="snap",
        symbol=SYMBOL,
        timestamp=bars[-1].timestamp,
        price=1.1,
        spread=0.0002,
        market_status="OPEN",
    )
    return Scanner(ScannerConfig()).scan(SYMBOL, {TIMEFRAME: bars}, snapshot, bars[-1].timestamp, TIMEFRAME)


def warm_up_observation():
    """A WARM_UP-quality (non-NOMINAL) `ScannerObservation`."""
    bars = [_bar(i, 1.1000) for i in range(3)]
    return Scanner(ScannerConfig()).scan(SYMBOL, {TIMEFRAME: bars}, None, bars[-1].timestamp, TIMEFRAME)


def enabled_config(*strategy_ids: str) -> StrategyEngineConfig:
    return StrategyEngineConfig(enabled_playbooks={sid: True for sid in strategy_ids})


class AlwaysUpPlaybook(Playbook):
    _METADATA = PlaybookMetadata(
        strategy_id="TEST_ALWAYS_UP",
        version="1.0.0",
        description="Test fixture: always proposes an UP hypothesis.",
        supported_symbols=(SYMBOL,),
        supported_timeframes=(TIMEFRAME,),
        schema_versions_supported=(SCANNER_SCHEMA_VERSION,),
    )

    @property
    def metadata(self) -> PlaybookMetadata:
        return self._METADATA

    def evaluate(self, observation, config) -> Tuple[CandidateTrade, ...]:
        strategy_id = self._METADATA.strategy_id
        return (
            CandidateTrade(
                schema_version=1,
                trace_id=observation.trace_id,
                candidate_id=make_candidate_id(observation.trace_id, strategy_id, self._METADATA.version),
                strategy_id=strategy_id,
                strategy_version=self._METADATA.version,
                symbol=observation.symbol,
                timeframe=TIMEFRAME,
                timestamp=observation.timestamp,
                direction=Direction.UP,
                entry_concept="test fixture entry zone",
                supporting_observations=(SupportingObservation("volatility", "fixture reference"),),
                evidence=(Evidence("fixture_key", "fixture_value"),),
                reason_codes=("TEST_UP",),
                reasoning="Test fixture always hypothesizes UP.",
            ),
        )


class AlwaysDownPlaybook(Playbook):
    _METADATA = PlaybookMetadata(
        strategy_id="TEST_ALWAYS_DOWN",
        version="1.0.0",
        description="Test fixture: always proposes a DOWN hypothesis.",
        supported_symbols=(SYMBOL,),
        supported_timeframes=(TIMEFRAME,),
        schema_versions_supported=(SCANNER_SCHEMA_VERSION,),
    )

    @property
    def metadata(self) -> PlaybookMetadata:
        return self._METADATA

    def evaluate(self, observation, config) -> Tuple[CandidateTrade, ...]:
        strategy_id = self._METADATA.strategy_id
        return (
            CandidateTrade(
                schema_version=1,
                trace_id=observation.trace_id,
                candidate_id=make_candidate_id(observation.trace_id, strategy_id, self._METADATA.version),
                strategy_id=strategy_id,
                strategy_version=self._METADATA.version,
                symbol=observation.symbol,
                timeframe=TIMEFRAME,
                timestamp=observation.timestamp,
                direction=Direction.DOWN,
                entry_concept="test fixture entry zone",
                supporting_observations=(),
                evidence=(),
                reason_codes=("TEST_DOWN",),
                reasoning="Test fixture always hypothesizes DOWN.",
            ),
        )


class MultiCandidatePlaybook(Playbook):
    _METADATA = PlaybookMetadata(
        strategy_id="TEST_MULTI",
        version="1.0.0",
        description="Test fixture: always proposes two hypotheses in one call.",
        supported_symbols=(SYMBOL,),
        supported_timeframes=(TIMEFRAME,),
        schema_versions_supported=(SCANNER_SCHEMA_VERSION,),
    )

    @property
    def metadata(self) -> PlaybookMetadata:
        return self._METADATA

    def evaluate(self, observation, config) -> Tuple[CandidateTrade, ...]:
        strategy_id = self._METADATA.strategy_id
        return tuple(
            CandidateTrade(
                schema_version=1,
                trace_id=observation.trace_id,
                candidate_id=make_candidate_id(
                    observation.trace_id, strategy_id, self._METADATA.version, disambiguator=str(i)
                ),
                strategy_id=strategy_id,
                strategy_version=self._METADATA.version,
                symbol=observation.symbol,
                timeframe=TIMEFRAME,
                timestamp=observation.timestamp,
                direction=direction,
                entry_concept=f"fixture zone {i}",
                supporting_observations=(),
                evidence=(),
                reason_codes=("TEST_MULTI",),
                reasoning=f"Test fixture candidate #{i}.",
            )
            for i, direction in enumerate((Direction.UP, Direction.DOWN))
        )


class RequiresTrendPlaybook(Playbook):
    """Demonstrates §5/§15's required-input discipline: abstains (returns
    `()`) rather than crashing or guessing when its required field is
    absent or not nominal."""

    _METADATA = PlaybookMetadata(
        strategy_id="TEST_REQUIRES_TREND",
        version="1.0.0",
        description="Test fixture: requires a nominal M1 trend reading.",
        supported_symbols=(SYMBOL,),
        supported_timeframes=(TIMEFRAME,),
        schema_versions_supported=(SCANNER_SCHEMA_VERSION,),
    )

    @property
    def metadata(self) -> PlaybookMetadata:
        return self._METADATA

    def evaluate(self, observation, config) -> Tuple[CandidateTrade, ...]:
        reading = observation.trend.get(TIMEFRAME)
        if reading is None or reading.direction == Direction.UNKNOWN:
            return ()

        strategy_id = self._METADATA.strategy_id
        return (
            CandidateTrade(
                schema_version=1,
                trace_id=observation.trace_id,
                candidate_id=make_candidate_id(observation.trace_id, strategy_id, self._METADATA.version),
                strategy_id=strategy_id,
                strategy_version=self._METADATA.version,
                symbol=observation.symbol,
                timeframe=TIMEFRAME,
                timestamp=observation.timestamp,
                direction=reading.direction,
                entry_concept="trend-following fixture zone",
                supporting_observations=(SupportingObservation("trend", str(reading.direction)),),
                evidence=(),
                reason_codes=("TEST_TREND",),
                reasoning="Test fixture follows the M1 trend reading.",
            ),
        )


class ExplodingPlaybook(Playbook):
    """A true implementation-bug simulator (ADR-003 §10) — always raises."""

    _METADATA = PlaybookMetadata(
        strategy_id="TEST_EXPLODES",
        version="1.0.0",
        description="Test fixture: always raises, to test failure isolation.",
        supported_symbols=(SYMBOL,),
        supported_timeframes=(TIMEFRAME,),
        schema_versions_supported=(SCANNER_SCHEMA_VERSION,),
    )

    @property
    def metadata(self) -> PlaybookMetadata:
        return self._METADATA

    def evaluate(self, observation, config) -> Tuple[CandidateTrade, ...]:
        raise RuntimeError("simulated playbook implementation bug")


class DisabledByDefaultPlaybook(Playbook):
    _METADATA = PlaybookMetadata(
        strategy_id="TEST_DISABLED_DEFAULT",
        version="1.0.0",
        description="Test fixture: never explicitly enabled in test configs.",
        supported_symbols=(SYMBOL,),
        supported_timeframes=(TIMEFRAME,),
        schema_versions_supported=(SCANNER_SCHEMA_VERSION,),
    )

    @property
    def metadata(self) -> PlaybookMetadata:
        return self._METADATA

    def evaluate(self, observation, config) -> Tuple[CandidateTrade, ...]:
        return (
            CandidateTrade(
                schema_version=1,
                trace_id=observation.trace_id,
                candidate_id=make_candidate_id(observation.trace_id, self._METADATA.strategy_id, self._METADATA.version),
                strategy_id=self._METADATA.strategy_id,
                strategy_version=self._METADATA.version,
                symbol=observation.symbol,
                timeframe=TIMEFRAME,
                timestamp=observation.timestamp,
                direction=Direction.UP,
                entry_concept="should never appear disabled",
                supporting_observations=(),
                evidence=(),
                reason_codes=(),
                reasoning="",
            ),
        )
