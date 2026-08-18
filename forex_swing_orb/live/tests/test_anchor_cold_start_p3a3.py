"""PR-3A.3 — safe daily-anchor cold-start reconstruction from authoritative broker
history. A mid-day first start no longer deadlocks on R_ACCOUNT_ANCHOR_UNAVAILABLE
WHEN the Prague-midnight anchor is provable from complete deal history and the book was
flat at midnight; every unprovable case remains fail-closed. Deterministic; no MT5.

Covers the Section U matrix, the Section V adversarial safety proofs, the Section Q
deterministic cross-check (forward events -> reconstruct backward -> original anchor),
and the Section R timezone/DST cases (CET, CEST, and boundary correctness).
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

from forex_swing_orb.bridge import serialize                                 # noqa: E402
from forex_swing_orb.compliance.contract import FtmoConfig, ftmo_levels      # noqa: E402
from forex_swing_orb.live import mt5_client as mc                            # noqa: E402
from forex_swing_orb.live.providers import (DailyAnchorTracker,              # noqa: E402
                                            Mt5AccountStateProvider,
                                            reconstruct_cold_start_anchor)

UTC = timezone.utc
R = DailyAnchorTracker

# Winter (CET, Prague = UTC+1): trading day 2026-01-07, Prague-00:00 = 2026-01-06 23:00Z
W_TDAY = "2026-01-07"
W_MIDNIGHT = datetime(2026, 1, 6, 23, 0, tzinfo=UTC)
W_NOW = datetime(2026, 1, 7, 13, 0, tzinfo=UTC)         # Prague 14:00
# Summer (CEST, Prague = UTC+2): trading day 2026-07-07, Prague-00:00 = 2026-07-06 22:00Z
S_TDAY = "2026-07-07"
S_MIDNIGHT = datetime(2026, 7, 6, 22, 0, tzinfo=UTC)
S_NOW = datetime(2026, 7, 7, 12, 0, tzinfo=UTC)


def _deal(t, *, dtype=0, entry=0, profit=0.0, commission=0.0, swap=0.0, fee=0.0, pid=1):
    return {"time": t, "type": dtype, "entry": entry, "profit": profit,
            "commission": commission, "swap": swap, "fee": fee, "position_id": pid}


def _closed_trade(pid, *, profit=0.0, commission=0.0, swap=0.0, buy=True,
                  in_hour=8, out_hour=9, day=(2026, 1, 7)):
    """A position OPENED and CLOSED today (both legs at time >= Prague midnight), so it
    was NOT open at midnight — a provably-flat contribution to the balance delta."""
    dt = mc.DEAL_TYPE_BUY if buy else mc.DEAL_TYPE_SELL
    y, m, d = day
    return [_deal(datetime(y, m, d, in_hour, 0, tzinfo=UTC), dtype=dt,
                  entry=mc.DEAL_ENTRY_IN, profit=0.0, pid=pid),
            _deal(datetime(y, m, d, out_hour, 0, tzinfo=UTC), dtype=dt,
                  entry=mc.DEAL_ENTRY_OUT, profit=profit, commission=commission,
                  swap=swap, pid=pid)]


def _ev(*, now=W_NOW, midnight=W_MIDNIGHT, current_balance=100000.0, deals=None,
        open_positions=None, account_id=123, history_ok=True, margin_days=7):
    return {"history_ok": history_ok, "current_balance": current_balance,
            "midnight_utc": midnight,
            "history_from_utc": midnight - timedelta(days=margin_days),
            "account_id": account_id, "deals": deals or [],
            "open_positions": open_positions or []}


def _rc(ev, *, now=W_NOW, tday=W_TDAY, acct=123):
    return reconstruct_cold_start_anchor(tday=tday, now=now, evidence=ev,
                                         expected_account_id=acct)


# --------------------------------------------------------------------------- #
# Provider integration harness
# --------------------------------------------------------------------------- #
def _client(balance=100000.0, equity=100000.0, login=123, positions=(), deals=()):
    c = mc.FakeMt5Client()
    c.account = SimpleNamespace(login=login, trade_mode=mc.ACCOUNT_TRADE_MODE_DEMO,
                                balance=balance, equity=equity, profit=0.0, margin=0.0,
                                margin_free=balance, margin_level=0.0, currency="USD",
                                leverage=100)
    c.positions = list(positions)
    for d in deals:
        c.deals.setdefault(d.position_id, []).append(d)
    return c


def _provider(client, tmp_path):
    tr = DailyAnchorTracker(str(tmp_path / "anchor.json"))
    return Mt5AccountStateProvider(client, initial_balance=100000.0, anchor_tracker=tr)


# =========================================================================== #
# U1–U3 persisted / restart / live rollover (existing invariants preserved)
# =========================================================================== #
def test_U1_existing_same_day_anchor_loads_unchanged(tmp_path):
    tr = DailyAnchorTracker(str(tmp_path / "a.json"))
    tr._records[W_TDAY] = _seed_rec(W_TDAY, 100000.0, 100000.0)
    got = tr.record(W_NOW, 55555.0, equity=55555.0, initial_balance=100000.0,
                    daily_loss_pct=0.05, account_id=123,
                    cold_start_evidence_fn=lambda: _ev())
    assert got["day_start_balance"] == 100000.0        # reused, NOT recomputed from 55555
    assert got.get("anchor_unavailable") is not True


def test_U2_restart_does_not_rewrite_anchor(tmp_path):
    p = str(tmp_path / "a.json")
    tr = DailyAnchorTracker(p)
    tr._records[W_TDAY] = _seed_rec(W_TDAY, 100000.0, 100000.0)
    tr._sync_aggregate()
    tr2 = DailyAnchorTracker(p)                         # simulate restart
    got = tr2.record(W_NOW, 42.0, equity=42.0, initial_balance=100000.0,
                     daily_loss_pct=0.05, account_id=123,
                     cold_start_evidence_fn=lambda: _ev(current_balance=42.0))
    assert got["day_start_balance"] == 100000.0        # immutable across restart


def test_U3_live_rollover_still_primary(tmp_path):
    tr = DailyAnchorTracker(str(tmp_path / "a.json"), cadence_sec=900)
    prev = datetime(2026, 1, 6, 22, 55, tzinfo=UTC)     # Prague 23:55 day 01-06
    roll = datetime(2026, 1, 6, 23, 5, tzinfo=UTC)      # Prague 00:05 day 01-07 (gap 10m)
    tr.record(prev, 100000.0, equity=100000.0, initial_balance=100000.0, daily_loss_pct=0.05)
    rec = tr.record(roll, 100000.0, equity=100000.0, initial_balance=100000.0, daily_loss_pct=0.05)
    assert rec.get("anchor_unavailable") is not True
    assert rec["anchor_source"] == R.SOURCE_LIVE_ROLLOVER


# =========================================================================== #
# U4–U15 reconstruction cases (pure function)
# =========================================================================== #
def test_U4_cold_start_complete_history_reconstructs():
    f, r = _rc(_ev(current_balance=99493.0,
                   deals=_closed_trade(1, profit=-500.0, commission=-7.0, buy=False)))
    assert r is None and f["day_start_balance"] == 100000.0 and f["day_start_equity"] == 100000.0


def test_U5_no_events_reconstructs_current_balance():
    f, r = _rc(_ev(current_balance=100000.0, deals=[]))
    assert r is None and f["day_start_balance"] == 100000.0


def test_U6_profitable_close():
    f, r = _rc(_ev(current_balance=100800.0, deals=_closed_trade(1, profit=800.0)))
    assert r is None and f["day_start_balance"] == 100000.0


def test_U7_losing_close():
    f, r = _rc(_ev(current_balance=99000.0, deals=_closed_trade(1, profit=-1000.0, buy=False)))
    assert r is None and f["day_start_balance"] == 100000.0


def test_U8_commission():
    # a standalone commission deal (no position) since midnight
    f, r = _rc(_ev(current_balance=99990.0, deals=[
        _deal(datetime(2026, 1, 7, 9, 0, tzinfo=UTC), dtype=7, entry=0, commission=-10.0, pid=0)]))
    assert r is None and f["day_start_balance"] == 100000.0


def test_U9_swap():
    f, r = _rc(_ev(current_balance=99985.0, deals=_closed_trade(1, profit=0.0, swap=-15.0)))
    assert r is None and f["day_start_balance"] == 100000.0


def test_U10_multiple_deals():
    d = _closed_trade(1, profit=300.0, commission=-4.0, in_hour=7, out_hour=8) + \
        _closed_trade(2, profit=-100.0, swap=-2.0, in_hour=8, out_hour=9, buy=False)
    # net = 300 -4 -100 -2 = 194 ; day_start = current - 194
    f, r = _rc(_ev(current_balance=100194.0, deals=d))
    assert r is None and f["day_start_balance"] == 100000.0


def test_U11_partial_closes_same_position_today():
    # one position opened AND partially closed twice today (flat by proof: opened today)
    d = [_deal(datetime(2026, 1, 7, 8, 0, tzinfo=UTC), dtype=0, entry=0, profit=0.0, pid=5),   # IN
         _deal(datetime(2026, 1, 7, 9, 0, tzinfo=UTC), dtype=1, entry=1, profit=200.0, pid=5),  # partial OUT
         _deal(datetime(2026, 1, 7, 10, 0, tzinfo=UTC), dtype=1, entry=1, profit=150.0, pid=5)]  # partial OUT
    f, r = _rc(_ev(current_balance=100350.0, deals=d))
    assert r is None and f["day_start_balance"] == 100000.0


def test_U12_position_open_before_and_closed_after_midnight_fails():
    # OUT after midnight but NO in-window IN>=midnight -> spanned midnight -> fail closed
    d = [_deal(datetime(2026, 1, 7, 9, 0, tzinfo=UTC), dtype=1, entry=1, profit=500.0, pid=9)]
    f, r = _rc(_ev(current_balance=100500.0, deals=d))
    assert f is None and r == R.R_RECON_OPEN_SPANS_MIDNIGHT


def test_U12b_currently_open_position_opened_before_midnight_fails():
    op = [{"position_id": 9, "open_time": datetime(2026, 1, 5, 12, 0, tzinfo=UTC)}]
    f, r = _rc(_ev(current_balance=100000.0, open_positions=op))
    assert f is None and r == R.R_RECON_OPEN_SPANS_MIDNIGHT


def test_U13_deposit_event_after_midnight_excluded_from_reference():
    # a mid-day deposit of +5000 (DEAL_TYPE_BALANCE) is subtracted so the anchor is the
    # TRUE midnight balance (a deposit cannot inflate/reset the daily-loss reference)
    d = [_deal(datetime(2026, 1, 7, 10, 0, tzinfo=UTC), dtype=2, entry=0, profit=5000.0, pid=0)]
    f, r = _rc(_ev(current_balance=105000.0, deals=d))
    assert r is None and f["day_start_balance"] == 100000.0


def test_U14_withdrawal_event():
    d = [_deal(datetime(2026, 1, 7, 10, 0, tzinfo=UTC), dtype=2, entry=0, profit=-2000.0, pid=0)]
    f, r = _rc(_ev(current_balance=98000.0, deals=d))
    assert r is None and f["day_start_balance"] == 100000.0


def test_U15_credit_adjustment():
    d = [_deal(datetime(2026, 1, 7, 10, 0, tzinfo=UTC), dtype=3, entry=0, profit=250.0, pid=0)]
    f, r = _rc(_ev(current_balance=100250.0, deals=d))
    assert r is None and f["day_start_balance"] == 100000.0


# =========================================================================== #
# U16–U23 fail-closed guards
# =========================================================================== #
def test_U16_unknown_event_fails_closed():
    d = [_deal(datetime(2026, 1, 7, 9, 0, tzinfo=UTC), dtype=99, entry=0, profit=1.0, pid=0)]
    f, r = _rc(_ev(deals=d))
    assert f is None and r == R.R_RECON_UNKNOWN_EVENT


def test_U17_history_query_failure_fails_closed():
    f, r = _rc(_ev(history_ok=False))
    assert f is None and r == R.R_RECON_HISTORY_UNAVAILABLE


def test_U18_incomplete_history_window_fails_closed():
    ev = _ev()
    ev["history_from_utc"] = W_MIDNIGHT + timedelta(hours=1)   # window starts AFTER midnight
    f, r = _rc(ev)
    assert f is None and r == R.R_RECON_HISTORY_INCOMPLETE


def test_U19_deals_none_fails_closed():
    ev = _ev(); ev["deals"] = None
    f, r = _rc(ev)
    assert f is None and r == R.R_RECON_HISTORY_UNAVAILABLE


def test_U20_malformed_timestamp_fails_closed():
    d = [_deal(datetime(2026, 1, 7, 9, 0), dtype=1, entry=1, profit=-1.0, pid=1)]  # naive
    f, r = _rc(_ev(deals=d))
    assert f is None and r == R.R_RECON_TIMEBASE


def test_U21_wrong_account_identity_fails_closed():
    f, r = reconstruct_cold_start_anchor(tday=W_TDAY, now=W_NOW,
                                         evidence=_ev(account_id=999),
                                         expected_account_id=123)
    assert f is None and r == R.R_RECON_IDENTITY


def test_U22_nonfinite_current_balance_fails_closed():
    f, r = _rc(_ev(current_balance=float("nan")))
    assert f is None and r == R.R_RECON_NONFINITE


def test_U23_nonfinite_reconstructed_or_deal_value_fails_closed():
    d = [_deal(datetime(2026, 1, 7, 9, 0, tzinfo=UTC), dtype=1, entry=1, profit=float("inf"), pid=1)]
    f, r = _rc(_ev(deals=d))
    assert f is None and r == R.R_RECON_NONFINITE


def test_U30_future_deal_timestamp_fails_closed():
    d = [_deal(W_NOW + timedelta(hours=1), dtype=1, entry=1, profit=-1.0, pid=1)]
    f, r = _rc(_ev(deals=d))
    assert f is None and r == R.R_RECON_TIMEBASE


# =========================================================================== #
# U24–U26 immutability / reuse / disagreement (integration)
# =========================================================================== #
def test_U24_reconstructed_anchor_immutable_same_run(tmp_path):
    tr = DailyAnchorTracker(str(tmp_path / "a.json"))
    first = tr.record(W_NOW, 100000.0, equity=100000.0, initial_balance=100000.0,
                      daily_loss_pct=0.05, account_id=123,
                      cold_start_evidence_fn=lambda: _ev(current_balance=100000.0))
    assert first["anchor_source"] == R.SOURCE_BROKER_HISTORY
    # a later call the same day with different current balance must REUSE, not recompute
    second = tr.record(W_NOW + timedelta(hours=1), 90000.0, equity=90000.0,
                       initial_balance=100000.0, daily_loss_pct=0.05, account_id=123,
                       cold_start_evidence_fn=lambda: _ev(current_balance=90000.0))
    assert second["day_start_balance"] == 100000.0


def test_U25_reconstructed_anchor_reused_after_restart(tmp_path):
    p = str(tmp_path / "a.json")
    tr = DailyAnchorTracker(p)
    tr.record(W_NOW, 100000.0, equity=100000.0, initial_balance=100000.0,
              daily_loss_pct=0.05, account_id=123,
              cold_start_evidence_fn=lambda: _ev(current_balance=100000.0))
    tr2 = DailyAnchorTracker(p)                         # restart reloads persisted record
    got = tr2.record(W_NOW + timedelta(hours=2), 80000.0, equity=80000.0,
                     initial_balance=100000.0, daily_loss_pct=0.05, account_id=123,
                     cold_start_evidence_fn=lambda: _ev(current_balance=80000.0))
    assert got["day_start_balance"] == 100000.0 and got["anchor_source"] == R.SOURCE_BROKER_HISTORY


def test_U26_persisted_anchor_wins_reconstruction_never_overwrites(tmp_path):
    tr = DailyAnchorTracker(str(tmp_path / "a.json"))
    tr._records[W_TDAY] = _seed_rec(W_TDAY, 100000.0, 100000.0)
    # even if reconstruction WOULD compute a different value, the persisted anchor wins
    got = tr.record(W_NOW, 100000.0, equity=100000.0, initial_balance=100000.0,
                    daily_loss_pct=0.05, account_id=123,
                    cold_start_evidence_fn=lambda: _ev(current_balance=123456.0,
                        deals=[_deal(datetime(2026, 1, 7, 9, 0, tzinfo=UTC), dtype=1,
                                     entry=1, profit=23456.0, pid=1)]))
    assert got["day_start_balance"] == 100000.0


# =========================================================================== #
# U27–U29, R: timezone / DST (via provider midnight computation)
# =========================================================================== #
def test_U27_cet_winter_boundary_via_provider(tmp_path):
    # a position-less commission deal at Prague 00:30 CET (2026-01-06 23:30Z) is AFTER
    # midnight -> counted (flat book: no position legs). Proves the CET boundary.
    c = _client(balance=99900.0)
    c.add_deal(0, 0, 0.0, 0.0, deal_type=mc.DEAL_TYPE_COMMISSION,
               time=int(datetime(2026, 1, 6, 23, 30, tzinfo=UTC).timestamp()), profit=-100.0)
    snap = _provider(c, tmp_path).snapshot(W_NOW)
    assert snap["daily_anchor_unavailable"] is False
    assert snap["day_start_balance"] == 100000.0       # 99900 - (-100)


def test_U28_cest_summer_boundary_via_provider(tmp_path):
    # summer Prague-00:00 = 22:00Z prev day; a deal at 22:30Z is AFTER midnight -> counted.
    # If the boundary wrongly used the winter offset (23:00Z), this deal would be missed.
    c = _client(balance=99900.0)
    c.add_deal(0, 0, 0.0, 0.0, deal_type=mc.DEAL_TYPE_COMMISSION,
               time=int(datetime(2026, 7, 6, 22, 30, tzinfo=UTC).timestamp()), profit=-100.0)
    snap = _provider(c, tmp_path).snapshot(S_NOW)
    assert snap["daily_anchor_unavailable"] is False
    assert snap["day_start_balance"] == 100000.0


def test_R_spring_dst_transition_day_boundary(tmp_path):
    # 2026-03-29 is the spring-forward day (CET->CEST at 02:00 Prague). Prague midnight
    # is still 00:00 CET = 2026-03-28 23:00Z. A commission at 23:30Z is after midnight.
    c = _client(balance=99950.0)
    c.add_deal(0, 0, 0.0, 0.0, deal_type=mc.DEAL_TYPE_COMMISSION,
               time=int(datetime(2026, 3, 28, 23, 30, tzinfo=UTC).timestamp()), profit=-50.0)
    now = datetime(2026, 3, 29, 10, 0, tzinfo=UTC)
    snap = _provider(c, tmp_path).snapshot(now)
    assert snap["daily_anchor_unavailable"] is False and snap["day_start_balance"] == 100000.0


def test_R_autumn_dst_transition_day_boundary(tmp_path):
    # 2026-10-25 is the fall-back day (CEST->CET at 03:00 Prague). Prague midnight is
    # still 00:00 CEST = 2026-10-24 22:00Z. A commission at 22:30Z is after midnight.
    c = _client(balance=99950.0)
    c.add_deal(0, 0, 0.0, 0.0, deal_type=mc.DEAL_TYPE_COMMISSION,
               time=int(datetime(2026, 10, 24, 22, 30, tzinfo=UTC).timestamp()), profit=-50.0)
    now = datetime(2026, 10, 25, 10, 0, tzinfo=UTC)
    snap = _provider(c, tmp_path).snapshot(now)
    assert snap["daily_anchor_unavailable"] is False and snap["day_start_balance"] == 100000.0


def test_U29_pre_midnight_deal_excluded(tmp_path):
    # a deal 30 min BEFORE Prague midnight (winter 22:30Z) must NOT be counted
    c = _client(balance=99900.0)
    c.add_deal(1, mc.DEAL_ENTRY_IN, 0.1, 1.1, deal_type=0,
               time=int(datetime(2026, 1, 6, 22, 30, tzinfo=UTC).timestamp()), profit=0.0)
    # position from before midnight, still open now -> spans midnight -> fail closed
    c.positions = [SimpleNamespace(ticket=1, symbol="EURUSD",
                                   time=int(datetime(2026, 1, 6, 22, 30, tzinfo=UTC).timestamp()))]
    snap = _provider(c, tmp_path).snapshot(W_NOW)
    assert snap["daily_anchor_unavailable"] is True     # open across midnight -> fail closed


# =========================================================================== #
# Q: deterministic cross-check (forward -> reconstruct backward -> original)
# =========================================================================== #
@pytest.mark.parametrize("events,expected_net", [
    ([], 0.0),
    ([("close", 800.0, -7.0)], 793.0),
    ([("close", -500.0, -7.0)], -507.0),
    ([("close", 300.0, -4.0), ("close", -100.0, -2.0)], 194.0),
    ([("deposit", 5000.0, 0.0)], 5000.0),
    ([("withdraw", -2000.0, 0.0)], -2000.0),
])
def test_Q_cross_check_reconstruct_backward(events, expected_net):
    ANCHOR = 100000.0
    deals = []
    for i, (kind, profit, comm) in enumerate(events):
        if kind == "close":
            deals.append(_deal(datetime(2026, 1, 7, 8 + i, 0, tzinfo=UTC), dtype=1,
                               entry=1, profit=profit, commission=comm, pid=100 + i))
            deals.append(_deal(datetime(2026, 1, 7, 8 + i, 0, tzinfo=UTC) - timedelta(minutes=30),
                               dtype=0, entry=0, profit=0.0, pid=100 + i))  # IN today (flat)
        else:
            dt = 2 if kind == "deposit" else 2
            deals.append(_deal(datetime(2026, 1, 7, 8 + i, 0, tzinfo=UTC), dtype=dt,
                               entry=0, profit=profit, pid=0))
    current_balance = ANCHOR + expected_net
    f, r = _rc(_ev(current_balance=current_balance, deals=deals))
    assert r is None
    assert abs(f["day_start_balance"] - ANCHOR) < 1e-9   # backward reconstruction == original


# =========================================================================== #
# V: adversarial safety proofs
# =========================================================================== #
def test_V1_restart_cannot_reset_anchor(tmp_path):
    # same as U2/U25 in spirit: a restart mid-day with a LOSS cannot reset the anchor
    p = str(tmp_path / "a.json")
    tr = DailyAnchorTracker(p)
    tr.record(W_NOW, 100000.0, equity=100000.0, initial_balance=100000.0,
              daily_loss_pct=0.05, account_id=123, cold_start_evidence_fn=lambda: _ev())
    tr2 = DailyAnchorTracker(p)
    got = tr2.record(W_NOW + timedelta(hours=1), 96000.0, equity=96000.0,
                     initial_balance=100000.0, daily_loss_pct=0.05, account_id=123,
                     cold_start_evidence_fn=lambda: _ev(current_balance=96000.0,
                         deals=[_deal(datetime(2026, 1, 7, 9, 0, tzinfo=UTC), dtype=1,
                                      entry=1, profit=-4000.0, pid=7)]))
    # anchor stays 100000 (intraday loss preserved), NOT reset to 96000
    assert got["day_start_balance"] == 100000.0


def test_V2_V3_current_balance_equity_never_anchor_without_proof():
    # no history -> cannot become anchor from current balance/equity
    f, r = _rc(_ev(history_ok=False, current_balance=100000.0))
    assert f is None


def test_V4_initial_capital_is_not_the_daily_anchor():
    # reconstruction output is derived from history math, not the initial_balance input
    f, r = _rc(_ev(current_balance=97000.0, deals=_closed_trade(1, profit=-3000.0, buy=False)))
    assert r is None and f["day_start_balance"] == 100000.0   # from history, not "initial"


def test_V5_missing_history_never_yields_anchor():
    assert _rc(_ev(history_ok=False))[0] is None


def test_V6_unknown_event_never_ignored():
    d = [_deal(datetime(2026, 1, 7, 9, 0, tzinfo=UTC), dtype=42, entry=0, profit=5.0, pid=0)]
    assert _rc(_ev(deals=d))[0] is None


def test_V8_another_accounts_anchor_never_reused():
    assert _rc(_ev(account_id=777), acct=123)[0] is None


def test_V11_reconstruction_preserves_ftmo_daily_reference():
    # a reconstructed anchor feeds ftmo_levels EXACTLY like a live one (max(bal,eq))
    f, r = _rc(_ev(current_balance=100000.0))
    acct = {"day_start_balance": f["day_start_balance"],
            "day_start_equity": f["day_start_equity"]}
    profile = SimpleNamespace(initial_balance=100000.0, daily_loss_pct=0.05, maximum_loss_pct=0.10)
    lv = ftmo_levels(acct, profile, FtmoConfig())
    assert lv["official_daily_level"] == 100000.0 - 0.05 * 100000.0   # 95000, unchanged formula


def test_V12_anchor_module_has_no_sizing_coupling():
    src = (REPO_ROOT / "forex_swing_orb" / "live" / "providers.py").read_text()
    assert "allowable_volume" not in src and "candidate_risk_amount" not in src


# =========================================================================== #
# helpers
# =========================================================================== #
def _seed_rec(tday, bal, eq):
    rec = {"anchor_schema_version": 2, "trading_day": tday, "timezone": "Europe/Prague",
           "anchor_source": R.SOURCE_LIVE_ROLLOVER, "day_start_balance": float(bal),
           "day_start_equity": float(eq), "initial_balance": 100000.0, "daily_loss_pct": 0.05}
    rec["integrity_digest"] = serialize.compute_integrity_digest(rec)
    return rec
