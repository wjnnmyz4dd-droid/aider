"""Phase 8E-R G2 — autonomous manager market-context integration.

Structure trailing and max-duration become operational by delivering read-only,
deterministic context (confirmed strategy swing + bars_open) to the accepted
PositionManager. The authoritative structure comes from the engine's OWN
confirmed_pivots (no recomputation); the context provider only normalizes/delivers;
the PM makes the trailing / max-duration decision; the manage channel/EA apply.

Tests: structure extraction, context freshness/bars_open, and the full manager
wiring driving trailing + max-duration to APPLIED via the accepted manage harness.
Deterministic; injected time; no networking.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from forex_swing_orb.bridge import serialize
from forex_swing_orb.ea_mt5 import mock_mt5
from forex_swing_orb.ea_mt5.position_manager import PositionManager
from forex_swing_orb.manage import BridgeMt5Adapter, ManageConsumer, ManagePaths, ManagerService
from forex_swing_orb.manage import ManageStatus
from forex_swing_orb.position.contract import PositionConfig, StopPhase, PMReason
from forex_swing_orb.producer.providers import Bars
from forex_swing_orb.producer.strategy_adapter import confirmed_structure, load_engine_module
from forex_swing_orb.runtime.context import ManagerMarketContextProvider
from forex_swing_orb.runtime import adoption

NOW = datetime(2026, 1, 7, 10, 0, 0, tzinfo=timezone.utc)
BUY = mock_mt5.ORDER_TYPE_BUY
SID = "0123456789abcdef"
TICKET = 5000001
_MODULE = load_engine_module()


# --------------------------------------------------------------------------- #
# bar / structure helpers
# --------------------------------------------------------------------------- #
def _bars(lows, *, symbol="EURUSD.FX", now=NOW):
    """Contiguous closed M15 bars ending at now-15 (last CLOSED bar)."""
    n = len(lows)
    rows = []
    for i, lo in enumerate(lows):
        ot = now - timedelta(minutes=15 * (n - i))
        rows.append({"open_time": ot, "open": lo, "high": lo + 0.0010,
                     "low": lo, "close": lo + 0.0005})
    return Bars(symbol, "M15", rows)


class _StubMarket:
    def __init__(self, bars):
        self._bars = bars

    def get_bars(self, symbol, timeframe, now):
        return self._bars


# fresh confirmed higher-low near the end (pivot at idx-2, confirm at idx-1)
_FRESH_LOWS = [1.1010, 1.1008, 1.1006, 1.1004, 1.1006, 1.1008, 1.1010, 1.1005, 1.1012]
# fresh confirmed lower-high (invert via highs) handled in the SHORT test


# --------------------------------------------------------------------------- #
# 1-5, 8: structure extraction (engine's own confirmed_pivots)
# --------------------------------------------------------------------------- #
def test_long_receives_confirmed_higher_low():
    s = confirmed_structure(_MODULE, _bars([1.1010, 1.1000, 1.0990, 1.1000]), "LONG", 1)
    assert s is not None and s["price"] == 1.0990       # the confirmed low
    assert s["bars_since_swing"] == 1                    # fresh


def test_short_receives_confirmed_lower_high():
    n = 4
    highs = [1.1000, 1.1010, 1.1020, 1.1010]            # confirmed high at idx2
    rows = [{"open_time": NOW - timedelta(minutes=15 * (n - i)),
             "open": h - 0.0005, "high": h, "low": h - 0.0010, "close": h - 0.0005}
            for i, h in enumerate(highs)]
    s = confirmed_structure(_MODULE, Bars("EURUSD.FX", "M15", rows), "SHORT", 1)
    assert s is not None and s["price"] == 1.1020


def test_forming_swing_is_ignored():
    # confirmed_structure sees only the bars given; the live provider drops the
    # forming bar, so a pivot needing the forming bar to confirm is never returned.
    # here the last low is the extreme but unconfirmed (no bar after it) -> ignored
    s = confirmed_structure(_MODULE, _bars([1.1010, 1.1005, 1.1000]), "LONG", 1)
    assert s is None                                     # last-bar low cannot confirm


def test_unconfirmed_or_monotonic_returns_none():
    assert confirmed_structure(_MODULE, _bars([1.1000, 1.1010, 1.1020, 1.1030]), "LONG", 1) is None


def test_structure_reference_deterministic():
    b = _bars([1.1010, 1.1000, 1.0990, 1.1000])
    a = confirmed_structure(_MODULE, b, "LONG", 1)
    c = confirmed_structure(_MODULE, b, "LONG", 1)
    assert a == c and a["structure_reference"]


# --------------------------------------------------------------------------- #
# context provider: freshness, bars_open, fail-closed (6,7,16,17,18,21)
# --------------------------------------------------------------------------- #
def _ctxp(bars, **kw):
    return ManagerMarketContextProvider(_StubMarket(bars), _MODULE, exec_timeframe="M15",
                                        pivot_k=1, max_context_age_sec=120,
                                        min_history_bars=3, **kw)


def test_context_delivers_structure_and_bars_open():
    opened = int((NOW - timedelta(minutes=15 * 5)).timestamp())
    c = _ctxp(_bars(_FRESH_LOWS)).context("EURUSD", "LONG", NOW, opened)
    assert c["fresh"] is True and c["confirmed_swing"] == 1.1005
    assert c["bars_since_swing"] == 1 and c["bars_open"] == 4
    assert c["source_snapshot_id"] and c["source_timeframe"] == "M15"


def test_context_missing_bars_fails_closed():
    c = ManagerMarketContextProvider(_StubMarket(None), _MODULE).context("EURUSD", "LONG", NOW, 0)
    assert c["fresh"] is False and c["confirmed_swing"] is None and c["bars_open"] is None


def test_context_stale_bars_fail_closed():
    stale = _bars(_FRESH_LOWS, now=NOW - timedelta(hours=6))   # last close 6h old
    c = _ctxp(stale).context("EURUSD", "LONG", NOW, int(NOW.timestamp()))
    assert c["fresh"] is False and c["reason"] is not None


def test_context_future_bar_fails_closed():
    fut = _bars(_FRESH_LOWS, now=NOW + timedelta(hours=1))     # bars beyond now
    c = _ctxp(fut).context("EURUSD", "LONG", NOW, int(NOW.timestamp()))
    assert c["fresh"] is False


def test_context_missing_open_time_bars_open_none():
    c = _ctxp(_bars(_FRESH_LOWS)).context("EURUSD", "LONG", NOW, None)
    assert c["bars_open"] is None                        # fail closed, but structure still delivered
    assert c["confirmed_swing"] == 1.1005


def test_context_conflicting_open_time_fails_closed():
    c = _ctxp(_bars(_FRESH_LOWS)).context("EURUSD", "LONG", NOW, "not-a-time")
    assert c["bars_open"] is None


def test_bars_open_counts_completed_bars_only_and_ignores_gaps():
    # 3 contiguous closed bars; opened before the first -> exactly 3 completed bars
    opened = int((NOW - timedelta(minutes=15 * 4)).timestamp())
    c = _ctxp(_bars([1.1000, 1.1001, 1.1002])).context("EURUSD", "LONG", NOW, opened)
    assert c["bars_open"] == 3


# --------------------------------------------------------------------------- #
# accepted manage harness: trailing + max-duration actually APPLY (10-14, 22-24)
# --------------------------------------------------------------------------- #
def _manager(tmp_path, cfg=None):
    mt5 = mock_mt5.MockMT5(); mt5.add_symbol("EURUSD")
    mpaths = ManagePaths(tmp_path / "bridge").ensure()
    consumer = ManageConsumer(mt5, mpaths)
    adapter = BridgeMt5Adapter(mt5, mpaths, now_fn=lambda: NOW, timeout_sec=5,
                               poll_interval_sec=1, sleep_fn=lambda s: None,
                               pump=lambda now: consumer.run_once(now))
    pm = PositionManager(adapter, str(tmp_path / "pm_audit.jsonl"),
                         cfg=cfg or PositionConfig())
    mgr = ManagerService(pm, adapter, mpaths, now_fn=lambda: NOW,
                         health_path=str(tmp_path / "health.json"))
    return mt5, mgr


def _open_long(mt5, mgr, entry=1.10000, sl=1.09800, tp=1.10600):
    mt5.positions[TICKET] = mock_mt5.Position(TICKET, "EURUSD", BUY, 0.10, entry, sl,
                                              tp, SID)
    mgr.register(SID, TICKET, "EURUSD", "LONG", entry, sl, tp, NOW)


def _drive_to_locked(mt5, mgr):
    _open_long(mt5, mgr)                                  # INITIAL, R=0.00200
    mgr.run_cycle(NOW, market={TICKET: 1.10200})         # -> BREAKEVEN (stop 1.10020)
    mgr.run_cycle(NOW, market={TICKET: 1.10300})         # -> LOCKED (stop 1.10100)
    assert mgr.pm.states[SID]["phase"] == StopPhase.LOCKED


def test_structure_trailing_now_fires_and_applies(tmp_path):
    mt5, mgr = _manager(tmp_path)
    _drive_to_locked(mt5, mgr)
    mgr.run_cycle(NOW, market={TICKET: 1.10400}, swings={TICKET: 1.10250},
                  structures={TICKET: "hl-1"}, bars_since={TICKET: 1})
    st = mgr.pm.states[SID]
    assert st["phase"] == StopPhase.TRAILING
    assert st["current_stop"] == pytest.approx(1.10240)  # 1.10250 - 1 pip offset, APPLIED


def test_without_context_trailing_does_not_fire(tmp_path):
    # the G2 gap: LOCKED with no swing context -> TRAIL_PENDING, stop unchanged
    mt5, mgr = _manager(tmp_path)
    _drive_to_locked(mt5, mgr)
    before = mgr.pm.states[SID]["current_stop"]
    r = mgr.run_cycle(NOW, market={TICKET: 1.10400})     # no swings
    assert r[0]["reason_code"] == PMReason.TRAIL_PENDING
    assert mgr.pm.states[SID]["current_stop"] == before


def test_stale_structure_produces_data_stale(tmp_path):
    mt5, mgr = _manager(tmp_path)
    _drive_to_locked(mt5, mgr)
    r = mgr.run_cycle(NOW, market={TICKET: 1.10400}, swings={TICKET: 1.10250},
                      structures={TICKET: "hl-1"}, bars_since={TICKET: 99})  # stale
    assert r[0]["reason_code"] == PMReason.DATA_STALE
    assert mgr.pm.states[SID]["phase"] == StopPhase.LOCKED


def test_duplicate_structure_reference_no_second_trail(tmp_path):
    mt5, mgr = _manager(tmp_path)
    _drive_to_locked(mt5, mgr)
    mgr.run_cycle(NOW, market={TICKET: 1.10400}, swings={TICKET: 1.10250},
                  structures={TICKET: "hl-1"}, bars_since={TICKET: 1})
    applied = mgr.pm.states[SID]["current_stop"]
    r = mgr.run_cycle(NOW, market={TICKET: 1.10450}, swings={TICKET: 1.10250},
                      structures={TICKET: "hl-1"}, bars_since={TICKET: 1})  # same ref
    assert r[0]["reason_code"] == PMReason.TRAIL_NO_IMPROVEMENT
    assert mgr.pm.states[SID]["current_stop"] == applied


def test_newer_structure_advances_trailing(tmp_path):
    mt5, mgr = _manager(tmp_path)
    _drive_to_locked(mt5, mgr)
    mgr.run_cycle(NOW, market={TICKET: 1.10400}, swings={TICKET: 1.10250},
                  structures={TICKET: "hl-1"}, bars_since={TICKET: 1})
    mgr.run_cycle(NOW, market={TICKET: 1.10500}, swings={TICKET: 1.10350},
                  structures={TICKET: "hl-2"}, bars_since={TICKET: 1})  # newer
    assert mgr.pm.states[SID]["current_stop"] == pytest.approx(1.10340)


def test_worse_structure_never_loosens(tmp_path):
    mt5, mgr = _manager(tmp_path)
    _drive_to_locked(mt5, mgr)
    mgr.run_cycle(NOW, market={TICKET: 1.10400}, swings={TICKET: 1.10250},
                  structures={TICKET: "hl-1"}, bars_since={TICKET: 1})
    applied = mgr.pm.states[SID]["current_stop"]
    mgr.run_cycle(NOW, market={TICKET: 1.10400}, swings={TICKET: 1.10150},  # lower swing
                  structures={TICKET: "hl-3"}, bars_since={TICKET: 1})
    assert mgr.pm.states[SID]["current_stop"] == applied  # never loosened


def test_max_duration_below_threshold_does_not_close(tmp_path):
    mt5, mgr = _manager(tmp_path, cfg=PositionConfig(max_duration_bars=5))
    _open_long(mt5, mgr)
    mgr.run_cycle(NOW, market={TICKET: 1.10050}, bars_open={TICKET: 4})   # 4 < 5
    assert mgr.pm.states[SID]["phase"] != StopPhase.CLOSED


def test_max_duration_at_threshold_closes(tmp_path):
    mt5, mgr = _manager(tmp_path, cfg=PositionConfig(max_duration_bars=5))
    _open_long(mt5, mgr)
    r = mgr.run_cycle(NOW, market={TICKET: 1.10050}, bars_open={TICKET: 5})  # 5 >= 5
    assert r[0]["reason_code"] == PMReason.MAX_DURATION_EXIT
    assert mgr.pm.states[SID]["phase"] == StopPhase.CLOSED


def test_max_duration_zero_disabled(tmp_path):
    mt5, mgr = _manager(tmp_path, cfg=PositionConfig(max_duration_bars=0))
    _open_long(mt5, mgr)
    mgr.run_cycle(NOW, market={TICKET: 1.10050}, bars_open={TICKET: 999})
    assert mgr.pm.states[SID]["phase"] != StopPhase.CLOSED


def test_kill_switch_blocks_trail_but_allows_protective_close(tmp_path):
    mt5, mgr = _manager(tmp_path)
    _drive_to_locked(mt5, mgr)
    r = mgr.run_cycle(NOW, market={TICKET: 1.10400}, swings={TICKET: 1.10250},
                      structures={TICKET: "hl-1"}, bars_since={TICKET: 1},
                      kill_switch=True)
    assert r[0]["reason_code"] == PMReason.KILL_SWITCH
    assert mgr.pm.states[SID]["phase"] == StopPhase.CLOSED     # authorized protective close


def test_one_inflight_enforced_with_context(tmp_path):
    mt5, mgr = _manager(tmp_path)
    _drive_to_locked(mt5, mgr)
    # a GENUINE unresolved in-flight: the instruction is durably present in the
    # bridge (pending) but not yet resolved. This is distinct from an M-5 orphan
    # (no instruction ever written), which self-heals; a genuine in-flight must
    # still hold the ticket and NOT be bypassed by rich market context.
    mid = "feedfeedfeedfeed"
    (mgr.paths.pending / f"{mid}.json").write_text("{}", encoding="utf-8")
    mgr.ledger.set_inflight(TICKET, mid)                       # unresolved in-flight
    mgr.run_cycle(NOW, market={TICKET: 1.10400}, swings={TICKET: 1.10250},
                  structures={TICKET: "hl-1"}, bars_since={TICKET: 1})
    assert mgr.ledger.get_inflight(TICKET) is not None         # not bypassed by context


# --------------------------------------------------------------------------- #
# run_once assembly + independence + restart (19,20,16 restart)
# --------------------------------------------------------------------------- #
class _FakeTruth:
    def __init__(self, positions):
        self._p = positions

    def positions(self):
        return list(self._p)

    def terminal_connected(self):
        return True

    def position_by_ticket(self, ticket):
        return next((p for p in self._p if p.ticket == ticket), None)

    def symbol_info(self, symbol):
        return SimpleNamespace(point=0.00001, digits=5)


def _fpos(ticket, comment, sl, opened_min_ago, price=1.10400, symbol="EURUSD"):
    return SimpleNamespace(ticket=ticket, symbol=symbol, type=BUY, volume=0.10,
                           price_open=1.10000, sl=sl, tp=1.10600, price_current=price,
                           comment=comment,
                           time=int((NOW - timedelta(minutes=opened_min_ago)).timestamp()))


def test_run_once_threads_context_into_trailing(tmp_path):
    mt5, mgr = _manager(tmp_path)
    _drive_to_locked(mt5, mgr)                             # SID now LOCKED
    mgr._truth = _FakeTruth([_fpos(TICKET, SID, mgr.pm.states[SID]["current_stop"], 90)])
    mgr._enter_paths = None                               # already tracked; no new discovery
    mgr._context_provider = _ctxp(_bars(_FRESH_LOWS))     # confirmed low 1.1005 -> candidate 1.10040
    # 1.10040 < locked stop 1.10100 -> worse -> no loosen; use a higher structure instead
    mgr._context_provider = _ctxp(_bars([1.1010, 1.1008, 1.1006, 1.1030, 1.1020, 1.1028, 1.1035, 1.1025, 1.1040]))
    r = mgr.run_once(NOW)
    # run_once obtained context and the PM acted (trail advanced or held deterministically)
    assert r and r[0]["reason_code"] in (PMReason.TRAIL_ADVANCED,
                                         PMReason.TRAIL_NO_IMPROVEMENT,
                                         PMReason.BROKER_CONSTRAINT)


def test_run_once_no_context_provider_is_safe(tmp_path):
    mt5, mgr = _manager(tmp_path)
    _drive_to_locked(mt5, mgr)
    mgr._truth = _FakeTruth([_fpos(TICKET, SID, mgr.pm.states[SID]["current_stop"], 90)])
    mgr._enter_paths = None
    mgr._context_provider = None                          # no provider -> no structure
    r = mgr.run_once(NOW)
    assert r[0]["reason_code"] == PMReason.TRAIL_PENDING  # BE/lock/reconcile still fine


def test_multiple_positions_independent_context():
    b_long = _bars([1.1010, 1.1000, 1.0990, 1.1000])     # confirmed low
    b_short_rows = [{"open_time": NOW - timedelta(minutes=15 * (4 - i)),
                     "open": h - 0.0005, "high": h, "low": h - 0.0010, "close": h - 0.0005}
                    for i, h in enumerate([1.1000, 1.1010, 1.1020, 1.1010])]

    class _MultiMarket:
        def get_bars(self, symbol, tf, now):
            return b_long if symbol == "EURUSD.FX" else Bars("GBPUSD.FX", "M15", b_short_rows)
    cp = ManagerMarketContextProvider(_MultiMarket(), _MODULE, exec_timeframe="M15",
                                      pivot_k=1, min_history_bars=3)
    long_ctx = cp.context("EURUSD", "LONG", NOW, int((NOW - timedelta(minutes=60)).timestamp()))
    short_ctx = cp.context("GBPUSD", "SHORT", NOW, int((NOW - timedelta(minutes=60)).timestamp()))
    assert long_ctx["confirmed_swing"] == 1.0990
    assert short_ctx["confirmed_swing"] == 1.1020         # independent, per-symbol bars


def test_bars_open_restart_deterministic():
    # bars_open derives from the (stable) broker open time -> identical across restarts
    cp = _ctxp(_bars(_FRESH_LOWS))
    opened = int((NOW - timedelta(minutes=15 * 6)).timestamp())
    a = cp.context("EURUSD", "LONG", NOW, opened)["bars_open"]
    b = cp.context("EURUSD", "LONG", NOW, opened)["bars_open"]
    assert a == b == 5                                    # deterministic, not reset to 0


def test_deterministic_repeat_full_context():
    cp = _ctxp(_bars(_FRESH_LOWS))
    o = int((NOW - timedelta(minutes=60)).timestamp())
    assert cp.context("EURUSD", "LONG", NOW, o) == cp.context("EURUSD", "LONG", NOW, o)


# --------------------------------------------------------------------------- #
# 25: no new pivot/trend logic in manage/runtime
# --------------------------------------------------------------------------- #
def test_no_duplicate_pivot_or_trend_logic_in_manage_runtime():
    import inspect
    from forex_swing_orb.manage import service as msvc
    from forex_swing_orb.runtime import context as rctx, adoption as radopt
    for mod in (msvc, rctx, radopt):
        src = inspect.getsource(mod)
        assert "fractal_pivot" not in src
        assert "def confirmed_pivots" not in src         # not redefined here
        assert "trend_from_pivots" not in src
    # the ONLY structure source is the engine's confirmed_pivots, reached via the
    # adapter seam; context.py references confirmed_structure, not a local parser
    assert "confirmed_structure" in inspect.getsource(rctx)
