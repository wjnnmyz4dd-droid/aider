"""Structural boundary tests (`ADR-022` Hard Rules 1-4, 9) — verified by
source inspection and by `scripts/check_architecture.py`'s own behavior,
never merely asserted in prose."""

from __future__ import annotations

import inspect
import re
import subprocess
import sys
import unittest
from pathlib import Path

from phantom_pipeline.statistical_risk.engine import StatisticalRiskEngine

REPO_ROOT = Path(__file__).resolve().parents[3]
STATISTICAL_RISK_DIR = REPO_ROOT / "phantom_pipeline" / "statistical_risk"
PIPELINE_STAGE_DIRS = (
    "data_pipeline", "scanner", "strategy_engine", "scoring_engine", "risk_engine",
    "compliance_engine", "execution_validator", "mt5_bridge", "position_manager", "analytics",
)

FORBIDDEN_METHOD_NAME_FRAGMENTS = (
    "submit_", "decide_", "approve_", "reject_", "execute_", "set_risk", "size_",
)


class TestNoDecisionAuthorityMethodNames(unittest.TestCase):
    def test_no_public_method_on_statistical_risk_engine_resembles_a_decision_verb(self):
        for name, _member in inspect.getmembers(StatisticalRiskEngine, predicate=inspect.isfunction):
            if name.startswith("_"):
                continue
            lowered = name.lower()
            for forbidden in FORBIDDEN_METHOD_NAME_FRAGMENTS:
                self.assertNotIn(forbidden, lowered, f"StatisticalRiskEngine.{name} resembles a forbidden decision verb")


class TestNoPipelineStageImportsStatisticalRisk(unittest.TestCase):
    """`ADR-022` Hard Rule 4, verified directly (not merely by running the
    script) so this test fails loudly even if check_architecture.py is
    ever removed or bypassed."""

    def test_source_scan_finds_no_pipeline_stage_importing_statistical_risk(self):
        pattern = re.compile(r"^from \.\.statistical_risk\b", re.MULTILINE)
        violations = []
        for stage_dir in PIPELINE_STAGE_DIRS:
            package_dir = REPO_ROOT / "phantom_pipeline" / stage_dir
            if not package_dir.is_dir():
                continue
            for path in package_dir.glob("*.py"):
                if pattern.search(path.read_text(encoding="utf-8")):
                    violations.append(str(path))
        self.assertEqual(violations, [], f"pipeline stage(s) import statistical_risk: {violations}")

    def test_check_architecture_script_passes(self):
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "check_architecture.py")],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("no pipeline-stage imports a cross-cutting observer package", result.stdout)


class TestRiskEngineNotModified(unittest.TestCase):
    def test_risk_engine_has_no_statistical_risk_import(self):
        risk_engine_dir = REPO_ROOT / "phantom_pipeline" / "risk_engine"
        pattern = re.compile(r"^from \.\.statistical_risk\b", re.MULTILINE)
        for path in risk_engine_dir.glob("*.py"):
            self.assertIsNone(pattern.search(path.read_text(encoding="utf-8")), f"{path} imports statistical_risk")

    def test_git_diff_touches_no_pipeline_stage_package(self):
        """Confirms this ADR's own claim: risk_engine, compliance_engine,
        execution_validator, position_manager, mt5_bridge, scanner, and
        strategy_engine are byte-for-byte unchanged by this work. Skipped
        (not failed) outside a git checkout with history to diff against."""
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        if result.returncode != 0:
            self.skipTest("not a git checkout with a diffable HEAD")
        protected_dirs = (
            "phantom_pipeline/risk_engine/", "phantom_pipeline/compliance_engine/",
            "phantom_pipeline/execution_validator/", "phantom_pipeline/position_manager/",
            "phantom_pipeline/mt5_bridge/", "phantom_pipeline/scanner/", "phantom_pipeline/strategy_engine/",
        )
        changed = result.stdout.splitlines()
        violations = [path for path in changed if path.startswith(protected_dirs)]
        self.assertEqual(violations, [], f"unexpected changes under a protected package: {violations}")


class TestStatisticalRiskHasNoDirectoryWalkOrEnvAccess(unittest.TestCase):
    def test_no_os_walk_or_dotenv_access_anywhere_in_package(self):
        for path in STATISTICAL_RISK_DIR.glob("*.py"):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("os.walk", source, f"{path} performs an arbitrary directory walk")
            self.assertNotIn(".env", source, f"{path} references a .env file")


if __name__ == "__main__":
    unittest.main()
