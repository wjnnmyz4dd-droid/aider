"""Data Pipeline — ADR-013 (Accepted).

The sole producer of normalized market data. Implements: tick ingestion,
bar construction, normalization, gap detection and repair, data quality
assessment, bounded historical cache with bulk/warm-cache bootstrap,
explicit cache invalidation, replay production, and a dedicated metrics
surface.

Explicitly out of scope (see docs/adr/ADR-013-data-pipeline.md):
corporate action handling, AI/research integration, Dashboard, Analytics.
"""

from .config import PipelineConfig, DEFAULT_CONFIG
from .gaps import GapEvent, detect_gaps, repair_gaps
from .metrics import DataPipelineMetrics
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
    "GapEvent",
    "detect_gaps",
    "repair_gaps",
    "DataPipelineMetrics",
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
