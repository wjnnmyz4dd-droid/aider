from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# A fixed reference "now" so every acquisition test is deterministic.
NOW = datetime(2024, 1, 10, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def now():
    return NOW


def raw_rows():
    """Two representative raw ForexFactory-style rows: a HIGH USD event in a few
    minutes and a LOW EUR event later. Timestamps are ISO with offsets."""
    return [
        {"title": "Non-Farm Employment Change", "country": "USD", "impact": "High",
         "date": "2024-01-10T12:10:00+00:00", "forecast": "170K", "previous": "199K"},
        {"title": "German Buba Speech", "country": "EUR", "impact": "Low",
         "date": "2024-01-10T15:00:00+00:00", "forecast": "", "previous": ""},
    ]
