"""Data Pipeline — ADR-013 (Accepted).

The sole producer of normalized market data. Implements Phase 1 scope:
tick ingestion, bar construction, normalization, gap detection, data
quality assessment, historical cache, and replay production.

Explicitly out of scope for Phase 1 (see docs/adr/ADR-013-data-pipeline.md
and the Phase 1 implementation task): corporate action handling, gap
*repair* (detection only), AI/research integration, Dashboard, Analytics.
"""

from .config import PipelineConfig, DEFAULT_CONFIG
from .models import (
    SCHEMA_VERSION,
    DataQuality,
    NormalizedTick,
    NormalizedBar,
    MarketSnapshot,
    DataQualityReport,
    PipelineHealth,
    HistoricalSeries,
    ReplaySeries,
)
from .pipeline import DataPipeline

__all__ = [
    "PipelineConfig",
    "DEFAULT_CONFIG",
    "SCHEMA_VERSION",
    "DataQuality",
    "NormalizedTick",
    "NormalizedBar",
    "MarketSnapshot",
    "DataQualityReport",
    "PipelineHealth",
    "HistoricalSeries",
    "ReplaySeries",
    "DataPipeline",
]
