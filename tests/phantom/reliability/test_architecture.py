"""Architecture tests (ADR-032 SS6): no decision-shaped vocabulary
anywhere in `phantom/reliability/`, no import of `phantom_pipeline` or
any Runtime *engine* module (only `phantom.runtime.models` and
`phantom.runtime.watchdog_integration` are permitted per ADR-032 Hard
Rule 2), Compliance Engine and Bridge never in the restart allow list."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from phantom.runtime.watchdog_integration import APPROVED_RESTART_COMPONENTS

PACKAGE_ROOT = Path(__file__).resolve().parents[3] / "phantom" / "reliability"

FORBIDDEN_IDENTIFIERS = {
    "select_strategy", "choose_strategy", "select_direction", "choose_direction",
    "calculate_evidence", "calculate_risk", "make_compliance_decision", "override_engine",
    "generate_signal", "submit_trade", "place_order",
}

FORBIDDEN_IMPORT_PREFIXES = ("phantom_pipeline", "phantom.validation_engine")
ALLOWED_RUNTIME_MODULES = ("phantom.runtime.models", "phantom.runtime.watchdog_integration")


def _source_files():
    return sorted(PACKAGE_ROOT.rglob("*.py"))


def _bound_identifiers(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            yield node.id
        elif isinstance(node, ast.Attribute):
            yield node.attr
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield node.name
        elif isinstance(node, ast.arg):
            yield node.arg


def _imported_names(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


class TestNoDecisionVocabulary(unittest.TestCase):
    def test_no_forbidden_identifier_anywhere_in_package_source(self):
        offenders = []
        for path in _source_files():
            tree = ast.parse(path.read_text(), filename=str(path))
            found = FORBIDDEN_IDENTIFIERS & set(_bound_identifiers(tree))
            if found:
                offenders.append((str(path.relative_to(PACKAGE_ROOT)), sorted(found)))
        self.assertEqual(offenders, [], f"forbidden decision vocabulary found in: {offenders}")

    def test_no_public_method_resembles_a_decision_api(self):
        from phantom.reliability.engine import ReliabilityEngine

        forbidden_method_names = {"select", "score", "decide", "approve", "reject", "override", "submit"}
        public_methods = {name for name in dir(ReliabilityEngine) if not name.startswith("_")}
        self.assertEqual(public_methods & forbidden_method_names, set())


class TestNoForbiddenImports(unittest.TestCase):
    def test_no_import_of_phantom_pipeline_or_validation_engine(self):
        offenders = []
        for path in _source_files():
            tree = ast.parse(path.read_text(), filename=str(path))
            for name in _imported_names(tree):
                if any(name == p or name.startswith(p + ".") for p in FORBIDDEN_IMPORT_PREFIXES):
                    offenders.append((str(path.relative_to(PACKAGE_ROOT)), name))
        self.assertEqual(offenders, [], f"forbidden imports found: {offenders}")

    def test_only_permitted_runtime_modules_are_imported(self):
        offenders = []
        for path in _source_files():
            tree = ast.parse(path.read_text(), filename=str(path))
            for name in _imported_names(tree):
                if name.startswith("phantom.runtime"):
                    if not any(name == m or name.startswith(m + ".") for m in ALLOWED_RUNTIME_MODULES):
                        offenders.append((str(path.relative_to(PACKAGE_ROOT)), name))
        self.assertEqual(offenders, [], f"unexpected Runtime import (only models/watchdog_integration permitted): {offenders}")

    def test_no_import_of_any_upstream_trading_engine(self):
        forbidden_engine_prefixes = (
            "phantom.evidence_engine", "phantom.market_intelligence",
            "phantom.risk_engine", "phantom.compliance_engine", "phantom.bridge",
        )
        offenders = []
        for path in _source_files():
            tree = ast.parse(path.read_text(), filename=str(path))
            for name in _imported_names(tree):
                if any(name == p or name.startswith(p + ".") for p in forbidden_engine_prefixes):
                    offenders.append((str(path.relative_to(PACKAGE_ROOT)), name))
        self.assertEqual(offenders, [], f"reliability engine must never call into a trading engine: {offenders}")


class TestWatchdogRestartBoundary(unittest.TestCase):
    def test_compliance_engine_never_in_restart_allow_list(self):
        self.assertNotIn("compliance_engine", APPROVED_RESTART_COMPONENTS)

    def test_bridge_never_in_restart_allow_list(self):
        self.assertNotIn("bridge", APPROVED_RESTART_COMPONENTS)

    def test_runtime_itself_never_in_restart_allow_list(self):
        self.assertNotIn("runtime", APPROVED_RESTART_COMPONENTS)


if __name__ == "__main__":
    unittest.main()
