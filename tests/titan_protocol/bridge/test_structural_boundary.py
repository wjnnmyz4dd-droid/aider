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
        news wiring; ADR-034 Amendment 2 ("Produce a Clean Deployment
        Release") legitimately adds install_mt5_files.py, to personalize
        the new SocketHost/SocketPort .set-file fields -- no other
        deployment_windows/ file is expected to change for any of these
        phases), and this repo's established root-level `PHANTOM_*.md`
        phase-deliverable report convention (historical -- these files
        were never renamed; see the Titan Protocol rename's own report)
        is touched. A documentation-reconciliation phase (post-ADR-034
        Amendment 3) legitimately touches a wider, explicitly-enumerated
        set of docs -- marking obsolete pre-Titan-Protocol/pre-ADR-034
        guides as deprecated, rewriting COPY_TO_VPS.md/VERIFY_DEPLOYMENT.md
        for the current deployment_windows/ workflow, correcting stale
        HTTP-only-transport/pre-Amendment-1 claims in
        WINDOWS_OPERATOR_GUIDE.md/KNOWN_GAPS.md, and removing the
        DEPLOYMENT_PACKAGE/ directory once every one of its live
        references was gone -- no runtime/trading logic is touched by any
        of it. Skipped (not failed) outside a git checkout."""
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
            "deployment_windows/install_mt5_files.py",
            "deployment_windows/KNOWN_GAPS.md",
            "deployment_windows/config/titan_protocol_config.example.json",
            # Documentation-reconciliation phase (post-ADR-034 Amendment 3):
            # deprecation banners on obsolete pre-Titan-Protocol guides, full
            # rewrites of the two VPS docs, staleness fixes in the current
            # operator guide, and the DEPLOYMENT_PACKAGE/ removal it depends on.
            "deployment_windows/WINDOWS_OPERATOR_GUIDE.md",
            "docs/mt5_validation/",
            "DEPLOYMENT_PACKAGE/",
            "COPY_TO_VPS.md", "VERIFY_DEPLOYMENT.md",
            "DEPLOYMENT_AUDIT.md", "DEPLOYMENT_MANIFEST.md",
            "FINAL_DEPLOYMENT_READINESS_REPORT.md",
            "DISASTER_RECOVERY.md", "KNOWLEDGE_DEPLOYMENT_GUIDE.md",
            "LIVE_DEPLOYMENT_GUIDE.md", "OPERATOR_CHECKLIST.md",
            "RESEARCH_DESK_GUIDE.md", "START_PHANTOM.md", "VPS_SETUP_GUIDE.md",
            # Deployment-bug fix (GetLastError=4014 persisting despite the
            # allow-list having been edited): mt5_terminal.py (new --
            # origin.txt-based running-instance/data-folder detection),
            # verify_mt5_instance.py (new -- the 6-point validation
            # script), and their test coverage. install.py/
            # install_mt5_files.py's own changes for this phase are
            # already covered by the broader prefixes above.
            "deployment_windows/mt5_terminal.py",
            "deployment_windows/verify_mt5_instance.py",
            "tests/deployment_windows/test_mt5_terminal.py",
            # Runtime Audit Phase 3 (deterministic communication-state
            # classifier): describe_rejection()/rejection-reason logging
            # was already in place (Phase 2); this phase adds the
            # EA-side TITAN_DIAG attempt/blocked/no-response markers
            # (mt5/TitanProtocolEA.mq5, already covered by "mt5/" above),
            # a Bridge-side console-log persistence fix and a socket-side
            # accepted-request log line (titan_protocol/bridge/, already
            # covered by "titan_protocol/" above), and the new
            # diagnose_communication.py classifier + its test coverage.
            "deployment_windows/diagnose_communication.py",
            "tests/deployment_windows/test_diagnose_communication.py",
            # Portfolio-state adapter fix: PortfolioState() was always
            # empty in the live-cycle loop, so check_position_limits()
            # could never see an already-open position -- fixed by mapping
            # BridgeEngine.latest_positions into it (deployment_windows/
            # start.py, already covered by the broader prefix above; this
            # adds only the new test file).
            "tests/deployment_windows/test_start_portfolio_state.py",
            # max_positions_per_pair=1 production-invariant fix: made the
            # compliance position-limit configurable from the JSON config
            # (deployment_windows/config_loader.py, already covered by the
            # broader prefix above) plus its own test file and a small,
            # additive extension to the shared config-loader test fixture
            # (a new compliance_overrides parameter, not a behavior change
            # for any existing caller).
            "tests/deployment_windows/test_config_loader.py",
            "tests/deployment_windows/_fixtures.py",
            "deployment_windows/REAL_MT5_VALIDATION_CHECKLIST.md",
        )

        def is_allowed(path: str) -> bool:
            if path.startswith(allowed_prefixes):
                return True
            return "/" not in path and path.startswith("PHANTOM_") and path.endswith(".md")

        unexpected = [line[3:] for line in result.stdout.splitlines() if not is_allowed(line[3:])]
        self.assertEqual(unexpected, [], f"unexpected changes outside this phase's scope: {unexpected}")


if __name__ == "__main__":
    unittest.main()
