"""Tier 1 replay runner — orchestration ONLY (no strategy/compliance/PM authority,
and — by design — no dependency on the research package).

Pipeline:

    data_map (historical OHLC)
        -> canonical SignalEngine.generate            (replay.batch_instructions)
        -> BLOCKING batch-vs-online parity gate        (replay.compare_parity)
        -> trade records from the engine's OWN audit   (trade_records.build_trades)

The runner returns the reconstructed trade list plus parity evidence and the
STRATEGY-EDGE-RESEARCH labels. Performance MATH is intentionally NOT computed here:
it is owned by ``research.portfolio`` and assembled by ``research.replay_report``
(the measurement tier). Keeping the harness free of any ``research`` import
preserves the production boundary guard (research stays deletable / non-coupled).

If parity fails, the runner returns status ``PARITY_FAILURE`` and produces NO trade
list — the caller must not compute performance statistics.
"""

from __future__ import annotations

from . import replay, trade_records

MODE_LABEL = "STRATEGY-EDGE RESEARCH"
LABELS = {
    "exit_model": (
        "Engine canonical static exits: STOP@stop level (R=-1), TP@target level "
        "(R=+planned), TIME/INVALIDATED@conservative worst-case bar extreme; same-bar "
        "stop&target resolved stop-first by the engine."),
    "cost_model": (
        "GROSS — COST MODEL = NOT YET PRODUCTION-FIDELITY "
        "(no spread/commission/slippage/swap)"),
    "news_compliance": "STRATEGY-EDGE RESEARCH — HISTORICAL NEWS/COMPLIANCE NOT FULLY REPLAYED",
    "position_manager": "NOT SIMULATED (Tier 1 uses the engine's static exits)",
}


def _exit_reason_counts(trades):
    counts = {}
    for t in trades:
        counts[t.get("exit_reason")] = counts.get(t.get("exit_reason"), 0) + 1
    return counts


def run_tier1(data_map, config=None, *, run_parity=True, online_start_index=None):
    """Run the Tier 1 replay. Returns a report dict.

    ``run_parity`` MUST stay True for any result to be trusted; it is togglable only
    so the parity gate can be unit-tested in isolation. On parity failure the report
    has status ``PARITY_FAILURE`` and NO trades/metrics. To obtain performance,
    pass the returned dict to ``research.replay_report.performance_report``.
    """
    module, _ = replay.load_engine(config)
    batch, engine = replay.batch_instructions(module, data_map, config)

    parity = {"ran": bool(run_parity)}
    if run_parity:
        online = replay.online_instructions(module, data_map, config,
                                            start_index=online_start_index)
        ok, first = replay.compare_parity(batch, online)
        parity.update({"passed": ok, "first_divergence": first,
                       "batch_signal_count": sum(len(v) for v in batch.values()),
                       "online_signal_count": sum(len(v) for v in online.values())})
        if not ok:
            return {
                "status": "PARITY_FAILURE",
                "mode": MODE_LABEL,
                "parity": parity,
                "note": "Performance statistics withheld: batch vs online strategy "
                        "outputs diverged. Fix parity before judging strategy.",
            }

    trades, open_at_end = trade_records.build_trades(module, engine, data_map)
    return {
        "status": "OK",
        "mode": MODE_LABEL,
        "labels": dict(LABELS),
        "parity": parity,
        "symbols": sorted(data_map),
        "setup_count": sum(len(v) for v in batch.values()),   # engine ENTER signals
        "trade_count": len(trades),
        "open_at_end": open_at_end,
        "exit_reason_counts": _exit_reason_counts(trades),
        "trades": trades,
    }
