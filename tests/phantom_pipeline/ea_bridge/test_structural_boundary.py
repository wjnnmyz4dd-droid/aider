"""Structural boundary tests (`ADR-023` Hard Rules 1-4) — verified by
source inspection and by `scripts/check_architecture.py`'s own behavior,
never merely asserted in prose."""

from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

from phantom_pipeline.ea_bridge.broker_adapter import EABrokerAdapter
from phantom_pipeline.mt5_bridge import BrokerAdapter, FakeBrokerAdapter
from phantom_pipeline.mt5_bridge.mt5_adapter import MT5Adapter  # noqa: F401 -- import registers the subclass

REPO_ROOT = Path(__file__).resolve().parents[3]
EA_BRIDGE_DIR = REPO_ROOT / "phantom_pipeline" / "ea_bridge"
PROTECTED_PACKAGE_DIRS = (
    "phantom_pipeline/risk_engine/", "phantom_pipeline/compliance_engine/",
    "phantom_pipeline/execution_validator/", "phantom_pipeline/position_manager/",
    "phantom_pipeline/mt5_bridge/", "phantom_pipeline/scanner/", "phantom_pipeline/strategy_engine/",
    "phantom_pipeline/scoring_engine/", "phantom_pipeline/data_pipeline/", "phantom_pipeline/analytics/",
)


class TestEABrokerAdapterIsTheOnlyNewBrokerAdapterSubclass(unittest.TestCase):
    """`MT5Bridge` needs zero code change (`ADR-023` Hard Rule 2) — this
    only holds if `EABrokerAdapter` implements the ABC exactly, alongside
    the two subclasses that already existed before this ADR."""

    def test_broker_adapter_subclasses_are_exactly_the_expected_three(self):
        subclass_names = {cls.__name__ for cls in BrokerAdapter.__subclasses__()}
        self.assertEqual(subclass_names, {"MT5Adapter", "FakeBrokerAdapter", "EABrokerAdapter"})

    def test_ea_broker_adapter_implements_every_abstract_method(self):
        for method_name in BrokerAdapter.__abstractmethods__:
            self.assertTrue(
                callable(getattr(EABrokerAdapter, method_name, None)),
                f"EABrokerAdapter is missing {method_name}",
            )


class TestNoPipelineStagePackageImportsEaBridge(unittest.TestCase):
    """`ea_bridge` is consumed only via `mt5_bridge`'s existing constructor-
    injection point (the same relationship `MT5Adapter` already has) —
    never imported directly by any pipeline stage."""

    def test_source_scan_finds_no_pipeline_stage_importing_ea_bridge(self):
        pattern = re.compile(r"^from \.\.ea_bridge\b", re.MULTILINE)
        violations = []
        for stage_dir in (
            "data_pipeline", "scanner", "strategy_engine", "scoring_engine", "risk_engine",
            "compliance_engine", "execution_validator", "mt5_bridge", "position_manager", "analytics",
        ):
            package_dir = REPO_ROOT / "phantom_pipeline" / stage_dir
            if not package_dir.is_dir():
                continue
            for path in package_dir.glob("*.py"):
                if pattern.search(path.read_text(encoding="utf-8")):
                    violations.append(str(path))
        self.assertEqual(violations, [], f"pipeline stage(s) import ea_bridge: {violations}")

    def test_check_architecture_script_passes(self):
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "check_architecture.py")],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class TestEaBridgeNeverConstructsCommandsOutsideBrokerAdapter(unittest.TestCase):
    """`ExecutionCommand` may only be built from an already-produced
    `BrokerRequest` (`ADR-023` Hard Rule 4) — the constructor call must
    appear nowhere in this package except `broker_adapter.py`."""

    def test_execution_command_constructed_only_in_broker_adapter(self):
        pattern = re.compile(r"\bExecutionCommand\(")
        offending_files = []
        for path in EA_BRIDGE_DIR.glob("*.py"):
            if path.name in ("models.py", "broker_adapter.py"):
                continue
            if pattern.search(path.read_text(encoding="utf-8")):
                offending_files.append(str(path))
        self.assertEqual(offending_files, [])


class TestGitDiffTouchesNoProtectedPipelineStage(unittest.TestCase):
    def test_git_diff_touches_no_pipeline_stage_package(self):
        """Confirms ADR-023's own claim: every existing pipeline-stage
        package is byte-for-byte unchanged by this work. Skipped (not
        failed) outside a git checkout with history to diff against."""
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        untracked = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        if result.returncode != 0:
            self.skipTest("not a git checkout with a diffable HEAD")
        changed = result.stdout.splitlines() + [
            line[3:] for line in untracked.stdout.splitlines() if line.startswith("??")
        ]
        violations = [path for path in changed if path.startswith(PROTECTED_PACKAGE_DIRS)]
        self.assertEqual(violations, [], f"unexpected changes under a protected package: {violations}")


if __name__ == "__main__":
    unittest.main()
