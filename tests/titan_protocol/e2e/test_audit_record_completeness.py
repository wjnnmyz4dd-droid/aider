"""Auditability audit: checks `RuntimeAuditRecord`'s actual field list
(`titan_protocol/runtime/models.py`) against this checklist's own
required-field list -- Decision ID, Configuration Version, Trading
Profile, Evidence Summary, Market Intelligence Summary, Strategy, Trade
Intent, Risk Decision, Compliance Decision, Bridge Decision, Execution
Result, Reason Chain, Timing.

Originally written for Phase 3B (ADR-031), when several categories were
only PARTIAL or MISSING and documented as Known Limitations pending a
future amendment, since Phase 3B's own bug policy allowed only
defect fixes to the then-frozen Runtime package, not new fields.

Final Release Hardening (requirement 4, "audit-record completeness")
is that amendment: it closed every gap this file used to document,
purely additively (every new field records an already-computed value
from another engine's own snapshot -- see
`titan_protocol/runtime/engine.py`'s `_record()` closure). This file
now asserts the closed state instead of the old gaps, so a future
regression that silently drops one of these fields is still caught.

Confirmed mapping (by reading the dataclass, not inferred):

| Checklist field            | `RuntimeAuditRecord` field(s)                        | Status |
|-----------------------------|-------------------------------------------------------|--------|
| Decision ID                 | `decision_id` (+ `cycle_id`/`pair`)                    | present |
| Configuration Version       | `configuration_version` + `config_schema_version`      | present |
| Trading Profile             | `profile_id`                                           | present |
| Symbol / Timeframe          | `pair` + `timeframe`                                   | present |
| Evidence Summary            | `evidence_id` + `evidence_summary`                     | present |
| Market Intelligence Summary | `market_intelligence_summary`                          | present |
| Strategy                    | `selected_strategy`                                    | present |
| Trade Intent                | `trade_intent`                                         | present |
| Risk Decision                | `risk_approved` + `risk_reasons`                       | present |
| Compliance Decision           | `compliance_decision` + `compliance_triggered_rules` + `compliance_lock_trigger`/`compliance_lock_reason` | present |
| Bridge Decision                | `bridge_error` + `bridge_correlation_id`              | present |
| Reason Chain                    | `reasons`                                            | present |
| Timing                           | `started_at`/`ended_at`/`duration_ms`/`stage_timings` | present |
| Snapshot hash / decision fingerprint | `snapshot_hash` + `decision_fingerprint`          | present |
"""

from __future__ import annotations

import dataclasses
import unittest

from titan_protocol.runtime.models import RuntimeAuditRecord

_ACTUAL_FIELDS = {f.name for f in dataclasses.fields(RuntimeAuditRecord)}

_MAPPED_CHECKLIST_CATEGORIES = {
    "decision_id": {"cycle_id", "pair", "decision_id"},
    "configuration_version": {"configuration_version", "config_schema_version"},
    "trading_profile": {"profile_id"},
    "symbol_timeframe": {"pair", "timeframe"},
    "evidence_summary": {"evidence_id", "evidence_summary"},
    "market_intelligence_summary": {"market_intelligence_summary"},
    "strategy": {"selected_strategy"},
    "trade_intent": {"trade_intent"},
    "risk_decision": {"risk_approved", "risk_reasons"},
    "compliance_decision": {
        "compliance_decision", "compliance_triggered_rules",
        "compliance_lock_trigger", "compliance_lock_reason",
    },
    "bridge_decision": {"bridge_error", "bridge_correlation_id"},
    "execution_result": {"outcome"},
    "reason_chain": {"reasons"},
    "timing": {"started_at", "ended_at", "duration_ms", "stage_timings"},
    "fingerprints": {"snapshot_hash", "decision_fingerprint"},
}


class TestMappedChecklistCategoriesArePresent(unittest.TestCase):
    def test_every_mapped_category_field_actually_exists_on_the_record(self):
        for category, fields in _MAPPED_CHECKLIST_CATEGORIES.items():
            missing = fields - _ACTUAL_FIELDS
            self.assertEqual(missing, set(), f"{category}: expected field(s) {missing} not found on RuntimeAuditRecord")

    def test_every_actual_field_is_accounted_for_by_the_mapping_or_is_engine_versions(self):
        """Guards the audit itself against silent drift: if a future
        field is added to `RuntimeAuditRecord` and forgotten here, or a
        mapped field is removed, this test breaks and forces the
        mapping table above to be updated."""
        mapped_fields = {f for fields in _MAPPED_CHECKLIST_CATEGORIES.values() for f in fields}
        # `stage_reached` (which stage a failed/rejected cycle reached)
        # and `engine_versions` (audit provenance) are legitimate fields
        # that don't correspond to one of the named checklist
        # categories -- accounted for explicitly, not silently dropped.
        unaccounted = _ACTUAL_FIELDS - mapped_fields - {"stage_reached", "engine_versions"}
        self.assertEqual(unaccounted, set(), f"unmapped RuntimeAuditRecord field(s): {unaccounted}")


class TestPreviouslyDocumentedGapsAreNowClosed(unittest.TestCase):
    """Mirror-image of the old `TestConfirmedGaps` class this file used
    to have -- each of these used to assert an absence (documented as a
    Known Limitation); Final Release Hardening closed every one, so
    these now assert presence instead."""

    def test_a_market_intelligence_summary_field_now_exists(self):
        self.assertIn("market_intelligence_summary", _ACTUAL_FIELDS)

    def test_evidence_summary_is_now_a_rich_string_not_only_an_identifier(self):
        field = next(f for f in dataclasses.fields(RuntimeAuditRecord) if f.name == "evidence_summary")
        self.assertEqual(field.type, "str")

    def test_risk_decision_now_carries_reasons_alongside_the_bare_bool(self):
        field = next(f for f in dataclasses.fields(RuntimeAuditRecord) if f.name == "risk_reasons")
        self.assertEqual(field.type, "Tuple[str, ...]")

    def test_bridge_decision_now_carries_a_correlation_id_for_the_success_path_too(self):
        field = next(f for f in dataclasses.fields(RuntimeAuditRecord) if f.name == "bridge_correlation_id")
        self.assertEqual(field.type, "Optional[str]")


if __name__ == "__main__":
    unittest.main()
