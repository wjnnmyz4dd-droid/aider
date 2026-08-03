"""Structural boundary tests (ADR-020 Hard Rules 1-4, 9) — verified by
source inspection and by `scripts/check_architecture.py`'s own behavior,
never merely asserted in prose."""

from __future__ import annotations

import inspect
import re
import subprocess
import sys
import unittest
from pathlib import Path

import phantom_pipeline.knowledge as knowledge_pkg
from phantom_pipeline.knowledge.engine import ExplanationEngine, KnowledgeEngine

REPO_ROOT = Path(__file__).resolve().parents[3]
KNOWLEDGE_DIR = REPO_ROOT / "phantom_pipeline" / "knowledge"
PIPELINE_STAGE_DIRS = (
    "data_pipeline", "scanner", "strategy_engine", "scoring_engine", "risk_engine",
    "compliance_engine", "execution_validator", "mt5_bridge", "position_manager", "analytics",
)

FORBIDDEN_METHOD_NAME_FRAGMENTS = ("submit_", "decide_", "approve_", "reject_", "execute_", "set_risk", "size_")


class TestNoDecisionAuthorityMethodNames(unittest.TestCase):
    def test_no_public_method_on_knowledge_engine_resembles_a_decision_verb(self):
        for name, _member in inspect.getmembers(KnowledgeEngine, predicate=inspect.isfunction):
            if name.startswith("_"):
                continue
            lowered = name.lower()
            for forbidden in FORBIDDEN_METHOD_NAME_FRAGMENTS:
                self.assertNotIn(forbidden, lowered, f"KnowledgeEngine.{name} resembles a forbidden decision verb")

    def test_no_public_method_on_explanation_engine_resembles_a_decision_verb(self):
        for name, _member in inspect.getmembers(ExplanationEngine, predicate=inspect.isfunction):
            if name.startswith("_"):
                continue
            lowered = name.lower()
            for forbidden in FORBIDDEN_METHOD_NAME_FRAGMENTS:
                self.assertNotIn(forbidden, lowered, f"ExplanationEngine.{name} resembles a forbidden decision verb")


class TestNoPipelineStageImportsKnowledge(unittest.TestCase):
    """ADR-020 Hard Rule 9, verified directly (not merely by running the
    script) so this test fails loudly even if check_architecture.py is
    ever removed or bypassed."""

    def test_source_scan_finds_no_pipeline_stage_importing_knowledge(self):
        pattern = re.compile(r"^from \.\.knowledge\b", re.MULTILINE)
        violations = []
        for stage_dir in PIPELINE_STAGE_DIRS:
            package_dir = REPO_ROOT / "phantom_pipeline" / stage_dir
            if not package_dir.is_dir():
                continue
            for path in package_dir.glob("*.py"):
                if pattern.search(path.read_text(encoding="utf-8")):
                    violations.append(str(path))
        self.assertEqual(violations, [], f"pipeline stage(s) import knowledge: {violations}")

    def test_check_architecture_script_passes(self):
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "check_architecture.py")],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("no pipeline-stage imports a cross-cutting observer package", result.stdout)


class TestDashboardNotModified(unittest.TestCase):
    def test_dashboard_package_has_no_knowledge_import(self):
        dashboard_dir = REPO_ROOT / "phantom_pipeline" / "dashboard"
        pattern = re.compile(r"^from \.\.knowledge\b", re.MULTILINE)
        for path in dashboard_dir.glob("*.py"):
            self.assertIsNone(pattern.search(path.read_text(encoding="utf-8")), f"{path} imports knowledge")

    def test_view_name_enum_unchanged_ten_values(self):
        from phantom_pipeline.dashboard.models import ViewName

        self.assertEqual(len(ViewName), 10)
        self.assertNotIn("KNOWLEDGE", ViewName.__members__)


class TestKnowledgeDocumentStoreNeverExposesEnvOrCredentialReaders(unittest.TestCase):
    def test_ingestion_module_has_no_arbitrary_directory_walk_function(self):
        """ADR-020 SS2's explicit exclusion: never a walk over an
        arbitrary/unrestricted directory (e.g. the repo root or a config
        directory) -- only the named KNOWN_ROOT_DOCUMENTS set and the
        two explicitly-scoped docs/adr, docs/plans directories."""
        from phantom_pipeline.knowledge import ingestion

        source = inspect.getsource(ingestion)
        self.assertNotIn("os.walk", source)

    def test_ingestion_module_never_opens_a_dotenv_file(self):
        from phantom_pipeline.knowledge import ingestion

        source = inspect.getsource(ingestion)
        self.assertNotIn('open(".env")', source)
        self.assertNotIn("open('.env')", source)


if __name__ == "__main__":
    unittest.main()
