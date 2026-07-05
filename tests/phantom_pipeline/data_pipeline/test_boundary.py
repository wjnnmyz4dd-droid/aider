"""Boundary/type-level test (ADR-013 §5's type-level guarantee,
VALIDATION_MATRIX.md §1): every Data Pipeline output type is structurally
incapable of holding a trade idea, score, risk/compliance/execution
decision, or portfolio decision.
"""

from __future__ import annotations

import dataclasses
import unittest

from phantom_pipeline.data_pipeline.models import (
    DataQualityReport,
    HistoricalSeries,
    MarketSnapshot,
    NormalizedBar,
    NormalizedTick,
    PipelineHealth,
    ReplaySeries,
)

FORBIDDEN_FIELD_SUBSTRINGS = (
    "candidate_trade",
    "score",
    "risk_decision",
    "risk_pct",
    "lot_size",
    "stop_loss",
    "take_profit",
    "compliance_decision",
    "approve",
    "block",
    "execution_decision",
    "execute",
    "portfolio_decision",
    "instruction",
)

OUTPUT_TYPES = (
    NormalizedTick,
    NormalizedBar,
    MarketSnapshot,
    DataQualityReport,
    PipelineHealth,
    HistoricalSeries,
    ReplaySeries,
)


class TestBoundaryTypeLevelGuarantee(unittest.TestCase):
    def test_no_output_type_has_a_forbidden_field(self):
        for output_type in OUTPUT_TYPES:
            field_names = [f.name.lower() for f in dataclasses.fields(output_type)]
            for forbidden in FORBIDDEN_FIELD_SUBSTRINGS:
                matches = [name for name in field_names if forbidden in name]
                self.assertFalse(
                    matches,
                    f"{output_type.__name__} has forbidden-looking field(s) "
                    f"{matches} matching {forbidden!r}",
                )

    def test_every_output_type_is_frozen(self):
        for output_type in OUTPUT_TYPES:
            params = getattr(output_type, "__dataclass_params__", None)
            self.assertIsNotNone(params, f"{output_type.__name__} is not a dataclass")
            self.assertTrue(params.frozen, f"{output_type.__name__} is not frozen/immutable")

    def test_every_output_type_carries_schema_version_and_trace_id(self):
        for output_type in OUTPUT_TYPES:
            field_names = {f.name for f in dataclasses.fields(output_type)}
            self.assertIn("schema_version", field_names, output_type.__name__)
            self.assertIn("trace_id", field_names, output_type.__name__)

    def test_frozen_instance_cannot_be_mutated(self):
        from datetime import datetime, timezone
        from phantom_pipeline.data_pipeline.models import DataQuality, SCHEMA_VERSION

        bar = NormalizedBar(
            schema_version=SCHEMA_VERSION,
            trace_id="t",
            symbol="EURUSD",
            timeframe="M1",
            timestamp=datetime(2026, 7, 4, tzinfo=timezone.utc),
            open=1.0,
            high=1.0,
            low=1.0,
            close=1.0,
            volume=1.0,
            quality=DataQuality.NOMINAL,
            is_repaired=False,
            source="test",
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            bar.close = 2.0  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
