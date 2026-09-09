"""Reconstruct trade records from the engine's OWN audit output (Tier 1).

This module invents NO strategy behavior. It reads the frozen engine's per-bar
audit trail (ENTER / HOLD / EXIT decisions the engine already made) plus the
engine's own emitted instruction (entry/stop/target/session/direction/planned R),
and turns each ENTER->EXIT episode into one trade record in the schema the
existing ``research.portfolio`` analytics consume (``r_multiple``/``pnl``/``mae``/
``mfe``/``session``/``symbol`` + descriptive extras).

EXIT MODEL (canonical + conservative; recorded on every record and report):
  * EXIT_STOP_LOSS   -> exit at the engine's own STOP level      (R = -1.0)
  * EXIT_TAKE_PROFIT -> exit at the engine's own TARGET level    (R = +planned R)
  * EXIT_TIME / EXIT_INVALIDATED -> the engine defines no fill level, so FAIL
    CLOSED to the conservative worst-case bar extreme (LONG: bar low; SHORT: bar
    high) of the exit bar. Never the favorable extreme.
  * Same-bar stop AND target is resolved by the ENGINE's own worst-case
    precedence (stop-first); this module inherits that classification verbatim.

Limitations (Tier 1): this is the strategy's specified STATIC exit model. It does
NOT model the production Position Manager (break-even/trailing/profit-lock), live
fills, spread/commission/slippage, or historical news/compliance.
"""

from __future__ import annotations

EXIT_AT_STOP = "STOP_LEVEL"
EXIT_AT_TARGET = "TARGET_LEVEL"
EXIT_AT_WORST_CASE = "CONSERVATIVE_WORST_CASE_BAR_EXTREME"


def _bar_lookup(module, df):
    """Map format_ts(index) -> integer position, plus numpy OHLC arrays, using the
    engine's OWN index normalization so timestamps match the audit exactly."""
    ndf = module.to_utc_index(df)
    pos = {module.format_ts(ts): i for i, ts in enumerate(ndf.index)}
    return ndf, pos


def build_trades(module, engine, data_map):
    """Return (trades, open_at_end) reconstructed from engine.audit/instructions.

    ``module`` is the loaded engine module; ``engine`` must have already run
    ``generate(data_map)`` so ``engine.audit``/``engine.instructions`` are populated.
    """
    RC = module.ReasonCode
    trades = []
    open_at_end = []
    for sym in sorted(data_map):
        df = data_map[sym]
        ndf, pos = _bar_lookup(module, df)
        highs = ndf["high"].to_numpy(dtype=float)
        lows = ndf["low"].to_numpy(dtype=float)
        instrs_by_id = {i["signal_id"]: i for i in engine.instructions.get(sym, [])}
        audit = engine.audit.get(sym, [])

        pending = None
        for rec in audit:
            decision = rec.get("decision")
            if decision == "ENTER" and rec.get("reason_code") == RC.SIGNAL_GENERATED:
                sid = rec.get("signal_id")
                instr = instrs_by_id.get(sid)
                if instr is None:                      # audit/instruction desync -> skip safely
                    continue
                pending = {"instr": instr, "enter_ts": rec.get("evaluation_timestamp")}
            elif decision == "EXIT" and pending is not None:
                trades.append(_finalize(module, sym, pending, rec, pos, highs, lows))
                pending = None
        if pending is not None:                        # never exited within the data window
            open_at_end.append({
                "symbol": sym,
                "signal_id": pending["instr"]["signal_id"],
                "entry_timestamp": pending["enter_ts"],
                "reason": "OPEN_AT_END",
            })
    return trades, open_at_end


def _finalize(module, symbol, pending, exit_rec, pos, highs, lows):
    instr = pending["instr"]
    direction = 1 if str(instr["direction"]).upper() == "LONG" else -1
    entry = float(instr["entry_price"])
    stop = float(instr["stop_loss"])
    target = float(instr["take_profit"])
    stop_distance = abs(entry - stop)
    ev = instr.get("evidence_summary", {}) or {}
    planned_r = ev.get("rr_planned")

    enter_ts = pending["enter_ts"]
    exit_ts = exit_rec.get("evaluation_timestamp")
    exit_reason = exit_rec.get("reason_code")

    exit_pos = pos.get(exit_ts)
    entry_pos = pos.get(enter_ts)

    # --- canonical / conservative exit price -------------------------------
    if exit_reason == module.ReasonCode.EXIT_STOP_LOSS:
        exit_price, assumption = stop, EXIT_AT_STOP
    elif exit_reason == module.ReasonCode.EXIT_TAKE_PROFIT:
        exit_price, assumption = target, EXIT_AT_TARGET
    else:  # EXIT_TIME / EXIT_INVALIDATED -> no engine-defined level -> worst case
        if exit_pos is not None:
            exit_price = lows[exit_pos] if direction > 0 else highs[exit_pos]
        else:                                          # unresolved bar -> stop (worst)
            exit_price = stop
        assumption = EXIT_AT_WORST_CASE

    pnl = direction * (exit_price - entry)             # price units (1 lot notional)
    r_multiple = (pnl / stop_distance) if stop_distance > 0 else None

    # --- MFE / MAE over the held window (bars after entry .. exit), in R ----
    mfe = mae = None
    if (stop_distance > 0 and entry_pos is not None and exit_pos is not None
            and exit_pos > entry_pos):
        hi = highs[entry_pos + 1: exit_pos + 1]
        lo = lows[entry_pos + 1: exit_pos + 1]
        if len(hi) > 0:
            if direction > 0:
                fav = float(hi.max()) - entry
                adv = float(lo.min()) - entry
            else:
                fav = entry - float(lo.min())
                adv = entry - float(hi.max())
            mfe = round(max(0.0, fav) / stop_distance, 6)     # favorable >= 0 (R)
            mae = round(min(0.0, adv) / stop_distance, 6)     # adverse   <= 0 (R)

    holding_bars = (exit_pos - entry_pos) if (exit_pos is not None
                                              and entry_pos is not None) else None

    return {
        # research.portfolio schema (r_multiple/pnl/mae/mfe/session/symbol)
        "r_multiple": (round(r_multiple, 6) if r_multiple is not None else None),
        "pnl": round(pnl, 8),
        "mae": mae,
        "mfe": mfe,
        "session": instr.get("session_id"),
        "symbol": symbol,
        # descriptive extras (ignored by portfolio; used by reporting/audit)
        "signal_id": instr["signal_id"],
        "direction": instr["direction"],
        "signal_timestamp": instr.get("generated_timestamp"),
        "entry_timestamp": enter_ts,
        "entry": entry,
        "stop_loss": stop,
        "take_profit": target,
        "stop_distance": round(stop_distance, 8),
        "planned_r": planned_r,
        "exit_timestamp": exit_ts,
        "exit_price": round(float(exit_price), 8),
        "exit_reason": exit_reason,
        "exit_price_assumption": assumption,
        "same_bar_stop_and_target": bool(
            (exit_rec.get("numeric_evidence") or {}).get("same_bar_stop_and_target", False)),
        "holding_bars": holding_bars,
    }
