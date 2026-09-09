"""Broker-derived recent-slippage observation (Phase 8D, item 8).

Replaces the placeholder ``recent_slippage_points: 0.0`` in the broker-health
provider with a value derived from real broker fills. The ENTER-channel EA records
each fill's ``execution.slippage`` (filled price − requested price, in price units)
in the bridge result records; this source reads those results (READ-ONLY) and
reports, per symbol, the worst recent absolute slippage converted to points.

No networking, no trading. Absence of recent fills is a legitimate observation
(0.0), not a failure. The source only reads its own bridge tree.
"""

from __future__ import annotations

from datetime import timedelta

from ..bridge import serialize
from ..bridge.paths import BridgePaths


class BridgeSlippageSource:
    def __init__(self, bridge_paths, lookback_sec=86400):
        self.paths = (bridge_paths if isinstance(bridge_paths, BridgePaths)
                      else BridgePaths(bridge_paths))
        self.lookback_sec = lookback_sec

    def recent_points(self, symbol, now, point):
        """Worst recent absolute slippage for ``symbol`` in points, or None if the
        broker point is unusable (fail closed on a bad point; the provider then
        rejects the snapshot). No recent fills -> 0.0 (observed, not a failure)."""
        if not point or point <= 0:
            return None
        cutoff = now - timedelta(seconds=self.lookback_sec)
        worst = 0.0
        for d in (self.paths.results, self.paths.archive_accepted):
            if not d.exists():
                continue
            for f in d.glob("*.json"):
                rec = self._load(f)
                if rec is None or rec.get("symbol") != symbol:
                    continue
                ex = rec.get("execution") or {}
                slip = ex.get("slippage")
                if not isinstance(slip, (int, float)):
                    continue
                if not self._recent(rec, cutoff):
                    continue
                worst = max(worst, abs(float(slip)) / point)
        return worst

    def _recent(self, rec, cutoff):
        ts = (rec.get("completed_timestamp") or rec.get("applied_timestamp")
              or rec.get("claimed_timestamp") or rec.get("generated_timestamp"))
        dt = serialize.parse_iso(ts) if ts else None
        return dt is None or dt >= cutoff   # undated -> count it (fail safe toward blocking)

    def _load(self, f):
        try:
            ok, rec = serialize.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return rec if ok and isinstance(rec, dict) else None
