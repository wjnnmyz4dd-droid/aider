"""Architecture tests (ADR-026 Hard Rules 1-2): no trade-decision
vocabulary, no import from `phantom_pipeline/` or `phantom/bridge/`
(the only permitted upstream imports are `phantom.evidence_engine` and
`phantom.market_intelligence`), no randomness.

Amendment 1 narrows Hard Rule 1's "no BUY/SELL" to allow exactly one
thing: the `TradeIntent` enum's `BUY`/`SELL` members, a directional
conclusion of an already-qualified entry thesis -- never a size, order,
or execution artifact. `BUY`/`SELL` are therefore removed from the
forbidden-identifier set below; every execution/sizing term remains
forbidden, and `TestNoSharedMutableEligibilityState` (below) still
verifies no method exists that *selects* or *chooses* a direction --
only a field that already carries one."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[3] / "phantom" / "strategy_engine"

FORBIDDEN_IDENTIFIERS = {
    "position_size", "stop_loss", "take_profit",
    "order_type", "place_order", "submit_order", "lot_size",
}

FORBIDDEN_IMPORT_PREFIXES = ("phantom_pipeline", "phantom.bridge")
ALLOWED_UPSTREAM_PREFIXES = ("phantom.evidence_engine", "phantom.market_intelligence")


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


class TestNoTradeDecisionVocabulary(unittest.TestCase):
    def test_no_forbidden_identifier_anywhere_in_package_source(self):
        offenders = []
        for path in _source_files():
            tree = ast.parse(path.read_text(), filename=str(path))
            found = FORBIDDEN_IDENTIFIERS & set(_bound_identifiers(tree))
            if found:
                offenders.append((str(path.relative_to(PACKAGE_ROOT)), sorted(found)))
        self.assertEqual(offenders, [], f"forbidden trade-decision vocabulary found in: {offenders}")


class TestNoForbiddenImports(unittest.TestCase):
    def test_no_import_of_phantom_pipeline_or_bridge(self):
        offenders = []
        for path in _source_files():
            tree = ast.parse(path.read_text(), filename=str(path))
            for name in _imported_names(tree):
                if any(name == p or name.startswith(p + ".") for p in FORBIDDEN_IMPORT_PREFIXES):
                    offenders.append((str(path.relative_to(PACKAGE_ROOT)), name))
        self.assertEqual(offenders, [], f"forbidden imports found: {offenders}")

    def test_only_evidence_engine_and_market_intelligence_are_imported_upstream(self):
        offenders = []
        for path in _source_files():
            tree = ast.parse(path.read_text(), filename=str(path))
            for name in _imported_names(tree):
                if name.startswith("phantom.") and not name.startswith("phantom.strategy_engine"):
                    if not any(name.startswith(p) for p in ALLOWED_UPSTREAM_PREFIXES):
                        offenders.append((str(path.relative_to(PACKAGE_ROOT)), name))
        self.assertEqual(offenders, [], f"unexpected upstream import: {offenders}")


class TestNoRandomnessOrMachineLearning(unittest.TestCase):
    def test_no_random_or_ml_imports(self):
        forbidden_modules = {"random", "numpy.random", "sklearn", "torch", "tensorflow"}
        offenders = []
        for path in _source_files():
            tree = ast.parse(path.read_text(), filename=str(path))
            for name in _imported_names(tree):
                if name in forbidden_modules:
                    offenders.append((str(path.relative_to(PACKAGE_ROOT)), name))
        self.assertEqual(offenders, [], f"forbidden random/ML imports found: {offenders}")


class TestNoSharedMutableEligibilityState(unittest.TestCase):
    def test_strategy_engine_config_has_no_mutation_method(self):
        from phantom.strategy_engine.config import StrategyEngineConfig

        forbidden_method_names = {"set_approved_pairs", "add_approved_pair", "update_eligibility", "mutate"}
        public_methods = {name for name in dir(StrategyEngineConfig) if not name.startswith("_")}
        self.assertEqual(public_methods & forbidden_method_names, set())

    def test_public_surface_has_no_trade_execution_method(self):
        from phantom.strategy_engine.engine import StrategyEngine

        forbidden_method_names = {"submit_order", "place_trade", "execute", "size_position", "select_direction"}
        public_methods = {name for name in dir(StrategyEngine) if not name.startswith("_")}
        self.assertEqual(public_methods & forbidden_method_names, set())


if __name__ == "__main__":
    unittest.main()
