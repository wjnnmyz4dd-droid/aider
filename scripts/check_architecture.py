#!/usr/bin/env python3
"""Architecture check for `phantom_pipeline/` (RPI Research phase,
`.claude/agents/TEAM.md` §9 / `docs/adr/ADR-014-multi-agent-governance.md`
Amendment 1).

Verifies, across every `phantom_pipeline/<package>/`:

1. **No circular imports** between packages.
2. **No cross-package private-state access** — a package may only import
   another package's `.models`, `.trace`, `.registry`, or its
   `__init__.py` public re-exports; never another package's `.engine`,
   `.state_store`, `.config`, `.checks`, `.metrics`, `.logging_sink`,
   `.idempotency_store`, or any other internal module.

This is read-only: it only parses import statements via a regular
expression over already-committed source files. It never imports or
executes `phantom_pipeline` code, and it never modifies anything.

These are exactly the two checks performed by hand during the Phase 1
Certification Audit; this script makes them repeatable rather than
re-derived manually for every future change.

Usage: `python3 scripts/check_architecture.py`
Exit code 0 on a clean architecture, 1 if any violation is found.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = REPO_ROOT / "phantom_pipeline"

# A package may only reach another package's public surface: its own
# __init__.py (bare `from ..other import X`), or these three submodules.
ALLOWED_SUBMODULES = {"models", "trace", "registry"}

_IMPORT_RE = re.compile(r"^from \.\.([a-z0-9_]+)(?:\.([a-z0-9_]+))?\s+import\b", re.MULTILINE)


def discover_packages() -> List[str]:
    return sorted(
        p.name
        for p in PACKAGE_ROOT.iterdir()
        if p.is_dir() and not p.name.startswith("_") and not p.name.startswith(".")
    )


def find_cross_package_imports(package: str) -> List[Tuple[str, str, str]]:
    """Returns (source_file, target_package, target_submodule_or_empty)
    for every cross-package import found in `package`'s own source files."""
    results = []
    package_dir = PACKAGE_ROOT / package
    for path in sorted(package_dir.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for match in _IMPORT_RE.finditer(text):
            target_package, target_submodule = match.group(1), match.group(2) or ""
            results.append((str(path.relative_to(REPO_ROOT)), target_package, target_submodule))
    return results


def build_dependency_graph(packages: List[str]) -> Dict[str, Set[str]]:
    graph: Dict[str, Set[str]] = {p: set() for p in packages}
    for package in packages:
        for _source_file, target_package, _submodule in find_cross_package_imports(package):
            if target_package in graph:
                graph[target_package]  # no-op, keeps intent explicit
                graph[package].add(target_package)
    return graph


def find_cycle(graph: Dict[str, Set[str]]) -> List[str]:
    """Returns one cycle (as a list of package names) if found, else []."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {node: WHITE for node in graph}
    path: List[str] = []

    def visit(node: str) -> List[str]:
        color[node] = GRAY
        path.append(node)
        for neighbor in sorted(graph.get(node, ())):
            if color[neighbor] == GRAY:
                cycle_start = path.index(neighbor)
                return path[cycle_start:] + [neighbor]
            if color[neighbor] == WHITE:
                found = visit(neighbor)
                if found:
                    return found
        path.pop()
        color[node] = BLACK
        return []

    for node in sorted(graph):
        if color[node] == WHITE:
            found = visit(node)
            if found:
                return found
    return []


def find_private_state_violations(packages: List[str]) -> List[str]:
    violations = []
    for package in packages:
        for source_file, target_package, submodule in find_cross_package_imports(package):
            if target_package not in packages:
                continue  # not a phantom_pipeline package (e.g. a stdlib-shaped false positive)
            if submodule and submodule not in ALLOWED_SUBMODULES:
                violations.append(
                    f"{source_file}: imports `{target_package}.{submodule}` — only "
                    f".models/.trace/.registry or {target_package}'s own __init__.py "
                    f"public surface may be imported across a package boundary"
                )
    return violations


def main() -> int:
    packages = discover_packages()
    graph = build_dependency_graph(packages)
    cycle = find_cycle(graph)
    violations = find_private_state_violations(packages)

    print("Architecture check — phantom_pipeline/")
    print("=" * 40)
    print(f"Packages discovered: {len(packages)}")

    ok = True
    if cycle:
        ok = False
        print(f"FAIL  circular import: {' -> '.join(cycle)}")
    else:
        print("PASS  no circular imports")

    if violations:
        ok = False
        print(f"FAIL  {len(violations)} private-state-access violation(s):")
        for violation in violations:
            print(f"      - {violation}")
    else:
        print("PASS  no cross-package private-state access")

    print("=" * 40)
    print("RESULT: PASS" if ok else "RESULT: FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
