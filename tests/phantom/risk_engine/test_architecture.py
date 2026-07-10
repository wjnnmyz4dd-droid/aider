"""Architecture tests (ADR-027 Hard Rules): no trade-decision/execution/
compliance vocabulary, no import of `phantom_pipeline`/`phantom.bridge`
(the only permitted upstream imports are `phantom.evidence_engine`,
`phantom.market_intelligence`, and `phantom.strategy_engine`), no
randomness anywhere except a seeded `random.Random` instance confined to
`monte_carlo.py`, no ML imports."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[3] / "phantom" / "risk_engine"

#: This engine's entire mission is sizing/exposure -- "lot_size",
#: "position_size" etc. are its legitimate vocabulary, unlike upstream
#: engines that must never size at all. What Risk Engine itself must
#: never do: choose a direction, select a strategy, execute a trade,
#: make a compliance/FTMO decision, or parse news.
FORBIDDEN_IDENTIFIERS = {
    "BUY", "SELL", "place_order", "submit_order", "execute_trade", "place_trade",
    "select_strategy", "choose_strategy", "select_direction", "choose_direction",
    "approve_compliance", "ftmo_check", "parse_news", "fetch_news",
}

FORBIDDEN_IMPORT_PREFIXES = ("phantom_pipeline", "phantom.bridge")
ALLOWED_UPSTREAM_PREFIXES = ("phantom.evidence_engine", "phantom.market_intelligence", "phantom.strategy_engine")
FORBIDDEN_RANDOM_ML_MODULES = {"numpy.random", "sklearn", "torch", "tensorflow"}


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

    def test_only_permitted_upstream_packages_are_imported(self):
        offenders = []
        for path in _source_files():
            tree = ast.parse(path.read_text(), filename=str(path))
            for name in _imported_names(tree):
                if name.startswith("phantom.") and not name.startswith("phantom.risk_engine"):
                    if not any(name.startswith(p) for p in ALLOWED_UPSTREAM_PREFIXES):
                        offenders.append((str(path.relative_to(PACKAGE_ROOT)), name))
        self.assertEqual(offenders, [], f"unexpected upstream import: {offenders}")

    def test_no_ml_imports(self):
        offenders = []
        for path in _source_files():
            tree = ast.parse(path.read_text(), filename=str(path))
            for name in _imported_names(tree):
                if name in FORBIDDEN_RANDOM_ML_MODULES:
                    offenders.append((str(path.relative_to(PACKAGE_ROOT)), name))
        self.assertEqual(offenders, [], f"forbidden ML imports found: {offenders}")


class TestRandomnessConfinedToMonteCarlo(unittest.TestCase):
    """ADR-027 Hard Rule 7: no randomness in live sizing. `random` may
    only be imported by `monte_carlo.py`, and even there, only ever
    used to construct a seeded `random.Random(seed)` instance -- never
    a bare `random.<function>()` call against un-seeded global state."""

    def test_random_module_only_imported_by_monte_carlo(self):
        offenders = []
        for path in _source_files():
            if path.name == "monte_carlo.py":
                continue
            tree = ast.parse(path.read_text(), filename=str(path))
            if "random" in set(_imported_names(tree)):
                offenders.append(str(path.relative_to(PACKAGE_ROOT)))
        self.assertEqual(offenders, [], f"'random' imported outside monte_carlo.py: {offenders}")

    def test_monte_carlo_only_uses_random_via_seeded_instance(self):
        path = PACKAGE_ROOT / "monte_carlo.py"
        tree = ast.parse(path.read_text(), filename=str(path))
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "random":
                if node.attr != "Random":
                    offenders.append(node.attr)
        self.assertEqual(offenders, [], f"monte_carlo.py calls random.{{...}} directly instead of via a seeded random.Random instance: {offenders}")


class TestNoMutationOfConfigOrEngine(unittest.TestCase):
    def test_risk_engine_config_has_no_mutation_method(self):
        from phantom.risk_engine.config import RiskEngineConfig

        forbidden_method_names = {"set_confidence_schedule", "update_schedule", "mutate"}
        public_methods = {name for name in dir(RiskEngineConfig) if not name.startswith("_")}
        self.assertEqual(public_methods & forbidden_method_names, set())

    def test_public_surface_has_no_trade_execution_method(self):
        from phantom.risk_engine.engine import RiskEngine

        forbidden_method_names = {"submit_order", "place_trade", "execute", "select_direction", "approve_compliance"}
        public_methods = {name for name in dir(RiskEngine) if not name.startswith("_")}
        self.assertEqual(public_methods & forbidden_method_names, set())


if __name__ == "__main__":
    unittest.main()
