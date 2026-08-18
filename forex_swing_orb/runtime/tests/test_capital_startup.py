"""Zero-friction startup: canonical capital-base persistence + no risk regression.

Proves the new automatic capital-base layer (runtime/capital.py + launcher wiring)
keeps `initial_balance` a PINNED FTMO starting-capital value — captured once per
account, never drifting with the live balance across restarts (H3), never inheriting
another account's base — and that it changes NO risk/FTMO/PR-3J formula or authority.
Pure/off-terminal; imports no MetaTrader5.
"""

from __future__ import annotations

import re
from pathlib import Path

from forex_swing_orb.runtime import capital as C
from forex_swing_orb.runtime import launcher as L

REPO = Path(__file__).resolve().parents[3]
PKG = REPO / "forex_swing_orb"
KW = dict(login=12345678, server="FTMO-Demo", currency="USD")


def _store(tmp):
    return C.CapitalBaseStore(tmp / "capital_base.json")


# --------------------------------------------------------------------------- #
# capital store + resolver
# --------------------------------------------------------------------------- #
def test_first_run_captures_and_pins_current_balance(tmp_path):
    s = _store(tmp_path)
    r = C.resolve_capital_base(s, current_balance=100000.0, cli_initial=None,
                               reinitialize=None, now_iso="t", **KW)
    assert r.ok and r.initial_balance == 100000.0 and r.source == C.SOURCE_FIRST_INIT
    assert s.get(C.account_key(KW["login"], KW["server"]))["initial_balance"] == 100000.0


def test_restart_keeps_pinned_base_despite_balance_change_H3(tmp_path):
    s = _store(tmp_path)
    C.resolve_capital_base(s, current_balance=100000.0, cli_initial=None,
                           reinitialize=None, now_iso="t", **KW)
    for live in (91000.0, 108000.0, 50000.0):        # drawdown / profit — must NOT drift
        r = C.resolve_capital_base(s, current_balance=live, cli_initial=None,
                                   reinitialize=None, now_iso="t", **KW)
        assert r.ok and r.initial_balance == 100000.0 and r.persisted is False


def test_explicit_initial_balance_first_run_pins_and_ignores_live(tmp_path):
    s = _store(tmp_path)
    r = C.resolve_capital_base(s, current_balance=93000.0, cli_initial=50000.0,
                               reinitialize=None, now_iso="t", **KW)
    assert r.ok and r.initial_balance == 50000.0 and r.source == C.SOURCE_CLI


def test_conflicting_cli_after_pin_fails_closed(tmp_path):
    s = _store(tmp_path)
    C.resolve_capital_base(s, current_balance=100000.0, cli_initial=None,
                           reinitialize=None, now_iso="t", **KW)
    r = C.resolve_capital_base(s, current_balance=100000.0, cli_initial=50000.0,
                               reinitialize=None, now_iso="t", **KW)
    assert r.ok is False and r.reason == "CAPITAL BASE CONFLICT"
    # the pinned value is untouched by a refused conflict
    assert s.get(C.account_key(KW["login"], KW["server"]))["initial_balance"] == 100000.0


def test_reinitialize_overwrites_deliberately(tmp_path):
    s = _store(tmp_path)
    C.resolve_capital_base(s, current_balance=100000.0, cli_initial=None,
                           reinitialize=None, now_iso="t", **KW)
    r = C.resolve_capital_base(s, current_balance=100000.0, cli_initial=None,
                               reinitialize=50000.0, now_iso="t", **KW)
    assert r.ok and r.initial_balance == 50000.0 and r.source == C.SOURCE_REINIT


def test_account_change_never_inherits_previous_base(tmp_path):
    s = _store(tmp_path)
    C.resolve_capital_base(s, current_balance=100000.0, cli_initial=None,
                           reinitialize=None, now_iso="t", **KW)
    other = dict(login=99999999, server="FTMO-Demo", currency="USD")
    r = C.resolve_capital_base(s, current_balance=25000.0, cli_initial=None,
                               reinitialize=None, now_iso="t", **other)
    assert r.ok and r.initial_balance == 25000.0            # new account's own base
    assert "ACCOUNT CHANGED" in r.message
    # first account's base is still intact and separate
    assert s.get(C.account_key(12345678, "FTMO-Demo"))["initial_balance"] == 100000.0


def test_missing_identity_fails_closed(tmp_path):
    s = _store(tmp_path)
    r = C.resolve_capital_base(s, login=None, server="FTMO-Demo", currency="USD",
                               current_balance=100000.0, cli_initial=None,
                               reinitialize=None, now_iso="t")
    assert r.ok is False and "ACCOUNT IDENTITY" in r.reason


def test_no_balance_and_no_cli_fails_closed(tmp_path):
    s = _store(tmp_path)
    r = C.resolve_capital_base(s, current_balance=None, cli_initial=None,
                               reinitialize=None, now_iso="t", **KW)
    assert r.ok is False and r.reason == "CAPITAL BASE NOT ESTABLISHED"


