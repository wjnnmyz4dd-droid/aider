"""Installation tooling tests: deployment manifest + read-only preflight + launcher.

Proves the additive install/deploy support tooling is correct and safe:
Phantom/tests/secrets/runtime-state are excluded from deployment; the preflight is
read-only (no order/instruction/child-process side effects) and never falsely green;
the launcher starts only Session Edge children. No trading behavior is touched.
"""

from __future__ import annotations

import re
from pathlib import Path

from forex_swing_orb.runtime import deploy_manifest as M
from forex_swing_orb.runtime import preflight as P

REPO = Path(__file__).resolve().parents[3]
RT = REPO / "forex_swing_orb" / "runtime"


# --------------------------------------------------------------------------- #
# deployment manifest
# --------------------------------------------------------------------------- #
def test_manifest_excludes_phantom_tests_caches_research_secrets():
    files = M.deployment_files(REPO)
    assert files, "manifest produced no files"
    assert not any(f.startswith("phantom") for f in files)          # phantom/ + phantom_institutional.py
    assert "phantom_institutional.py" not in files
    assert not any("/tests/" in f or f.endswith("/tests") for f in files)
    assert not any("__pycache__" in f or f.endswith((".pyc", ".pyo")) for f in files)
    assert not any(f.startswith("forex_swing_orb/research/") for f in files)  # not needed at runtime
    assert not any(h in f.lower() for f in files for h in M.SECRET_HINTS)
    # Phantom root docs/scripts excluded
    for banned in ("run_demo.py", "validate.py", "README.md", "AUDIT.md", "RELEASE.md"):
        assert banned not in files


def test_manifest_includes_required_runtime_and_ea_and_launchers():
    files = set(M.deployment_files(REPO))
    required = {
        "run_session_edge.bat", "autostart_run.bat",
        "forex_swing_orb/runtime/launcher.py",
        "forex_swing_orb/producer/runner.py",
        "forex_swing_orb/manage/service.py",
        "forex_swing_orb/newsfeed/service.py",
        "forex_swing_orb/compliance/sizing.py",
        "forex_swing_orb/position/geometry.py",
        "forex_swing_orb/bridge/paths.py",
        "forex_swing_orb/live/mt5_client.py",
        "forex_swing_orb/ea_mt5/SessionEdgeExecutionEA.mq5",
        "forex_swing_orb/ea_mt5/JsonBridge.mqh",
        "forex_swing_orb/ea_mt5/SessionEdgeManageHandler.mqh",
        "forex_swing_orb/run_dir/code/signal_engine.py",
    }
    missing = required - files
    assert not missing, f"deployment manifest missing required files: {sorted(missing)}"


def test_manifest_never_lists_runtime_state_or_secrets():
    files = M.deployment_files(REPO)
    for f in files:
        assert "session_edge_bridge" not in f and "session_edge_runtime" not in f
    # predicate rejects secret-shaped + runtime-state paths deterministically
    assert not M.is_deployment_path("forex_swing_orb/secret_password.py")
    assert not M.is_deployment_path("something/session_edge_bridge/outbox/pending/x.json")
    assert not M.is_deployment_path("forex_swing_orb/runtime/config.env")


def test_manifest_summary_flags():
    s = M.manifest_summary(REPO)
    assert s["phantom_excluded"] is True and s["tests_excluded"] is True
    assert s["file_count"] == len(M.deployment_files(REPO))


# --------------------------------------------------------------------------- #
# preflight (read-only)
# --------------------------------------------------------------------------- #
def test_preflight_runs_readonly_and_returns_valid_statuses():
    results = P.run_checks()
    assert results, "preflight produced no checks"
    allowed = {P.PASS, P.FAIL, P.ENV}
    for name, status, detail in results:
        assert status in allowed, (name, status)
        assert isinstance(detail, str)


def test_preflight_no_false_green_without_terminal():
    # Off the Windows/MT5 terminal these MUST be ENV (never PASS, never FAIL).
    by = {name: status for name, status, _ in P.run_checks()}
    assert by["import MetaTrader5"] == P.ENV
    assert by["MT5 terminal connection"] == P.ENV
    assert by["DEMO account"] == P.ENV
    assert by["B2 MT5 time-base is UTC"] == P.ENV


def test_preflight_core_env_checks_pass_here():
    by = {name: status for name, status, _ in P.run_checks()}
    assert by["Python >= 3.9"] == P.PASS
    assert by["import pandas"] == P.PASS and by["import numpy"] == P.PASS
    assert by["timezone data (zoneinfo/tzdata)"] == P.PASS


def test_preflight_overall_exit_codes():
    assert P._overall([("a", P.PASS, "")]) == (P.PASS, 0)
    assert P._overall([("a", P.PASS, ""), ("b", P.ENV, "")]) == (P.ENV, 2)
    assert P._overall([("a", P.ENV, ""), ("b", P.FAIL, "")]) == (P.FAIL, 1)


def test_preflight_is_readonly_no_trade_or_process_surface():
    # check CODE call-patterns (paren-suffixed), not the docstring which describes
    # what the module deliberately never does.
    src = (RT / "preflight.py").read_text()
    for banned in ("order_send(", ".order_send", "OrderSend(", "write_instruction(",
                   "Popen(", "subprocess.", "os.system(", ".mkdir(", "atomic_write(",
                   ".ensure("):
        assert banned not in src, f"preflight must be read-only; found {banned!r}"


def test_preflight_reuses_canonical_authorities_not_reimplemented():
    src = (RT / "preflight.py").read_text()
    # composes existing owners rather than re-deriving any gate math
    assert "from .config import load_config" in src
    assert "providers" in src and "validate" in src.lower()  # references producer validators (docstring/uses)
    assert "metadata_ok" in src            # reuses compliance.sizing
    assert "bridge.paths" in src or "BridgePaths" in src


def test_install_tooling_does_not_import_phantom():
    for mod in ("preflight.py", "deploy_manifest.py"):
        src = (RT / mod).read_text()
        assert not re.search(r"^\s*(import|from)\s+phantom", src, re.M)


# --------------------------------------------------------------------------- #
# launcher correctness (Session Edge only)
# --------------------------------------------------------------------------- #
def test_launcher_starts_only_session_edge_children():
    from forex_swing_orb.runtime import launcher as L
    assert L.CHILDREN == ("forex_swing_orb.newsfeed", "forex_swing_orb.producer",
                          "forex_swing_orb.manage")
    assert not any("phantom" in c for c in L.CHILDREN)
