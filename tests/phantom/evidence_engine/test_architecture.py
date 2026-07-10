"""Architecture tests (ADR-024 Hard Rules 1 and 5): no trade-decision
vocabulary, no import from `phantom_pipeline/` or `phantom/bridge/`, no
randomness, in any `phantom/evidence_engine/` source file."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[3] / "phantom" / "evidence_engine"

#: Vocabulary that would signal a trade decision leaking into this
#: package -- checked against actual bound identifiers (variable names,
#: function/class names, attribute names) via the AST, never against
#: raw source text, so a docstring that *mentions* "BUY" to document
#: its absence (as this package's own module docstrings do) never
#: false-positives.
FORBIDDEN_IDENTIFIERS = {
    "BUY", "SELL", "position_size", "stop_loss", "take_profit",
    "order_type", "place_order", "submit_order",
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
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    if any(name == p or name.startswith(p + ".") for p in FORBIDDEN_IMPORT_PREFIXES):
                        offenders.append((path.name, name))
        self.assertEqual(offenders, [], f"forbidden imports found: {offenders}")


class TestNoRandomnessOrMachineLearning(unittest.TestCase):
    def test_no_random_or_ml_imports(self):
        forbidden_modules = {"random", "numpy.random", "sklearn", "torch", "tensorflow"}
        offenders = []
        for path in _source_files():
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    if name in forbidden_modules:
                        offenders.append((path.name, name))
        self.assertEqual(offenders, [], f"forbidden random/ML imports found: {offenders}")


class TestSingleResponsibility(unittest.TestCase):
    def test_no_network_or_file_io_modules_imported(self):
        # This package computes evidence from bars handed to it -- it
        # never talks to a socket, a broker, or the filesystem.
        forbidden_modules = {"socket", "http.client", "urllib.request", "requests"}
        offenders = []
        for path in _source_files():
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    if name in forbidden_modules:
                        offenders.append((path.name, name))
        self.assertEqual(offenders, [], f"forbidden I/O imports found: {offenders}")

    def test_public_surface_has_no_trade_execution_method(self):
        from phantom.evidence_engine.engine import EvidenceEngine

        forbidden_method_names = {"submit_order", "place_trade", "execute", "close_position", "open_position"}
        public_methods = {name for name in dir(EvidenceEngine) if not name.startswith("_")}
        self.assertEqual(public_methods & forbidden_method_names, set())


if __name__ == "__main__":
    unittest.main()
