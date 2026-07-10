"""Execution Quality Monitor (ADR-029 §5): a new, this-package-owned
deterministic 0-100 score per trade -- slippage magnitude, fill time,
requote count, and stop/TP execution accuracy -- aggregated per pair."""

from __future__ import annotations

import statistics as pystats
from collections import defaultdict
from typing import Dict, List, Sequence

from .config import ResearchEngineConfig
from .models import ClosedTrade, ExecutionQualityRecord, ExecutionQualitySummary, executed_trades


def compute_execution_quality_record(trade: ClosedTrade, config: ResearchEngineConfig) -> ExecutionQualityRecord:
    """Assumes `trade.was_executed` -- callers filter via
    `executed_trades()` first (`summarize_execution_quality` does)."""

    total_slippage_pips = abs(trade.slippage_entry_pips or 0.0) + abs(trade.slippage_exit_pips or 0.0)
    slippage_score = 100.0
    if config.max_acceptable_slippage_pips > 0:
        slippage_score = max(0.0, 100.0 - min(100.0, total_slippage_pips / config.max_acceptable_slippage_pips * 100.0))

    fill_time_score = 100.0
    if config.max_acceptable_fill_time_ms > 0 and trade.time_to_fill_ms is not None:
        fill_time_score = max(0.0, 100.0 - min(100.0, trade.time_to_fill_ms / config.max_acceptable_fill_time_ms * 100.0))

    requote_penalty = trade.requotes * config.requote_penalty_per_event

    stop_execution_quality = 100.0
    if trade.stop_loss_price is not None and not trade.won and config.stop_execution_tolerance_pips > 0:
        distance = abs(trade.exit_price - trade.stop_loss_price)
        stop_execution_quality = max(0.0, 100.0 - min(100.0, distance / config.stop_execution_tolerance_pips * 100.0))

    tp_execution_quality = 100.0
    if trade.take_profit_price is not None and trade.won and config.tp_execution_tolerance_pips > 0:
        distance = abs(trade.exit_price - trade.take_profit_price)
        tp_execution_quality = max(0.0, 100.0 - min(100.0, distance / config.tp_execution_tolerance_pips * 100.0))

    composite = (
        config.slippage_weight * slippage_score
        + config.fill_time_weight * fill_time_score
        + config.requote_weight * max(0.0, 100.0 - requote_penalty)
        + config.stop_tp_execution_weight * ((stop_execution_quality + tp_execution_quality) / 2.0)
    )

    return ExecutionQualityRecord(
        pair=trade.pair, slippage_score=slippage_score, fill_time_score=fill_time_score,
        requote_penalty=requote_penalty, stop_execution_quality=stop_execution_quality,
        tp_execution_quality=tp_execution_quality, composite_score=max(0.0, min(100.0, composite)),
    )


def summarize_execution_quality(trades: Sequence[ClosedTrade], config: ResearchEngineConfig) -> ExecutionQualitySummary:
    executed = executed_trades(trades)
    if not executed:
        return ExecutionQualitySummary(
            overall_score=0.0, average_slippage_pips=0.0, average_time_to_fill_ms=0.0,
            total_requotes=0, total_partial_fills=0, per_pair_score=(),
        )

    records = [compute_execution_quality_record(t, config) for t in executed]
    per_pair: Dict[str, List[float]] = defaultdict(list)
    for trade, record in zip(executed, records):
        per_pair[trade.pair].append(record.composite_score)

    return ExecutionQualitySummary(
        overall_score=pystats.mean(r.composite_score for r in records),
        average_slippage_pips=pystats.mean(abs(t.slippage_entry_pips or 0.0) + abs(t.slippage_exit_pips or 0.0) for t in executed),
        average_time_to_fill_ms=pystats.mean(t.time_to_fill_ms or 0.0 for t in executed),
        total_requotes=sum(t.requotes for t in executed),
        total_partial_fills=sum(t.partial_fills for t in executed),
        per_pair_score=tuple(sorted((pair, pystats.mean(scores)) for pair, scores in per_pair.items())),
    )


__all__ = ["compute_execution_quality_record", "summarize_execution_quality"]
