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
from .strategies import StrategyEngine
from .types import MarketSnapshot, ScoreResult


class Scanner:
    def __init__(
        self,
        config: Config = DEFAULT_CONFIG,
        sink: Optional[LogSink] = None,
        orb_engine: Optional[ORBEngine] = None,
        strategy_engine: Optional[StrategyEngine] = None,
    ):
        self.config = config
        self.sink = sink or LogSink()
        self.strategies = strategy_engine or StrategyEngine(config, orb_engine=orb_engine)
        self.orb = self.strategies.orb_engine  # backward-compatible reference
        self.scorer = Scorer(config, strategy_engine=self.strategies)

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

        # Dedicated strategy-layer log line (per-strategy signals + conflict).
        if result.strategies is not None:
            st = result.strategies
            self.sink.log_scan({
                "kind_detail": "strategy",
                "symbol": result.symbol,
                "net_score": st["net_score"],
                "direction": st["direction"],
                "conflict": st["conflict"],
                "detail": st["detail"],
                "signals": st["signals"],
            })

        # Scan log line. The Trade Thesis Summary is informational only and has
        # no bearing on the score or decision.
        self.sink.log_scan({
            "symbol": result.symbol,
            "decision": result.decision.value,
            "direction": result.direction.value,
            "score": round(result.total, 2),
            "capped_at": result.capped_at,
            "strategy_impact": result.strategies["net_score"] if result.strategies else 0.0,
            "conflict": result.strategies["conflict"] if result.strategies else False,
            "data_quality_flag": result.data_quality_flag,
            "thesis": result.thesis,
        })
        return result

    def scan(self, snapshots: List[MarketSnapshot]) -> List[ScoreResult]:
        return [self.scan_symbol(s) for s in snapshots]
