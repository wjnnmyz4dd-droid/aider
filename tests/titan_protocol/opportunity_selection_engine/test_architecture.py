"""Architecture tests (ADR-037 §1, Plan §9): no sizing/execution/decision
vocabulary, no import of `phantom_pipeline`/`titan_protocol.bridge`/
`titan_protocol.validation_engine`, exactly one permitted upstream package
(`titan_protocol.strategy_engine` -- the sole sanctioned route to the
`SessionName`/`TradeIntent` types this package itself does not own), no
randomness/ML imports."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[3] / "titan_protocol" / "opportunity_selection_engine"

FORBIDDEN_IDENTIFIERS = {
    "BUY", "SELL", "place_order", "submit_order", "execute_trade", "place_trade",
    "select_direction", "choose_direction", "approve_compliance", "ftmo_check",
    "parse_news", "fetch_news", "calculate_risk", "position_size", "lot_size",
}

FORBIDDEN_IMPORT_PREFIXES = ("phantom_pipeline", "titan_protocol.bridge", "titan_protocol.validation_engine")
ALLOWED_UPSTREAM_PREFIXES = ("titan_protocol.strategy_engine",)
FORBIDDEN_RANDOM_ML_MODULES = {"random", "numpy.random", "sklearn", "torch", "tensorflow"}


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
        self.assertEqual(offenders, [], f"forbidden vocabulary found in: {offenders}")

    def test_no_public_method_resembles_a_trade_decision_api(self):
        from titan_protocol.opportunity_selection_engine.engine import OpportunitySelectionEngine

        forbidden_method_names = {"decide", "approve", "reject", "execute", "size"}
        public_methods = {name for name in dir(OpportunitySelectionEngine) if not name.startswith("_")}
        self.assertEqual(public_methods & forbidden_method_names, set())


class TestNoForbiddenImports(unittest.TestCase):
    def test_no_import_of_phantom_pipeline_bridge_or_validation_engine(self):
        offenders = []
        for path in _source_files():
            tree = ast.parse(path.read_text(), filename=str(path))
            for name in _imported_names(tree):
                if any(name == p or name.startswith(p + ".") for p in FORBIDDEN_IMPORT_PREFIXES):
                    offenders.append((str(path.relative_to(PACKAGE_ROOT)), name))
        self.assertEqual(offenders, [], f"forbidden imports found: {offenders}")

    def test_only_permitted_upstream_packages_are_imported(self):
        offenders = []
        for path in _source_files():
            tree = ast.parse(path.read_text(), filename=str(path))
            for name in _imported_names(tree):
                if name.startswith("titan_protocol.") and not name.startswith("titan_protocol.opportunity_selection_engine"):
                    if not any(name.startswith(p) for p in ALLOWED_UPSTREAM_PREFIXES):
                        offenders.append((str(path.relative_to(PACKAGE_ROOT)), name))
        self.assertEqual(offenders, [], f"unexpected upstream import: {offenders}")

    def test_no_evidence_engine_or_market_intelligence_or_risk_or_compliance_import(self):
        """ADR-037's own package-boundary decision (Plan §1, §9): this
        package may not import `evidence_engine`, `market_intelligence`,
        `risk_engine`, or `compliance_engine` directly -- `SessionName`
        and `TradeIntent` are sourced exclusively via the one permitted
        upstream package, `titan_protocol.strategy_engine`."""
        forbidden = (
            "titan_protocol.evidence_engine", "titan_protocol.market_intelligence",
            "titan_protocol.risk_engine", "titan_protocol.compliance_engine", "titan_protocol.runtime",
        )
        offenders = []
        for path in _source_files():
            tree = ast.parse(path.read_text(), filename=str(path))
            for name in _imported_names(tree):
                if any(name == p or name.startswith(p + ".") for p in forbidden):
                    offenders.append((str(path.relative_to(PACKAGE_ROOT)), name))
        self.assertEqual(offenders, [], f"forbidden cross-engine imports found: {offenders}")

    def test_no_random_or_ml_imports(self):
        offenders = []
        for path in _source_files():
            tree = ast.parse(path.read_text(), filename=str(path))
            for name in _imported_names(tree):
                if name in FORBIDDEN_RANDOM_ML_MODULES:
                    offenders.append((str(path.relative_to(PACKAGE_ROOT)), name))
        self.assertEqual(offenders, [], f"forbidden random/ML imports found: {offenders}")


if __name__ == "__main__":
    unittest.main()
