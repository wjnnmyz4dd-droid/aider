"""Read-only MT5 time-base field diagnostic (B2).

The production market provider labels each MT5 rate timestamp as true UTC
(`datetime.fromtimestamp(epoch, tz=timezone.utc)`), which is correct IFF the
MetaTrader5 package returns rate `time` as a true-UTC epoch. Whether it does is
BROKER/TERMINAL dependent and cannot be proven off-Windows, so PR-2 does NOT
change the production timestamp arithmetic and applies NO guessed broker offset.

This diagnostic lets an operator FIELD-VERIFY the assumption on a live Windows
DEMO terminal: it compares the terminal's most recent CLOSED M15 bar time (as MT5
reports it, interpreted as UTC — exactly as production does) against the
independently-computed "expected last closed M15 open" derived from the machine's
true UTC clock, and reports the apparent offset. A ~0 offset confirms the UTC
assumption; a ~N-hour offset is the broker/server skew that would need addressing
in a later, evidence-based PR.

READ-ONLY: it reads rates/terminal info only; it never trades, never writes, and
never mutates production timestamps. All comparison logic is pure and unit-tested
off-Windows; the terminal-touching entrypoint is Windows-only.
"""

from __future__ import annotations

import json
import sys

M15_SECONDS = 15 * 60

# classifications
TB_SOURCE_APPEARS_UTC = "SOURCE_APPEARS_UTC"
TB_APPARENT_BROKER_OFFSET = "APPARENT_BROKER_OFFSET"
TB_UNKNOWN = "UNKNOWN"


# --------------------------------------------------------------------------- #
# Pure logic (unit-tested off-Windows)
# --------------------------------------------------------------------------- #
def expected_last_closed_open_epoch(now_utc_epoch, tf_seconds=M15_SECONDS):
    """The open epoch of the most recently CLOSED bar for a true-UTC clock:
    floor(now / tf) gives the forming bar's open; one tf earlier is the last
    fully-closed bar's open."""
    now = int(now_utc_epoch)
    forming_open = (now // tf_seconds) * tf_seconds
    return forming_open - tf_seconds


def classify_timebase(reported_last_open_epoch, now_utc_epoch,
                      tf_seconds=M15_SECONDS, tolerance_sec=90):
    """Classify the MT5 time base from the reported last-closed-bar open epoch.

    ``reported_last_open_epoch`` is the terminal's most recent closed bar open,
    interpreted as UTC exactly as the production provider does. Returns a dict with
    the apparent offset (reported - expected). |offset| <= tolerance => the source
    behaves as true UTC; otherwise an apparent broker/server offset is reported.
    NEVER returns an instruction to apply an offset — evidence only."""
    if reported_last_open_epoch is None or now_utc_epoch is None:
        return {"class": TB_UNKNOWN, "offset_sec": None, "offset_hours": None,
                "note": "insufficient_data"}
    expected = expected_last_closed_open_epoch(now_utc_epoch, tf_seconds)
    offset = int(reported_last_open_epoch) - expected
    out = {"expected_last_open_epoch": expected,
           "reported_last_open_epoch": int(reported_last_open_epoch),
           "offset_sec": offset, "offset_hours": round(offset / 3600.0, 3)}
    if abs(offset) <= tolerance_sec:
        out["class"] = TB_SOURCE_APPEARS_UTC
        out["production_assumption_holds"] = True
    else:
        out["class"] = TB_APPARENT_BROKER_OFFSET
        out["production_assumption_holds"] = False
    return out


def server_utc_skew(terminal_time_epoch, now_utc_epoch, tolerance_sec=90):
    """Apparent skew of terminal_info().time (server clock, read as UTC) vs true
    UTC now — a second, independent signal. Evidence only."""
    if terminal_time_epoch is None or now_utc_epoch is None:
        return {"skew_sec": None, "skew_hours": None, "note": "insufficient_data"}
    skew = int(terminal_time_epoch) - int(now_utc_epoch)
    return {"skew_sec": skew, "skew_hours": round(skew / 3600.0, 3),
            "within_tolerance": abs(skew) <= tolerance_sec}


# --------------------------------------------------------------------------- #
# Windows-only entrypoint (read-only)
# --------------------------------------------------------------------------- #
def _connect():  # pragma: no cover - requires a live Windows terminal
    try:
        import MetaTrader5 as _mt5  # noqa: N813
    except Exception:
        return None
    try:
        if not _mt5.initialize():
            return None
    except Exception:
        return None
    return _mt5


def _probe(mt5, symbol):  # pragma: no cover - live terminal only
    import time as _time
    now_utc = int(_time.time())                       # machine true-UTC epoch
    tf = getattr(mt5, "TIMEFRAME_M15", None)
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, 3) if tf is not None else None
    reported_last_open = None
    if rates is not None and len(rates) >= 2:
        # drop the forming bar (last), take the most recent CLOSED bar's open,
        # interpreted as UTC exactly as the production provider does.
        reported_last_open = int(rates[-2]["time"])
    ti = mt5.terminal_info()
    terminal_time = int(getattr(ti, "time", 0)) or None
    return {
        "symbol": symbol,
        "timebase": classify_timebase(reported_last_open, now_utc),
        "server_utc_skew": server_utc_skew(terminal_time, now_utc),
        "note": ("Production applies NO offset; a non-UTC result here is [ENV] "
                 "evidence for a later, dedicated fix — not applied automatically."),
    }


def main(argv=None):  # pragma: no cover - Windows/terminal orchestration
    symbol = (argv or sys.argv[1:] or ["EURUSD"])[0]
    mt5 = _connect()
    if mt5 is None:
        print(json.dumps({"error": "MT5_UNAVAILABLE"}, indent=2))
        return 3
    try:
        report = _probe(mt5, symbol)
    finally:
        try:
            mt5.shutdown()
        except Exception:
            pass
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
