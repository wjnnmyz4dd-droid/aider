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
            # Run Status diagnostics (item 10): a single, health.json-backed
            # view (start.py's _LiveCycleStatus + _write_health_snapshot's
            # new run_status block, health_check.py's RUN STATUS panel) so
            # an operator can determine why Titan is or is not trading from
            # one place. Additive only -- new optional parameters/fields,
            # no existing signature or behavior changed.
            "tests/deployment_windows/test_run_status.py",
            "tests/deployment_windows/test_health_check_run_status.py",
            # ADR-034 Amendment 4: transport-default flip (socket -> http)
            # and the EA's HTTP-status classification boundary fix. Files
            # already covered above: titan_protocol/ (bridge/config.py),
            # mt5/ (TitanProtocolEA.mq5/.set), docs/adr/, deployment_windows/
            # start.py, config_loader.py, install_mt5_files.py,
            # WINDOWS_OPERATOR_GUIDE.md, config/titan_protocol_config.
            # example.json, diagnose_communication.py,
            # tests/deployment_windows/test_diagnose_communication.py.
            # New test files added by this phase only:
            "tests/deployment_windows/test_transport_defaults.py",
            "tests/mt5/test_titan_protocol_ea_transport_classification.py",
            # ACCOUNT_STATE_STALE fail-closed freshness gate (fix option (b)):
            # ComplianceEngine gains one new early-reject rule
            # (ACCOUNT_STATE_STALE), configurable via
            # compliance.max_account_state_age_seconds (config_loader.py,
            # already covered above), surfaced in run_status/health_check.py
            # (already covered above). _build_compliance_account_state()
            # (start.py, already covered) now threads account_report_age_seconds
            # through -- the only pre-existing test file this touches is
            # test_compliance_state_persistence.py (its _FakeBridgeEngine stub
            # needed a received_at field); the rest are new test files.
            "tests/deployment_windows/test_compliance_state_persistence.py",
            "tests/titan_protocol/runtime/test_account_state_staleness_integration.py",
            # ADR-034 Amendment 5 (HTTP poll-level exponential backoff) +
            # the undelivered-command-abandonment runtime-state-machine
            # fix: mt5/TitanProtocolEA.mq5 (already covered by "mt5/"),
            # titan_protocol/runtime/in_flight_commands.py and
            # titan_protocol/bridge/engine.py (already covered by
            # "titan_protocol/"), deployment_windows/start.py (already
            # covered above), docs/adr/ (already covered above). New test
            # files this phase adds: the one under tests/mt5/ (not
            # covered by any broader prefix -- individual EA test files
            # are enumerated here, same as the transport-classification
            # one above); the runtime integration test is already covered
            # by the broad "tests/titan_protocol/" prefix.
            "tests/mt5/test_titan_protocol_ea_poll_backoff.py",
            # Part 2 of the same corrective patch: a new, additive
            # transport-configuration verification script (reuses
            # diagnose_communication.py's own log-location/parsing
            # helpers rather than duplicating them) plus its test file.
            "deployment_windows/verify_transport_configuration.py",
            "tests/deployment_windows/test_verify_transport_configuration.py",
            # WinINet proxy/WPAD diagnostic for the still-open
            # `pseudoStatus=1001`/`5203` WebRequest() failure signature
            # (KNOWN_GAPS.md section 12): a new, additive diagnostic script
            # plus its test file. WINDOWS_OPERATOR_GUIDE.md/KNOWN_GAPS.md/
            # CHANGELOG.md are already covered above.
            "deployment_windows/diagnose_wininet.py",
            "tests/deployment_windows/test_diagnose_wininet.py",
            # Positions-staleness observability signal (Titan Protocol
            # Independent Verification, Partially Verified finding):
            # a new, pure, directly-testable logging-only function in
            # start.py (_log_positions_staleness_if_stale()) plus its
            # test file -- no trade acceptance/rejection behavior
            # changed, reuses BridgeConfig's existing
            # heartbeat_timeout_seconds as the log threshold.
            "tests/deployment_windows/test_positions_staleness_observability.py",
            # ADR-037 post-implementation conformance correction: closes
            # two findings from an independent post-implementation review
            # (b526ae1) -- a distinct runtime observability signal plus
            # fail-closed suppression for ADR-037 SS11 item 2/SS12's
            # defense-in-depth backstop (titan_protocol/runtime/engine.py,
            # already covered by "titan_protocol/" above, plus its test
            # file, already covered by "tests/titan_protocol/" above), and
            # an administrative-only update to this Plan document's own
            # status/history recording the authorization-through-review
            # chain -- no architecture or implementation design altered.
            "docs/plans/adr-037-implementation-plan.md",
            # ADR-037 production-activation governance: two new,
            # documentation-only artifacts recording the Research pass
            # (ea53932) and this Policy Decision pass -- no code, ADR, or
            # production configuration changed by either; both explicitly
            # authorize no Gate A/B activation, no cross_pair_selection_
            # enabled flip, no legacy-strategy retirement.
            "docs/plans/adr-037-production-activation-research.md",
            "docs/plans/adr-037-production-activation-policy-decision.md",
        )

        def is_allowed(path: str) -> bool:
            if path.startswith(allowed_prefixes):
                return True
            if path == "CHANGELOG.md":
                # ADR-034 Amendments 8/9 (position-confirmation timeout +
                # restart-safe in-flight persistence): a dated changelog
                # entry alongside the already-allowed docs/adr/ and
                # titan_protocol/ changes -- no unrelated content.
                return True
            return "/" not in path and path.startswith("PHANTOM_") and path.endswith(".md")

        unexpected = [line[3:] for line in result.stdout.splitlines() if not is_allowed(line[3:])]
        self.assertEqual(unexpected, [], f"unexpected changes outside this phase's scope: {unexpected}")


if __name__ == "__main__":
    unittest.main()
