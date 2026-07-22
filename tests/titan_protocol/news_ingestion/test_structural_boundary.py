"""Structural boundary tests (Phase 3E, ADR-033 Part 2) -- verified by
source inspection, never merely asserted in prose. `titan_protocol.
news_ingestion` may import exactly one sibling package,
`titan_protocol.market_intelligence`, and only its `.models` (to build the
`NewsEvent` type MI's `evaluate()` already accepts) -- never MI's
`.engine`, `.news`, `.scoring`, or any other internal module, and never
reimplement MI's blackout/scoring/session logic itself (mission's own
"No provider-specific logic belongs inside Market Intelligence" /
"Market Intelligence owns event interpretation" split, mirrored in
reverse: news_ingestion owns transport only)."""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
NEWS_INGESTION_DIR = REPO_ROOT / "titan_protocol" / "news_ingestion"


class TestNoImportsBeyondMarketIntelligenceModels(unittest.TestCase):
    def test_only_market_intelligence_models_is_ever_imported(self):
        pattern = re.compile(r"^from titan_protocol\.market_intelligence(\.\S+)?\s+import", re.MULTILINE)
        violations = []
        for path in NEWS_INGESTION_DIR.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for match in pattern.finditer(text):
                submodule = match.group(1) or ""
                if submodule not in ("", ".models"):
                    violations.append((str(path.relative_to(REPO_ROOT)), match.group(0)))
        self.assertEqual(violations, [], f"news_ingestion file(s) import a Market Intelligence module beyond .models: {violations}")

    def test_no_file_imports_any_other_titan_protocol_pipeline_stage_package(self):
        forbidden_packages = (
            "evidence_engine", "strategy_engine", "risk_engine", "compliance_engine",
            "runtime", "bridge", "reliability", "market_data_ingestion",
        )
        pattern = re.compile(
            r"^from titan_protocol\.(" + "|".join(forbidden_packages) + r")\b", re.MULTILINE,
        )
        violations = []
        for path in NEWS_INGESTION_DIR.rglob("*.py"):
            if pattern.search(path.read_text(encoding="utf-8")):
                violations.append(str(path.relative_to(REPO_ROOT)))
        self.assertEqual(violations, [], f"news_ingestion file(s) import an unauthorized pipeline-stage package: {violations}")

    def test_no_file_imports_phantom_pipeline(self):
        pattern = re.compile(r"phantom_pipeline", re.MULTILINE)
        violations = [
            str(path.relative_to(REPO_ROOT))
            for path in NEWS_INGESTION_DIR.rglob("*.py")
            if pattern.search(path.read_text(encoding="utf-8"))
        ]
        self.assertEqual(violations, [], f"news_ingestion file(s) reference phantom_pipeline: {violations}")


class TestNoReimplementationOfMarketIntelligenceInternals(unittest.TestCase):
    def test_no_blackout_scoring_or_session_logic_is_duplicated(self):
        """Hard boundary: news_ingestion supplies events and a trust
        boolean only -- it must never itself compute a blackout
        decision, a news score, or a trade-readiness verdict (that
        remains Market Intelligence Engine's sole authority,
        unmodified)."""
        forbidden_reimplementation_markers = (
            "def compute_blackout", "def compute_news_score", "def evaluate_session",
            "def build_trade_readiness", "def build_pair_safety", "blackout_active =",
        )
        violations = []
        for path in NEWS_INGESTION_DIR.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for forbidden in forbidden_reimplementation_markers:
                if forbidden in text:
                    violations.append((str(path.relative_to(REPO_ROOT)), forbidden))
        self.assertEqual(violations, [], f"news_ingestion file(s) appear to reimplement Market Intelligence internals: {violations}")


