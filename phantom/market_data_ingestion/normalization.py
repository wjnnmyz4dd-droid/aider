"""The one-way seam to Evidence Engine (ADR-033 SS0/SS3.2): converts a
validated, closed `RawBar` into `phantom.evidence_engine.models.Bar` --
the exact, unmodified type Evidence Engine already accepts. Never
called for a forming (not-yet-closed) bar; Evidence Engine's own
`closed-bar vs forming-bar` distinction is preserved by simply never
normalizing a forming bar at all, rather than passing a flag Evidence
Engine would need to understand."""

from __future__ import annotations

from phantom.evidence_engine.models import Bar

from .models import RawBar


def normalize(raw: RawBar) -> Bar:
    return Bar(
        symbol=raw.symbol, timestamp=raw.bar_open_time,
        open=raw.open, high=raw.high, low=raw.low, close=raw.close, volume=raw.volume,
    )


__all__ = ["normalize"]
