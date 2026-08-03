"""Structural boundary tests (ADR-021 Hard Rules 1-4, 6, 7, 9) — verified
by source inspection and by scripts/check_architecture.py's own
behavior, never merely asserted in prose."""

from __future__ import annotations

import inspect
import re
import subprocess
import sys
import unittest
from pathlib import Path

from phantom_pipeline.research_desk.debate import BullBearDebateAgent
from phantom_pipeline.research_desk.explainable import ExplainableDecisionEngine
from phantom_pipeline.research_desk.institutional_review import WeeklyInstitutionalReviewGenerator
from phantom_pipeline.research_desk.market_research import MarketResearchAgent
from phantom_pipeline.research_desk.strategy_research import StrategyResearchAgent
from phantom_pipeline.research_desk.trade_journal import AITradeJournal
from phantom_pipeline.research_desk.trade_thesis import TradeThesisGenerator

REPO_ROOT = Path(__file__).resolve().parents[3]
PIPELINE_STAGE_DIRS = (
    "data_pipeline", "scanner", "strategy_engine", "scoring_engine", "risk_engine",
    "compliance_engine", "execution_validator", "mt5_bridge", "position_manager", "analytics",
)
FORBIDDEN_METHOD_NAME_FRAGMENTS = ("submit_", "decide_", "approve_", "reject_", "execute_", "set_risk", "size_")
AGENT_CLASSES = (
    BullBearDebateAgent, MarketResearchAgent, TradeThesisGenerator, AITradeJournal,
    StrategyResearchAgent, WeeklyInstitutionalReviewGenerator, ExplainableDecisionEngine,
)


class TestNoDecisionAuthorityMethodNames(unittest.TestCase):
    def test_no_public_method_on_any_agent_resembles_a_decision_verb(self):
        for cls in AGENT_CLASSES:
            for name, _member in inspect.getmembers(cls, predicate=inspect.isfunction):
                if name.startswith("_"):
                    continue
                lowered = name.lower()
                for forbidden in FORBIDDEN_METHOD_NAME_FRAGMENTS:
                    self.assertNotIn(forbidden, lowered, f"{cls.__name__}.{name} resembles a forbidden decision verb")


class TestNoUpdateMethodOnJournalEntry(unittest.TestCase):
    def test_ai_trade_journal_has_no_update_or_edit_method(self):
        update_like = [
            name for name, _m in inspect.getmembers(AITradeJournal, predicate=inspect.isfunction)
            if name.startswith(("set_", "update_", "edit_", "modify_"))
        ]
        self.assertEqual(update_like, [])


class TestNoPipelineStageImportsResearchDesk(unittest.TestCase):
    def test_source_scan_finds_no_pipeline_stage_importing_research_desk_or_knowledge(self):
        pattern = re.compile(r"^from \.\.(knowledge|research_desk)\b", re.MULTILINE)
        violations = []
        for stage_dir in PIPELINE_STAGE_DIRS:
            package_dir = REPO_ROOT / "phantom_pipeline" / stage_dir
            if not package_dir.is_dir():
                continue
            for path in package_dir.glob("*.py"):
                if pattern.search(path.read_text(encoding="utf-8")):
                    violations.append(str(path))
        self.assertEqual(violations, [])

    def test_check_architecture_script_passes(self):
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "check_architecture.py")],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("no pipeline-stage imports a cross-cutting observer package", result.stdout)


class TestKnowledgeAndDashboardUnmodified(unittest.TestCase):
    def test_knowledge_package_has_no_research_desk_import(self):
        knowledge_dir = REPO_ROOT / "phantom_pipeline" / "knowledge"
        pattern = re.compile(r"^from \.\.research_desk\b", re.MULTILINE)
        for path in knowledge_dir.glob("*.py"):
            self.assertIsNone(pattern.search(path.read_text(encoding="utf-8")), f"{path} imports research_desk")

    def test_dashboard_package_has_no_research_desk_import(self):
        dashboard_dir = REPO_ROOT / "phantom_pipeline" / "dashboard"
        pattern = re.compile(r"^from \.\.research_desk\b", re.MULTILINE)
        for path in dashboard_dir.glob("*.py"):
            self.assertIsNone(pattern.search(path.read_text(encoding="utf-8")), f"{path} imports research_desk")

    def test_view_name_enum_still_ten_values(self):
        from phantom_pipeline.dashboard.models import ViewName

        self.assertEqual(len(ViewName), 10)

    def test_knowledge_document_kind_unchanged_count(self):
        from phantom_pipeline.knowledge.models import DocumentKind

        # 17 members as of ADR-020 (confirms research_desk added no new
        # DocumentKind value, ADR-021 Hard Rule 3); 18 as of ADR-022
        # Amendment 1's STATISTICAL_RISK_ASSESSMENT addition -- this test's
        # own purpose (catch an unreviewed drift, not freeze the enum
        # forever) is satisfied by keeping this count in lockstep with
        # every intentional, ADR-documented addition.
        self.assertEqual(len(DocumentKind), 18)


if __name__ == "__main__":
    unittest.main()
