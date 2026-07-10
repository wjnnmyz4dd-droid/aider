"""Architecture tests (ADR-025 Hard Rules 1 and 6): no trade-decision
vocabulary, no import from `phantom_pipeline/` or `phantom/bridge/`
(the one permitted upstream import is `phantom.evidence_engine`), no
randomness, in any `phantom/market_intelligence/` source file."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[3] / "phantom" / "market_intelligence"

FORBIDDEN_IDENTIFIERS = {
    "BUY", "SELL", "position_size", "stop_loss", "take_profit",
    "order_type", "place_order", "submit_order", "select_strategy",
}

FORBIDDEN_IMPORT_PREFIXES = ("phantom_pipeline", "phantom.bridge")


def _source_files():
    return sorted(PACKAGE_ROOT.glob("*.py"))


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


class TestNoTradeDecisionVocabulary(unittest.TestCase):
    def test_no_forbidden_identifier_anywhere_in_package_source(self):
        offenders = []
        for path in _source_files():
            tree = ast.parse(path.read_text(), filename=str(path))
            found = FORBIDDEN_IDENTIFIERS & set(_bound_identifiers(tree))
            if found:
                offenders.append((path.name, sorted(found)))
        self.assertEqual(offenders, [], f"forbidden trade-decision vocabulary found in: {offenders}")


class TestNoForbiddenImports(unittest.TestCase):
    def test_no_import_of_phantom_pipeline_or_bridge(self):
        offenders = []
        for path in _source_files():
            tree = ast.parse(path.read_text(), filename=str(path))
            for name in _imported_names(tree):
                if any(name == p or name.startswith(p + ".") for p in FORBIDDEN_IMPORT_PREFIXES):
                    offenders.append((path.name, name))
        self.assertEqual(offenders, [], f"forbidden imports found: {offenders}")

    def test_only_permitted_import_from_evidence_engine_is_session_and_models(self):
        allowed_evidence_engine_modules = {
            "phantom.evidence_engine.session",
            "phantom.evidence_engine.models",
            "phantom.evidence_engine.config",
        }
        offenders = []
        for path in _source_files():
            tree = ast.parse(path.read_text(), filename=str(path))
            for name in _imported_names(tree):
                if name.startswith("phantom.evidence_engine") and name not in allowed_evidence_engine_modules:
                    offenders.append((path.name, name))
        self.assertEqual(offenders, [], f"unexpected evidence_engine submodule import: {offenders}")


class TestNoRandomnessOrMachineLearning(unittest.TestCase):
    def test_no_random_or_ml_imports(self):
        forbidden_modules = {"random", "numpy.random", "sklearn", "torch", "tensorflow"}
        offenders = []
        for path in _source_files():
            tree = ast.parse(path.read_text(), filename=str(path))
            for name in _imported_names(tree):
                if name in forbidden_modules:
                    offenders.append((path.name, name))
        self.assertEqual(offenders, [], f"forbidden random/ML imports found: {offenders}")


class TestSingleResponsibility(unittest.TestCase):
    def test_no_network_or_file_io_modules_imported(self):
        forbidden_modules = {"socket", "http.client", "urllib.request", "requests"}
        offenders = []
        for path in _source_files():
            tree = ast.parse(path.read_text(), filename=str(path))
            for name in _imported_names(tree):
                if name in forbidden_modules:
                    offenders.append((path.name, name))
        self.assertEqual(offenders, [], f"forbidden I/O imports found: {offenders}")

    def test_public_surface_has_no_trade_execution_method(self):
        from phantom.market_intelligence.engine import MarketIntelligenceEngine

        forbidden_method_names = {"submit_order", "place_trade", "execute", "close_position", "open_position", "select_strategy"}
        public_methods = {name for name in dir(MarketIntelligenceEngine) if not name.startswith("_")}
        self.assertEqual(public_methods & forbidden_method_names, set())


if __name__ == "__main__":
    unittest.main()
