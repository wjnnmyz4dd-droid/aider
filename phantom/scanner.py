"""Scanner — the orchestration entry point.

For each symbol snapshot it: runs the scorer (which folds in the ORB layer),
writes a scan log record and a dedicated ORB log record, and returns the
:class:`ScoreResult`. The scanner is the only component that produces a
decision; it never sends orders.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from .config import Config, DEFAULT_CONFIG
from .logging_sink import LogSink
from .orb import ORBEngine
from .scorer import Scorer
from .types import MarketSnapshot, ScoreResult


class Scanner:
    def __init__(
        self,
        config: Config = DEFAULT_CONFIG,
        sink: Optional[LogSink] = None,
        orb_engine: Optional[ORBEngine] = None,
    ):
        self.config = config
        self.sink = sink or LogSink()
        self.orb = orb_engine or ORBEngine(config)
        self.scorer = Scorer(config, orb_engine=self.orb)

    def scan_symbol(self, snap: MarketSnapshot) -> ScoreResult:
        result = self.scorer.score(snap)

        # Dedicated ORB log line (Part 3 fields).
        if result.orb is not None:
            o = result.orb
            self.sink.log_orb({
                "symbol": o.symbol,
                "session": o.session,
                "orb_high": o.orb_high,
                "orb_low": o.orb_low,
                "breakout_direction": o.breakout_direction.value,
                "false_breakout": o.false_breakout,
                "score_impact": round(o.score_impact, 2),
                "outcome": "BLOCKED" if o.blocked else ("CONFIRMED" if o.confirmed else "NONE"),
                "reason": o.reason,
            })

        # Scan log line.
        self.sink.log_scan({
            "symbol": result.symbol,
            "decision": result.decision.value,
            "direction": result.direction.value,
            "score": round(result.total, 2),
            "capped_at": result.capped_at,
            "orb_impact": round(result.orb.score_impact, 2) if result.orb else 0.0,
        })
        return result

    def scan(self, snapshots: List[MarketSnapshot]) -> List[ScoreResult]:
        return [self.scan_symbol(s) for s in snapshots]
