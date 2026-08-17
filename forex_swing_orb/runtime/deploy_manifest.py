"""Canonical Session Edge deployment-file authority (installation/PR-3S).

The repository is a two-project monorepo (Session Edge under ``forex_swing_orb/``
plus the separate, quarantined **Phantom** system — see
docs/SESSION_EDGE_PHANTOM_SEPARATION.md). This module is the ONE place that decides
exactly which files constitute a Session Edge deployment to the Windows/MT5 machine,
so "fast update" copies a deterministic, minimal, Phantom-free set.

It is pure and read-only: it enumerates and filters paths; it copies nothing, runs
nothing, and has zero trade authority. It never lists runtime state (the bridge /
runtime dirs live under the terminal's ``MQL5\\Files\\`` on the target, never in the
repo) and never lists secrets.
"""

from __future__ import annotations

from pathlib import Path

# The Session Edge runtime lives entirely in this package (producer, manager,
# newsfeed, runtime launcher, live MT5 client, compliance, bridge, position,
# session, ea_mt5 EA source, and the frozen engine under run_dir/code/).
INCLUDE_DIRS = ("forex_swing_orb",)

# Operator launchers at the repo root (Session Edge only).
INCLUDE_ROOT_FILES = (
    "run_session_edge.bat", "autostart_run.bat",
    "setup_autostart.bat", "remove_autostart.bat",
)

# Dirs (by name, at any depth) never deployed.
EXCLUDE_DIR_NAMES = frozenset({"__pycache__", "tests", ".git"})

# Path prefixes (repo-relative, POSIX) never deployed.
#   research/  — analytics; deletable without affecting trading (not needed at runtime).
#   phantom/   — separate quarantined system (PR-3R).
EXCLUDE_PREFIXES = ("forex_swing_orb/research/", "phantom/")

# Root files that belong to Phantom or are not part of a Session Edge deployment.
EXCLUDE_ROOT_FILES = frozenset({
    "phantom_institutional.py", "run_demo.py", "validate.py",
    "README.md", "AUDIT.md", "RELEASE.md",           # these root docs describe Phantom
})

# Never bundle caches, logs, or local state artifacts.
EXCLUDE_SUFFIXES = (".pyc", ".pyo", ".pyd", ".log", ".jsonl", ".ex5")

# Secret-shaped filenames are never deployed (MT5 password is an env var only).
SECRET_HINTS = ("secret", "password", "credential", ".env", ".key", ".pem", ".pfx")

# Live runtime-state directory names — created under the terminal Files folder on the
# target, never present in the repo and never copied (so a deploy cannot destroy the
# bridge pending/claimed/results or execution_outcome / anchor history).
RUNTIME_STATE_DIR_NAMES = frozenset({"session_edge_bridge", "session_edge_runtime"})


def _rel(p, root):
    return p.relative_to(root).as_posix()


def is_deployment_path(rel_posix):
    """True iff a repo-relative POSIX path belongs on the trading machine."""
    parts = rel_posix.split("/")
    if any(seg in EXCLUDE_DIR_NAMES for seg in parts):
        return False
    if any(seg in RUNTIME_STATE_DIR_NAMES for seg in parts):
        return False
    if rel_posix.startswith(EXCLUDE_PREFIXES):
        return False
    low = rel_posix.lower()
    if low.endswith(EXCLUDE_SUFFIXES):
        return False
    if any(h in low for h in SECRET_HINTS):
        return False
    top = parts[0]
    if top in EXCLUDE_ROOT_FILES:
        return False
    if len(parts) == 1:                              # a root file
        return rel_posix in INCLUDE_ROOT_FILES
    return top in INCLUDE_DIRS


def deployment_files(repo_root):
    """Deterministic, sorted list of repo-relative POSIX paths to deploy. Pure scan
    of the include set with the exclusion rules applied (no copy, no side effects)."""
    root = Path(repo_root)
    out = set()
    for name in INCLUDE_ROOT_FILES:
        p = root / name
        if p.is_file() and is_deployment_path(name):
            out.add(name)
    for d in INCLUDE_DIRS:
        base = root / d
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            rel = _rel(p, root)
            if is_deployment_path(rel):
                out.add(rel)
    return sorted(out)


def manifest_summary(repo_root):
    """A small human/machine summary for the runbook and preflight."""
    files = deployment_files(repo_root)
    return {
        "file_count": len(files),
        "include_dirs": list(INCLUDE_DIRS),
        "include_root_files": list(INCLUDE_ROOT_FILES),
        "excluded_prefixes": list(EXCLUDE_PREFIXES),
        "excluded_root_files": sorted(EXCLUDE_ROOT_FILES),
        "phantom_excluded": not any(f.startswith("phantom") for f in files),
        "tests_excluded": not any("/tests/" in f or f.endswith("/tests") for f in files),
    }