def test_malformed_store_fails_closed(tmp_path):
    p = tmp_path / "capital_base.json"
    p.write_text("{ not json", encoding="utf-8")
    import pytest
    with pytest.raises(C.CapitalBaseError):
        C.CapitalBaseStore(p).get(C.account_key(1, "s"))


def test_record_account_mismatch_fails_closed(tmp_path):
    s = _store(tmp_path)
    C.resolve_capital_base(s, current_balance=100000.0, cli_initial=None,
                           reinitialize=None, now_iso="t", **KW)
    # tamper: swap the record under a different key -> account_key mismatch
    import json
    data = json.loads((tmp_path / "capital_base.json").read_text())
    rec = list(data["records"].values())[0]
    data["records"] = {"999@other": rec}                    # key no longer matches record.account_key
    (tmp_path / "capital_base.json").write_text(json.dumps(data))
    import pytest
    with pytest.raises(C.CapitalBaseError):
        s.get("999@other")


def test_mask_account_never_exposes_full_login():
    assert C.mask_account(12345678) == "***5678"
    assert C.mask_account(None) == "****"


# --------------------------------------------------------------------------- #
# bridge handshake (no trade)
# --------------------------------------------------------------------------- #
def test_bridge_handshake_readwrite_and_no_probe_left(tmp_path):
    root = tmp_path / "session_edge_bridge"
    ok, detail = L.bridge_handshake(str(root), "2026-08-17T00:00:00Z")
    assert ok, detail
    assert not (root / "health" / "startup_probe.json").exists()   # cleaned up
    # probe is written under health/, NEVER into outbox/pending (EA never sees it)
    assert list((root / "outbox" / "pending").iterdir()) == []


# --------------------------------------------------------------------------- #
# launcher surface
# --------------------------------------------------------------------------- #
def test_launcher_initial_balance_optional_and_reinitialize_present():
    src = (PKG / "runtime" / "launcher.py").read_text()
    assert 'add_argument("--initial-balance"' in src and 'default=None' in src
    assert 'add_argument("--reinitialize"' in src
    # normal .bat use passes no capital args
    bat = (REPO / "run_session_edge.bat").read_text()
    assert "--ftmo-verified" in bat
    assert "--initial-balance" not in bat.split("python -m")[1].split("%*")[0]


def test_launcher_children_unchanged():
    assert L.CHILDREN == ("forex_swing_orb.newsfeed", "forex_swing_orb.producer",
                          "forex_swing_orb.manage")


def test_resolve_initial_balance_still_pins_and_ignores_live_H3():
    # the original H3 helper is unchanged (still ignores the live balance)
    assert L.resolve_initial_balance(50000, live_balance=47000) == 50000.0
    assert L.resolve_initial_balance(50000, live_balance=52000) == 50000.0
    assert L.resolve_initial_balance(None) is None


# --------------------------------------------------------------------------- #
# risk-semantic no-regression proofs (Section O)
# --------------------------------------------------------------------------- #
def test_pr3j_remains_sole_lot_authority():
    owners = [str(p.relative_to(REPO)) for p in PKG.rglob("*.py")
              if "/tests/" not in str(p) and re.search(r"^def allowable_volume\(", p.read_text(), re.M)]
    assert owners == ["forex_swing_orb/compliance/sizing.py"]


def test_candidate_risk_amount_formula_unchanged():
    src = (PKG / "compliance" / "contract.py").read_text()
    # permitted per-trade risk is still initial_balance * risk_fraction (unchanged)
    assert "def candidate_risk_amount(" in src
    assert "return initial * rf" in src


def test_capital_layer_does_not_import_or_call_risk_sizing_ftmo():
    # prose in the docstring may name them; the CODE must never import/call them.
    src = (PKG / "runtime" / "capital.py").read_text()
    assert not re.search(r"^\s*(import|from)\s+.*(sizing|compliance)", src, re.M)
    for call in ("allowable_volume(", "candidate_risk_amount(", "ftmo_levels(",
                 "risk_within_limit("):
        assert call not in src


def test_ea_no_manual_lot_input_and_no_score_sizing():
    ea = (PKG / "ea_mt5" / "SessionEdgeExecutionEA.mq5").read_text()
    # The EA exposes NO manual lot/volume/risk INPUT (the misleading DefaultVolume input
    # was removed). Sizing is autonomous (PR-3J); the EA executes the authorized volume.
    import re as _re
    assert not _re.search(r"^\s*input\s+\w+\s+\w*(?:[Vv]olume|[Ll]ot|[Rr]isk)\w*", ea, _re.M)
    assert "input double DefaultVolume" not in ea
    # no score-based sizing anywhere in trading
    for pkg in ("compliance", "producer", "ea_mt5", "runtime"):
        for p in (PKG / pkg).rglob("*.py"):
            if "/tests/" in str(p):
                continue
            assert "trade_score" not in p.read_text()
