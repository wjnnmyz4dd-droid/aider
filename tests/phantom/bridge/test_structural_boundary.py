"""Structural boundary tests (Phase 1) -- verified by source inspection,
never merely asserted in prose. Phase 1 has exactly one component; this
guards against future phases accidentally being wired in before their
own approval, and against `phantom.bridge` ever gaining trading-decision
logic of its own."""

from __future__ import annotations

import inspect
import re
import subprocess
import sys
import unittest
from pathlib import Path

from phantom.bridge.engine import BridgeEngine

REPO_ROOT = Path(__file__).resolve().parents[3]
BRIDGE_DIR = REPO_ROOT / "phantom" / "bridge"

FORBIDDEN_METHOD_NAME_FRAGMENTS = (
    "score_", "decide_risk", "size_position", "generate_signal", "approve_trade",
)


class TestNoDecisionAuthorityMethodNames(unittest.TestCase):
    def test_no_public_method_on_bridge_engine_resembles_a_decision_verb(self):
        for name, _member in inspect.getmembers(BridgeEngine, predicate=inspect.isfunction):
            if name.startswith("_"):
                continue
            lowered = name.lower()
            for forbidden in FORBIDDEN_METHOD_NAME_FRAGMENTS:
                self.assertNotIn(forbidden, lowered, f"BridgeEngine.{name} resembles a forbidden decision verb")


class TestNoImportsBeyondItsOwnPackage(unittest.TestCase):
    """Phase 1 has no scanner/strategy/risk/intelligence/watchdog/config
    package to import from yet -- this test fails loudly the moment
    anyone adds one before it's approved, rather than relying on nobody
    noticing an accidental early coupling."""

    def test_no_file_imports_a_sibling_phantom_package(self):
        pattern = re.compile(r"^from \.\.(?!bridge\b)[a-z0-9_]+|^from phantom\.(?!bridge\b)[a-z0-9_]+", re.MULTILINE)
        violations = []
        for path in BRIDGE_DIR.glob("*.py"):
            if pattern.search(path.read_text(encoding="utf-8")):
                violations.append(str(path))
        self.assertEqual(violations, [], f"phantom/bridge file(s) import a sibling phantom package: {violations}")

    def test_no_file_imports_phantom_pipeline(self):
        pattern = re.compile(r"phantom_pipeline", re.MULTILINE)
        violations = []
        for path in BRIDGE_DIR.glob("*.py"):
            if pattern.search(path.read_text(encoding="utf-8")):
                violations.append(str(path))
        self.assertEqual(violations, [], f"phantom/bridge file(s) reference phantom_pipeline: {violations}")


class TestGitDiffTouchesNoUnrelatedPackage(unittest.TestCase):
    def test_git_status_shows_only_expected_paths_changed(self):
        """Confirms this phase's own claim: nothing outside phantom/,
        mt5/, tests/phantom/, docs/research/, docs/adr/ (the
        charter-mandated per-stage ADR gate, CLAUDE.md §1.10 -- every
        later phase, e.g. ADR-024's Evidence Engine, legitimately adds
        one), and this repo's established root-level `PHANTOM_*.md`
        phase-deliverable report convention is touched. Skipped (not
        failed) outside a git checkout."""
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        if result.returncode != 0:
            self.skipTest("not a git checkout")
        allowed_prefixes = ("phantom/", "mt5/", "tests/phantom/", "docs/research/", "docs/adr/")

        def is_allowed(path: str) -> bool:
            if path.startswith(allowed_prefixes):
                return True
            return "/" not in path and path.startswith("PHANTOM_") and path.endswith(".md")

        unexpected = [line[3:] for line in result.stdout.splitlines() if not is_allowed(line[3:])]
        self.assertEqual(unexpected, [], f"unexpected changes outside this phase's scope: {unexpected}")


if __name__ == "__main__":
    unittest.main()
