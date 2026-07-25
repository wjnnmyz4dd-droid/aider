"""Structural boundary tests (Final Release Hardening, persisted
compliance state) -- verified by source inspection, never merely
asserted in prose. `titan_protocol.compliance_state_store` may import
exactly two things from `titan_protocol.compliance_engine`: `.models`
(the caller-owned `AccountState`/`ComplianceLockState`/
`LockRecommendation` types it persists) and `.lock` (ADR-028's own pure
daily-reset/lock-transition helpers, reused rather than
reimplemented) -- never `.engine`, `.daily_loss`, `.drawdown`, or any
other rule-evaluation module. It must never import any other
pipeline-stage package, and it must never itself compute a compliance
decision (that stays `ComplianceEngine`'s sole authority, per ADR-028
Hard Rule 6 -- this store is a caller-owned persistence layer only)."""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
STORE_DIR = REPO_ROOT / "titan_protocol" / "compliance_state_store"


class TestOnlyAuthorizedComplianceEngineSubmodulesAreImported(unittest.TestCase):
    def test_only_models_and_lock_are_ever_imported(self):
        pattern = re.compile(r"^from titan_protocol\.compliance_engine(\.\S+)?\s+import", re.MULTILINE)
        violations = []
        for path in STORE_DIR.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for match in pattern.finditer(text):
                submodule = match.group(1) or ""
                if submodule not in (".models", ".lock"):
                    violations.append((str(path.relative_to(REPO_ROOT)), match.group(0)))
        self.assertEqual(violations, [], f"compliance_state_store file(s) import a compliance_engine module beyond .models/.lock: {violations}")

    def test_no_file_imports_any_other_pipeline_stage_package(self):
        forbidden_packages = (
            "evidence_engine", "strategy_engine", "risk_engine", "runtime",
            "bridge", "reliability", "market_data_ingestion", "news_ingestion",
            "market_intelligence",
        )
        pattern = re.compile(
            r"^from titan_protocol\.(" + "|".join(forbidden_packages) + r")\b", re.MULTILINE,
        )
        violations = []
        for path in STORE_DIR.rglob("*.py"):
            if pattern.search(path.read_text(encoding="utf-8")):
                violations.append(str(path.relative_to(REPO_ROOT)))
        self.assertEqual(violations, [], f"compliance_state_store file(s) import an unauthorized pipeline-stage package: {violations}")

    def test_no_file_imports_phantom_pipeline(self):
        pattern = re.compile(r"phantom_pipeline")
        violations = [
            str(path.relative_to(REPO_ROOT))
            for path in STORE_DIR.rglob("*.py")
            if pattern.search(path.read_text(encoding="utf-8"))
        ]
        self.assertEqual(violations, [], f"compliance_state_store file(s) reference phantom_pipeline: {violations}")


class TestNoReimplementationOfComplianceEngineInternals(unittest.TestCase):
    def test_no_rule_evaluation_logic_is_duplicated(self):
        """Hard boundary: this store persists/retrieves state only -- it
        must never itself evaluate a compliance rule, compute a
        compliance decision, or compute daily-loss/drawdown/profit
        percentages (those stay `ComplianceEngine`'s sole authority,
        derived live from the balances this store persists)."""
        forbidden_reimplementation_markers = (
            "def evaluate_daily_loss", "def evaluate_drawdown", "def evaluate_profit_protection",
            "ComplianceDecision.APPROVE", "ComplianceDecision.REDUCE", "ComplianceDecision.REJECT",
            "daily_loss_pct_consumed", "def compute_compliance_score",
        )
        violations = []
        for path in STORE_DIR.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for forbidden in forbidden_reimplementation_markers:
                if forbidden in text:
                    violations.append((str(path.relative_to(REPO_ROOT)), forbidden))
        self.assertEqual(violations, [], f"compliance_state_store file(s) appear to reimplement ComplianceEngine internals: {violations}")


class TestFrozenPackagesAreUntouched(unittest.TestCase):
    """Confirms this phase's own claim: adding persisted compliance
    state touches only the new compliance_state_store package + its
    tests + the explicitly-authorized deployment/config surface, never
    ComplianceEngine itself or any other frozen pipeline-stage package."""

    _FROZEN_PREFIXES = (
        "titan_protocol/evidence_engine/",
        "titan_protocol/market_intelligence/",
        "titan_protocol/strategy_engine/",
        "titan_protocol/risk_engine/",
        "titan_protocol/compliance_engine/",
        "titan_protocol/runtime/",
        "titan_protocol/reliability/",
        "titan_protocol/market_data_ingestion/",
        "titan_protocol/news_ingestion/",
    )

    # Pair-level in-flight command guard (a later, separately-authorized
    # change, not part of Final Release Hardening): closes the traced
    # defect where RuntimeOrchestrator submitted a fresh TradeCommand
    # every cycle with no memory of one already outstanding for the same
    # pair. Additive only -- RuntimeOrchestrator gained one new optional
    # constructor parameter defaulting to None (old behavior unchanged
    # for every existing caller), CycleOutcome gained one new enum
    # member, and the registry itself is a brand new, independent
    # module. This exception documents that this phase's own claim
    # ("touches only compliance_state_store") is unaffected; it does not
    # relax the check for anything else.
    _LATER_AUTHORIZED_EXCEPTIONS = (
        "titan_protocol/runtime/engine.py",
        "titan_protocol/runtime/models.py",
        "titan_protocol/runtime/in_flight_commands.py",
        # max_positions_per_pair=1 production-invariant fix (also later,
        # separately-authorized): default corrected from 2 to 1, made
        # configurable, and given dedicated position-limit-check logging.
        # Additive/config-only in both files -- no compliance_state_store
        # behavior is touched.
        "titan_protocol/compliance_engine/models.py",
        "titan_protocol/compliance_engine/engine.py",
        "titan_protocol/compliance_engine/logging_sink.py",
        # ADR-034 Amendment 8/9 (later, separately-authorized): a bounded
        # timeout for the position-confirmation wait, plus restart-safe
        # persistence of InFlightCommandRegistry's minimal pair-level
        # state -- additive only, no compliance_state_store behavior
        # touched.
        "titan_protocol/runtime/config.py",
        "titan_protocol/runtime/in_flight_store.py",
        # Reservation-lifecycle leak fix (later, separately-authorized):
        # RiskEngine.release_reservation() previously had no caller;
        # RuntimeOrchestrator's InFlightCommandRegistry now carries each
        # trade's reservation_id through the existing command lifecycle
        # and releases it at every terminal/confirmed state. Additive
        # only (two new health-diagnostic passthrough methods plus an
        # extended docstring on the pre-existing release_reservation()) --
        # no compliance_state_store behavior touched.
        "titan_protocol/risk_engine/engine.py",
        # ADR-035 Phase 0 (later, separately-authorized): Evidence Engine
        # amendment adding OpeningRangeState / EvidenceSnapshot.opening_ranges
        # -- additive only (new model, new opening_range.py module, one new
        # _analyze() call, new defaulted config fields), no
        # compliance_state_store behavior touched.
        "titan_protocol/evidence_engine/__init__.py",
        "titan_protocol/evidence_engine/config.py",
        "titan_protocol/evidence_engine/engine.py",
        "titan_protocol/evidence_engine/models.py",
        "titan_protocol/evidence_engine/opening_range.py",
    )

    def test_no_frozen_pipeline_package_is_touched_by_this_change(self):
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
        self.assertEqual(violations, [], f"Final Release Hardening (compliance state store) touched a frozen pipeline package: {violations}")


if __name__ == "__main__":
    unittest.main()
