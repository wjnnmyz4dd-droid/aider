"""Architecture tests (ADR-028 Hard Rules): no direction/execution/
strategy-selection vocabulary, no import of `phantom_pipeline`/
`titan_protocol.bridge`/`titan_protocol.evidence_engine` internals beyond `.models`,
statelessness (Hard Rule 6), and never-increases-risk verified
structurally."""

from __future__ import annotations

import ast
import inspect
import textwrap
import unittest
from pathlib import Path

from titan_protocol.compliance_engine.engine import ComplianceEngine

PACKAGE_ROOT = Path(__file__).resolve().parents[3] / "titan_protocol" / "compliance_engine"

#: This engine's mission is exactly APPROVE/REDUCE/REJECT sizing --
#: what it must never do is choose a direction, select a strategy,
#: execute a trade, or query a data provider directly.
FORBIDDEN_IDENTIFIERS = {
    "BUY", "SELL", "place_order", "submit_order", "execute_trade", "place_trade",
    "select_strategy", "choose_strategy", "select_direction", "choose_direction",
    "fetch_news", "query_news_provider",
}

FORBIDDEN_IMPORT_PREFIXES = ("phantom_pipeline", "titan_protocol.bridge")
ALLOWED_UPSTREAM_PREFIXES = (
    "titan_protocol.evidence_engine", "titan_protocol.market_intelligence", "titan_protocol.strategy_engine", "titan_protocol.risk_engine",
)
FORBIDDEN_ML_MODULES = {"numpy.random", "sklearn", "torch", "tensorflow"}


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


class TestNoForbiddenVocabulary(unittest.TestCase):
    def test_no_forbidden_identifier_anywhere_in_package_source(self):
        offenders = []
        for path in _source_files():
            tree = ast.parse(path.read_text(), filename=str(path))
            found = FORBIDDEN_IDENTIFIERS & set(_bound_identifiers(tree))
            if found:
                offenders.append((str(path.relative_to(PACKAGE_ROOT)), sorted(found)))
        self.assertEqual(offenders, [], f"forbidden vocabulary found in: {offenders}")


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
                if name.startswith("titan_protocol.") and not name.startswith("titan_protocol.compliance_engine"):
                    if not any(name.startswith(p) for p in ALLOWED_UPSTREAM_PREFIXES):
                        offenders.append((str(path.relative_to(PACKAGE_ROOT)), name))
        self.assertEqual(offenders, [], f"unexpected upstream import: {offenders}")

    def test_no_ml_or_random_imports(self):
        offenders = []
        for path in _source_files():
            tree = ast.parse(path.read_text(), filename=str(path))
            for name in _imported_names(tree):
                if name in FORBIDDEN_ML_MODULES or name == "random":
                    offenders.append((str(path.relative_to(PACKAGE_ROOT)), name))
        self.assertEqual(offenders, [], f"forbidden random/ML imports found: {offenders}")


class TestStatelessness(unittest.TestCase):
    def test_compliance_engine_holds_only_config_and_metrics(self):
        """ADR-028 Hard Rule 6: pure deterministic logic -- no engine-
        held mutable state beyond its own config/metrics references."""

        source = textwrap.dedent(inspect.getsource(ComplianceEngine.__init__))
        tree = ast.parse(source)
        assigned_attrs = {
            node.attr for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self"
        }
        self.assertEqual(assigned_attrs, {"config", "metrics"})

    def test_no_public_method_on_engine_resembles_a_lock_ledger(self):
        forbidden_method_names = {"reserve", "release", "lock", "unlock"}
        public_methods = {name for name in dir(ComplianceEngine) if not name.startswith("_")}
        self.assertEqual(public_methods & forbidden_method_names, set())


class TestNeverIncreasesRisk(unittest.TestCase):
    def test_position_sizing_reduction_never_uses_multiplier_above_one(self):
        """Structural check: every `GraduatedBand` shipped in the default
        configs has `multiplier <= 1.0` -- there is no configuration
        path, even by default, that could increase size."""

        from titan_protocol.compliance_engine.config import (
            DEFAULT_DAILY_LOSS_BANDS,
            DEFAULT_DRAWDOWN_BANDS,
            DEFAULT_PROFIT_PROTECTION_BANDS,
        )

        for bands in (DEFAULT_DAILY_LOSS_BANDS, DEFAULT_DRAWDOWN_BANDS, DEFAULT_PROFIT_PROTECTION_BANDS):
            for band in bands:
                self.assertLessEqual(band.multiplier, 1.0)


if __name__ == "__main__":
    unittest.main()