class TestFrozenPackagesAreUntouched(unittest.TestCase):
    """Confirms this phase's own claim (mission: 'Do NOT modify
    Strategy, Risk, Compliance, Runtime, Evidence, or Execution
    logic'): the git diff touches only news_ingestion + its tests +
    the explicitly-authorized deployment/config/docs/release surface,
    never any frozen engine package. Skipped (not failed) outside a
    git checkout."""

    _FROZEN_PREFIXES = (
        "titan_protocol/evidence_engine/",
        "titan_protocol/market_intelligence/",
        "titan_protocol/strategy_engine/",
        "titan_protocol/risk_engine/",
        "titan_protocol/compliance_engine/",
        "titan_protocol/runtime/",
        "titan_protocol/bridge/",
        "titan_protocol/reliability/",
    )

    # Pair-level in-flight command guard (a later, separately-authorized
    # change, not part of Phase 3E): closes the traced defect where
    # RuntimeOrchestrator submitted a fresh TradeCommand every cycle with
    # no memory of one already outstanding for the same pair. Additive
    # only in both files -- BridgeEngine gained one passthrough method
    # (command_resolved()), RuntimeOrchestrator gained one new optional
    # constructor parameter defaulting to None (old behavior unchanged
    # for every existing caller) -- and the registry itself is a brand
    # new, Bridge-independent module. This exception documents that this
    # phase's own claim ("touches only news_ingestion") is unaffected;
    # it does not relax the check for anything else.
    _LATER_AUTHORIZED_EXCEPTIONS = (
        "titan_protocol/bridge/engine.py",
        "titan_protocol/runtime/engine.py",
        "titan_protocol/runtime/models.py",
        "titan_protocol/runtime/in_flight_commands.py",
        # max_positions_per_pair=1 production-invariant fix (also later,
        # separately-authorized): default corrected from 2 to 1, made
        # configurable, and given dedicated position-limit-check logging.
        # bridge/server.py's one-line change threads a `now` argument into
        # handle_positions() (closes the ExecutionReport-vs-PositionReport
        # race) -- additive/config-only across all four files, no
        # news_ingestion behavior is touched.
        "titan_protocol/bridge/server.py",
        "titan_protocol/compliance_engine/models.py",
        "titan_protocol/compliance_engine/engine.py",
        "titan_protocol/compliance_engine/logging_sink.py",
        # ADR-034 Amendment 4 transport-default flip + status-classification
        # fix (later, separately-authorized): BridgeConfig.transport's
        # shipped default reverts from "socket" to "http" -- a config
        # default only, no news_ingestion behavior touched.
        "titan_protocol/bridge/config.py",
        # ADR-034 Amendment 5/6 (later, separately-authorized): the
        # undelivered-command-abandonment fix and its production-readiness
        # hardening add CommandQueue.is_abandoned() and its
        # mutual-exclusion _abandoned_ids bookkeeping -- additive only, no
        # news_ingestion behavior touched.
        "titan_protocol/bridge/command_queue.py",
        # ADR-034 Amendment 8/9 (later, separately-authorized): a bounded
        # timeout for the position-confirmation wait, plus restart-safe
        # persistence of InFlightCommandRegistry's minimal pair-level
        # state -- additive only, no news_ingestion behavior touched.
        "titan_protocol/runtime/config.py",
        "titan_protocol/runtime/in_flight_store.py",
        # ADR-034 Amendment 10 (later, separately-authorized): native
        # MQL5 socket transport removed entirely, HTTP-only -- deletes
        # titan_protocol/bridge/socket_transport.py, drops its export
        # from __init__.py, and removes its now-dead metrics counters
        # from metrics.py. Transport-layer only, no news_ingestion
        # behavior touched.
        "titan_protocol/bridge/__init__.py",
        "titan_protocol/bridge/metrics.py",
        "titan_protocol/bridge/socket_transport.py",
    )

    def test_no_frozen_pipeline_package_is_touched_by_this_phase(self):
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        if result.returncode != 0:
            self.skipTest("not a git checkout")
        violations = [
            line[3:] for line in result.stdout.splitlines()
            if line[3:].startswith(self._FROZEN_PREFIXES) and line[3:] not in self._LATER_AUTHORIZED_EXCEPTIONS
        ]
        self.assertEqual(violations, [], f"Phase 3E touched a frozen pipeline package: {violations}")


if __name__ == "__main__":
    unittest.main()
