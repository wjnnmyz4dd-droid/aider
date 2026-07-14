"""Structural boundary tests (Phase 1 + Amendment 1) -- verified by
source inspection, never merely asserted in prose. Phase 1 had exactly
one component; Amendment 1 (ADR-023) explicitly and narrowly authorizes
exactly one more: `titan_protocol.market_data_ingestion`, called only to
delegate (never to duplicate its validation/normalization logic). This
guards against any *other* package being wired in before its own
approval, and against `titan_protocol.bridge` ever gaining trading-
decision logic of its own."""

from __future__ import annotations

import inspect
import re
import subprocess
import sys
import unittest
from pathlib import Path

from titan_protocol.bridge.engine import BridgeEngine

REPO_ROOT = Path(__file__).resolve().parents[3]
BRIDGE_DIR = REPO_ROOT / "titan_protocol" / "bridge"

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
    """Phase 1 had no scanner/strategy/risk/intelligence/watchdog/config
    package to import from yet; Amendment 1 (ADR-023) explicitly
    authorizes exactly one addition -- `market_data_ingestion`, called
    only to delegate. This test still fails loudly the moment anyone
    adds any *other* sibling package before it's approved."""

    _ALLOWED_SIBLING_PACKAGES = ("bridge", "market_data_ingestion")

    def test_no_file_imports_an_unauthorized_sibling_titan_protocol_package(self):
        allowed_alternation = "|".join(self._ALLOWED_SIBLING_PACKAGES)
        pattern = re.compile(
            rf"^from \.\.(?!(?:{allowed_alternation})\b)[a-z0-9_]+"
            rf"|^from titan_protocol\.(?!(?:{allowed_alternation})\b)[a-z0-9_]+",
            re.MULTILINE,
        )
        violations = []
        for path in BRIDGE_DIR.glob("*.py"):
            if pattern.search(path.read_text(encoding="utf-8")):
                violations.append(str(path))
        self.assertEqual(violations, [], f"titan_protocol/bridge file(s) import an unauthorized sibling titan_protocol package: {violations}")

    def test_market_data_ingestion_is_only_ever_delegated_to_not_reimplemented(self):
        """Hard Rule 9 (Amendment 1): no validation/normalization/
        ordering/warmup/gap-detection logic may be duplicated in
        titan_protocol/bridge/ -- every reference to market_data_ingestion
        must be an import or a call into its existing public engine
        methods, never a reimplementation of its internals."""
        forbidden_reimplementation_names = (
            "def validate_bar", "def check_ordering", "def is_stale", "class WarmupTracker", "def normalize(",
        )
        violations = []
        for path in BRIDGE_DIR.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            for forbidden in forbidden_reimplementation_names:
                if forbidden in text:
                    violations.append((str(path), forbidden))
        self.assertEqual(violations, [], f"titan_protocol/bridge file(s) appear to reimplement market_data_ingestion internals: {violations}")

    def test_no_file_imports_phantom_pipeline(self):
        pattern = re.compile(r"phantom_pipeline", re.MULTILINE)
        violations = []
        for path in BRIDGE_DIR.glob("*.py"):
            if pattern.search(path.read_text(encoding="utf-8")):
                violations.append(str(path))
        self.assertEqual(violations, [], f"titan_protocol/bridge file(s) reference phantom_pipeline: {violations}")


class TestGitDiffTouchesNoUnrelatedPackage(unittest.TestCase):
    def test_git_status_shows_only_expected_paths_changed(self):
        """Confirms this phase's own claim: nothing outside titan_protocol/,
        mt5/, tests/titan_protocol/, docs/research/, docs/adr/ (the
        charter-mandated per-stage ADR gate, CLAUDE.md §1.10 -- every
        later phase, e.g. ADR-024's Evidence Engine, legitimately adds
        one), deployment_windows/ (Amendment 1, ADR-023, scoped to
        start.py/health_check.py; Phase 3E, ADR-033 Part 2, legitimately
        adds config_loader.py/install.py/KNOWN_GAPS.md/config/
        titan_protocol_config.example.json for the new dual-provider
        news wiring -- no other deployment_windows/ file is expected to
        change for either phase), and this repo's established
        root-level `PHANTOM_*.md` phase-deliverable report convention
        (historical -- these files were never renamed; see the Titan
        Protocol rename's own report) is touched. Skipped (not failed)
        outside a git checkout."""
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        if result.returncode != 0:
            self.skipTest("not a git checkout")
        allowed_prefixes = (
            "titan_protocol/", "mt5/", "tests/titan_protocol/", "docs/research/", "docs/adr/",
            "deployment_windows/start.py", "deployment_windows/health_check.py",
            "deployment_windows/config_loader.py", "deployment_windows/install.py",
            "deployment_windows/KNOWN_GAPS.md",
            "deployment_windows/config/titan_protocol_config.example.json",
        )

        def is_allowed(path: str) -> bool:
            if path.startswith(allowed_prefixes):
                return True
            return "/" not in path and path.startswith("PHANTOM_") and path.endswith(".md")

        unexpected = [line[3:] for line in result.stdout.splitlines() if not is_allowed(line[3:])]
        self.assertEqual(unexpected, [], f"unexpected changes outside this phase's scope: {unexpected}")


if __name__ == "__main__":
    unittest.main()
