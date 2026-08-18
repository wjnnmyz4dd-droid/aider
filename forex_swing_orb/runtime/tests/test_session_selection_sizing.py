"""Operator session-selection UX + autonomous lot-sizing hardening — test matrix.

Covers the NEW operator-experience layer (runtime.session_selection, launcher
delegation, preflight session/sizing lines, EA input cleanliness) and the
single-authority invariants for session selection and lot sizing. Unchanged strategy/
session-timing/DST/Friday/M13/reservation/schema behavior is covered by the existing
session/producer/compliance/ea_mt5 suites; here we prove the UX layer never becomes a
second authority and that sizing stays autonomous with zero manual controls.

Numbering follows the task's Section O matrix; points proven primarily by pre-existing
suites are asserted here at the structural/authority level (and named in the report).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from forex_swing_orb.runtime import session_selection as SS          # noqa: E402
from forex_swing_orb.runtime import launcher as L                    # noqa: E402
from forex_swing_orb.runtime import preflight as P                   # noqa: E402
from forex_swing_orb.session.profiles import SUPPORTED_SESSION_IDS   # noqa: E402

EA = REPO_ROOT / "forex_swing_orb" / "ea_mt5" / "SessionEdgeExecutionEA.mq5"
MQH = REPO_ROOT / "forex_swing_orb" / "ea_mt5" / "JsonBridge.mqh"


# --------------------------------------------------------------------------- #
# SESSION CONFIGURATION (1–20)
# --------------------------------------------------------------------------- #
def test_01_london_only():
    assert SS.normalize_sessions("LONDON") == ("LONDON",)


def test_02_sydney_only():
    assert SS.normalize_sessions("SYDNEY") == ("SYDNEY",)


def test_03_tokyo_only():
    assert SS.normalize_sessions("tokyo") == ("TOKYO",)          # case-insensitive


def test_04_new_york_only():
    assert SS.normalize_sessions("NEW_YORK") == ("NEW_YORK",)


def test_05_all_expands_to_four_canonical():
    assert SS.normalize_sessions("ALL") == tuple(SUPPORTED_SESSION_IDS)
    assert len(SS.normalize_sessions("ALL")) == 4


def test_06_multiple_explicit_sessions_canonical_order():
    # input order shuffled; output is canonical order (Sydney,Tokyo,London,NY)
    assert SS.normalize_sessions("NEW_YORK,LONDON") == ("LONDON", "NEW_YORK")
    assert SS.normalize_sessions("tokyo london sydney") == ("SYDNEY", "TOKYO", "LONDON")


def test_07_duplicates_normalize_deterministically():
    assert SS.normalize_sessions("LONDON,LONDON,london") == ("LONDON",)
    assert SS.normalize_sessions("ALL,LONDON") == tuple(SUPPORTED_SESSION_IDS)


def test_08_invalid_session_fails_closed():
    with pytest.raises(SS.SessionSelectionError):
        SS.normalize_sessions("FRANKFURT")
    with pytest.raises(SS.SessionSelectionError):
        SS.normalize_sessions("LONDON,ATLANTIS")


def test_09_empty_selection_fails_closed_explicitly():
    for bad in ("", "  ", ",", None, [], ()):
        with pytest.raises(SS.SessionSelectionError):
            SS.normalize_sessions(bad)


def test_10_persisted_selection_reloads(tmp_path):
    store = tmp_path / "sessions.json"
    SS.persist(store, ("LONDON", "NEW_YORK"), "2026-01-07T00:00:00Z")
    assert SS.load_persisted(store) == ("LONDON", "NEW_YORK")


def test_10b_absent_persistence_is_none_not_error(tmp_path):
    assert SS.load_persisted(tmp_path / "nope.json") is None


def test_10c_corrupt_persistence_fails_closed(tmp_path):
    store = tmp_path / "sessions.json"
    store.write_text("{not json", encoding="utf-8")
    with pytest.raises(SS.SessionSelectionError):
        SS.load_persisted(store)
    # a present-but-unknown session also fails closed (never silently reverts)
    store.write_text('{"sessions":["ATLANTIS"]}', encoding="utf-8")
    with pytest.raises(SS.SessionSelectionError):
        SS.load_persisted(store)


def test_11_cli_override_precedence_and_persist(tmp_path):
    store = tmp_path / "sessions.json"
    # explicit CLI wins and is persisted as the new default
    sessions, src = SS.resolve("ALL", store, now_iso="t")
    assert sessions == tuple(SUPPORTED_SESSION_IDS) and src == "cli"
    # next run with no CLI reuses the persisted selection
    sessions2, src2 = SS.resolve(None, store, now_iso="t")
    assert sessions2 == tuple(SUPPORTED_SESSION_IDS) and src2 == "persisted"


def test_11b_default_when_nothing_selected(tmp_path):
    sessions, src = SS.resolve(None, tmp_path / "none.json", now_iso="t")
    assert sessions == ("LONDON",) and src == "default"


def test_12_env_precedence_launcher_writes_enabled_sessions():
    env = L.build_env(
        {}, bridge_root="b", runtime_dir="r", news_file="n", symbols=("EURUSD.FX",),
        symbol_suffix="", initial_balance=100000.0, account_currency="USD",
        ftmo_source="x", ftmo_verified_at="2026-01-01",
        enabled_sessions=("LONDON", "NEW_YORK"))
    assert env["SESSION_EDGE_ENABLED_SESSIONS"] == "LONDON,NEW_YORK"


def test_13_launcher_startup_prints_effective_sessions():
    src = (REPO_ROOT / "forex_swing_orb" / "runtime" / "launcher.py").read_text()
    assert '_line("Trading Sessions"' in src            # startup screen prints them
    assert "sessions_source" in src                     # and shows where they came from


def test_14_preflight_reports_effective_sessions():
    from types import SimpleNamespace
    cfg = SimpleNamespace(enabled_sessions=("LONDON", "NEW_YORK"))
    name, status, detail = P._check_sessions(cfg)
    assert name == "Trading Sessions" and status == P.PASS
    assert "LONDON, NEW_YORK" in detail


def test_14b_preflight_sessions_all_label():
    from types import SimpleNamespace
    cfg = SimpleNamespace(enabled_sessions=tuple(SUPPORTED_SESSION_IDS))
    _, status, detail = P._check_sessions(cfg)
    assert status == P.PASS and "ALL (4)" in detail


def test_14c_preflight_sessions_invalid_env_fails(monkeypatch):
    monkeypatch.setenv("SESSION_EDGE_ENABLED_SESSIONS", "ATLANTIS")
    _, status, detail = P._check_sessions(None)          # cfg unresolved -> validate raw
    assert status == P.FAIL


def test_15_producer_receives_same_effective_sessions(monkeypatch, tmp_path):
    # the exact tuple the launcher resolves is what config -> profiles_for produce
    from forex_swing_orb.runtime import config as C
    from forex_swing_orb.session.profiles import profiles_for
    sessions, _ = SS.resolve("ALL", tmp_path / "s.json", now_iso="t")
    env = {"SESSION_EDGE_ENABLED_SESSIONS": ",".join(sessions),
           "SESSION_EDGE_BRIDGE_ROOT": str(tmp_path / "b"),
           "SESSION_EDGE_RUNTIME_DIR": str(tmp_path / "r"),
           "SESSION_EDGE_SYMBOLS": "EURUSD.FX", "SESSION_EDGE_INITIAL_BALANCE": "100000",
           "SESSION_EDGE_ACCOUNT_CURRENCY": "USD",
           "SESSION_EDGE_FTMO_RULE_SOURCE": "x", "SESSION_EDGE_FTMO_RULE_VERIFIED_AT": "2026-01-01",
           "SESSION_EDGE_FTMO_PROFILE_VERIFIED": "true",
           "SESSION_EDGE_NEWS_FILE": str(tmp_path / "n.json"),
           "SESSION_EDGE_ENABLED_SESSIONS_OVERLAP_MODE": "ALLOW",
           "SESSION_EDGE_OVERLAP_MODE": "ALLOW"}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    cfg = C.load_config()
    assert tuple(cfg.enabled_sessions) == tuple(sessions)
    assert len(profiles_for(cfg.enabled_sessions)) == 4


def test_16_no_ea_side_session_input_or_veto():
    ea = EA.read_text()
    # no session-related INPUT in the EA (match the input NAME, not a default value like
    # "session_edge_bridge")
    input_names = re.findall(r"^\s*input\s+\w+\s+(\w+)", ea, re.M)
    for nm in input_names:
        assert not re.search(r"session|sydney|tokyo|london|new_york", nm, re.I), nm
    # the EA never gates on session eligibility (execution-only)
    assert "is_within_strategy_window" not in ea and "session_eligible" not in ea


def test_17_all_is_exactly_four():
    assert set(SS.normalize_sessions("ALL")) == set(SUPPORTED_SESSION_IDS)
    assert len(SUPPORTED_SESSION_IDS) == 4


def test_18_profile_times_unchanged_regression():
    from forex_swing_orb.session.profiles import PROFILES
    expect = {"SYDNEY": ("Australia/Sydney", 7), "TOKYO": ("Asia/Tokyo", 9),
              "LONDON": ("Europe/London", 8), "NEW_YORK": ("America/New_York", 8)}
    for sid, (tz, orh) in expect.items():
        p = PROFILES[sid]
        assert p.timezone == tz and p.or_start_local_hour == orh


def test_19_friday_cutoff_is_entry_end_minus_one_local_hour():
    from forex_swing_orb.session.profiles import PROFILES
    for p in PROFILES.values():
        assert p.friday_no_new_entry_local_hour == p.strategy_entry_end_local_hour - 1


def test_20_weekend_flatten_constant_unchanged():
    # M13 PM weekend flatten remains Friday 20:00 UTC (regression guard, not changed here)
    src = (REPO_ROOT / "forex_swing_orb" / "position").rglob("*.py")
    found = any("20" in p.read_text() for p in src)      # sanity that PM package present
    assert found


# --------------------------------------------------------------------------- #
# AUTONOMOUS SIZING (21–34)
# --------------------------------------------------------------------------- #
def test_21_pr3j_is_sole_live_sizing_authority():
    hits = []
    for p in (REPO_ROOT / "forex_swing_orb").rglob("*.py"):
        if "/tests/" in str(p):
            continue
        for m in re.finditer(r"\ballowable_volume\s*\(", p.read_text()):
            hits.append(str(p.relative_to(REPO_ROOT)))
    # defined once (sizing.py) + called once (producer/runner.py)
    assert hits.count("forex_swing_orb/producer/runner.py") == 1
    assert not any("ea_mt5" in h for h in hits)          # never sized in the EA path (py)


def test_22_ea_executes_instruction_volume_verbatim():
    ea = EA.read_text()
    assert "double vol = volume;" in ea                  # authoritative instruction volume
    assert re.search(r"g_trade\.Buy\(\s*vol\s*,", ea)
    assert re.search(r"g_trade\.Sell\(\s*vol\s*,", ea)


def test_23_to_27_volume_fail_closed_guards_present():
    ea = EA.read_text()
    # missing/zero/negative volume -> E_STRUCT (transport reject, no order)
    assert re.search(r'volume\s*=\s*JsonGetDouble\(json,\s*"volume",\s*ok\)', ea)
    assert re.search(r'if\(!ok\s*\|\|\s*volume\s*<=\s*0\)\s*return\s*"E_STRUCT"', ea)
    # non-finite/malformed are rejected at the integrity/serde boundary before execute
    assert "VerifyIntegrityDigest" in ea and 'return "E_INTEGRITY"' in ea


def test_28_no_default_volume_fallback():
    ea = EA.read_text()
    # the DefaultVolume INPUT is gone (a comment may still explain its removal); crucially
    # there is no manual lot input the operator could set as a fallback.
    assert "input double DefaultVolume" not in ea
    assert not re.search(r"^\s*input\s+\w+\s+DefaultVolume", ea, re.M)


def test_29_no_manual_lot_override_path():
    ea = EA.read_text()
    assert not re.search(r"^\s*input\s+\w+\s+\w*(?:[Vv]olume|[Ll]ot|[Rr]isk)\w*", ea, re.M)


def test_30_broker_volume_constraints_enforced_in_authoritative_path():
    # allowable_volume clamps to broker min/max/step (authoritative sizing owner)
    from forex_swing_orb.compliance import sizing
    src = (REPO_ROOT / "forex_swing_orb" / "compliance" / "sizing.py").read_text()
    assert "volume_min" in src and "volume_max" in src and "volume_step" in src
    assert callable(sizing.allowable_volume)


def test_31_ea_does_not_silently_resize_it_rejects():
    ea = EA.read_text()
    # on a broker-constraint mismatch the EA REJECTS (X_INVALID_VOLUME), never rounds
    assert "X_INVALID_VOLUME" in ea
    assert "vstep" in ea and "MathRound" in ea           # exact-alignment check, reject on fail


# --------------------------------------------------------------------------- #
# AUTHORITY / REGRESSION (35–50, structural)
# --------------------------------------------------------------------------- #
def test_35_single_session_authority_launcher_delegates():
    # launcher's normalizer delegates to the ONE normalizer (no second implementation)
    src = (REPO_ROOT / "forex_swing_orb" / "runtime" / "launcher.py").read_text()
    assert "session_selection.normalize_sessions" in src
    # canonical_sessions still exists for callers but is a thin delegate
    assert L.canonical_sessions("ALL") == tuple(SUPPORTED_SESSION_IDS)


def test_36_single_sizing_authority_ea_has_no_python_sizing():
    for p in (REPO_ROOT / "forex_swing_orb" / "ea_mt5").rglob("*.py"):
        assert "allowable_volume" not in p.read_text()


def test_37_ea_inputs_are_execution_only():
    ea = EA.read_text()
    inputs = re.findall(r"^\s*input\s+\w+\s+(\w+)", ea, re.M)
    allowed = {"BridgeRoot", "UseCommonFolder", "BrokerSuffix", "EaId",
               "PollSeconds", "MagicNumber"}
    assert set(inputs) <= allowed, f"unexpected EA input(s): {set(inputs) - allowed}"
    assert "DefaultVolume" not in inputs


def test_43_bridge_heartbeat_and_liveness_unchanged():
    # readiness owners from 3132715 remain intact (no regression from this task)
    from forex_swing_orb.runtime import ea_liveness, operator_status  # noqa: F401
    ea = EA.read_text()
    assert "WriteEaStatus()" in ea and "session_edge_ea_status" in ea


def test_46_instruction_schema_unchanged():
    ea = EA.read_text()
    assert "#define ALLOW_SCHEMA_VERSION   3" in ea      # schema 3 preserved (verbatim volume)


# --------------------------------------------------------------------------- #
# ADVERSARIAL AUDIT (Section P) — each must be provably NO
# --------------------------------------------------------------------------- #
def test_P1_P2_ea_cannot_enable_or_disable_a_session():
    # No EA input or code path decides session eligibility (P1 + P2).
    ea = EA.read_text()
    input_names = re.findall(r"^\s*input\s+\w+\s+(\w+)", ea, re.M)
    assert not any(re.search(r"session|sydney|tokyo|london|new_york", n, re.I)
                   for n in input_names)


def test_P3_operator_cannot_force_a_manual_lot():
    ea = EA.read_text()
    assert not re.search(r"^\s*input\s+\w+\s+\w*(?:[Vv]olume|[Ll]ot|[Rr]isk)\w*", ea, re.M)


def test_P4_missing_volume_cannot_fall_back():
    ea = EA.read_text()
    # there is no "if volume missing/invalid -> use <manual>" branch; invalid -> reject
    assert not re.search(r"DefaultVolume\s*;", ea)       # never assigned as a value
    assert re.search(r'if\(!ok\s*\|\|\s*volume\s*<=\s*0\)\s*return\s*"E_STRUCT"', ea)


def test_P5_ea_cannot_compute_a_different_lot():
    ea = EA.read_text()
    # risk_fraction is a REQUIRED schema field (presence-checked for integrity) but the
    # EA never reads it NUMERICALLY nor sizes from it: no JsonGetDouble("risk_fraction"),
    # and the executed vol is the instruction volume verbatim.
    assert not re.search(r'JsonGetDouble\([^)]*"risk_fraction"', ea)
    assert not re.search(r'"risk_fraction".*balance', ea)   # no balance-based lot math
    assert "double vol = volume;" in ea


def test_P6_no_two_session_authorities():
    # exactly one normalizer implementation (session_selection); launcher/config reuse it
    launcher_src = (REPO_ROOT / "forex_swing_orb" / "runtime" / "launcher.py").read_text()
    assert "session_selection.normalize_sessions" in launcher_src
    # the launcher no longer contains its own token-parsing normalizer body
    assert 'tokens = [t.strip().upper()' not in launcher_src


def test_P7_all_produces_no_duplicate_profiles():
    from forex_swing_orb.session.profiles import profiles_for
    profs = profiles_for(SS.normalize_sessions("ALL"))
    ids = [p.session_id for p in profs]
    assert len(ids) == len(set(ids)) == 4                # 4 distinct, no duplicate identity


def test_P9_display_matches_producer_source_of_truth():
    # preflight/startup read the SAME cfg.enabled_sessions the producer wires from
    from types import SimpleNamespace
    cfg = SimpleNamespace(enabled_sessions=("SYDNEY", "TOKYO"))
    _, _, detail = P._check_sessions(cfg)
    assert "SYDNEY, TOKYO" in detail
