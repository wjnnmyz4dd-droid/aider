"""Phase 3B auditability audit: checks `RuntimeAuditRecord`'s actual
field list (`titan_protocol/runtime/models.py`, frozen for Phase 3B) against
this checklist's own required-field list -- Decision ID, Configuration
Version, Trading Profile, Evidence Summary, Market Intelligence
Summary, Strategy, Trade Intent, Risk Decision, Compliance Decision,
Bridge Decision, Execution Result, Reason Chain, Timing -- and records
the real gaps as Known Limitations rather than silently patching the
frozen Runtime package (Phase 3B's own bug policy: additive fixes for
real defects only, no feature additions).

Confirmed mapping (by reading the dataclass, not inferred):

| Checklist field           | `RuntimeAuditRecord` field(s)              | Status  |
|----------------------------|--------------------------------------------|---------|
| Decision ID                | `cycle_id` + `pair`                         | present |
| Configuration Version      | `configuration_version`                     | present |
| Trading Profile            | `profile_id` (id only, not the full object) | present |
| Evidence Summary           | `evidence_id` (an id string, not a summary) | PARTIAL |
| Market Intelligence Summary| *(no field at all)*                         | MISSING |
| Strategy                   | `selected_strategy`                         | present |
| Trade Intent                | `trade_intent`                              | present |
| Risk Decision               | `risk_approved` (bool only, no sizing/tier) | PARTIAL |
| Compliance Decision         | `compliance_decision` (enum, no reduction%) | PARTIAL |
| Bridge Decision              | `bridge_error` (error path only)            | PARTIAL |
| Execution Result            | *(no field -- `outcome` implies it)*        | PARTIAL |
| Reason Chain                | `reasons`                                   | present |
| Timing                      | `started_at`/`ended_at`/`duration_ms`/`stage_timings` | present |

Known Limitations (recommended future ADR-031 Amendment, not
implemented here -- out of Phase 3B's scope, which may only fix real
defects in what's already Accepted, not add new fields to a frozen
type):
  - No Market Intelligence summary field exists on `RuntimeAuditRecord`
    at all -- an auditor cannot recover *why* a cycle's Market
    Intelligence stage passed or failed from the audit record alone.
  - `evidence_id` is an identifier, not a summary (composite score,
    trend, session) -- recovering the actual Evidence facts behind a
    decision requires re-fetching the original `EvidenceSnapshot`
    elsewhere, which may no longer be retained.
  - `risk_approved` collapses the whole Risk Decision to a bool --
    `approved_risk_r`, `confidence_tier`, and any rejection reason are
    not separately retained on the audit record itself (though
    `reasons` often carries a human-readable version of the same
    information).
  - `bridge_error` only covers the failure path; a successful
    submission's bridge-side result (e.g. broker ticket id) is not
    captured on the audit record -- `outcome == SUBMITTED` only tells
    you a `TradeCommand` was handed to the bridge, not what became of
    it.
"""

from __future__ import annotations

import dataclasses
import unittest

from titan_protocol.runtime.models import RuntimeAuditRecord

_ACTUAL_FIELDS = {f.name for f in dataclasses.fields(RuntimeAuditRecord)}

# Every checklist category this session could map to at least one real
# field -- i.e. "present" or "PARTIAL" in the table above, never
# "MISSING" (those are asserted separately, as an absence).
_MAPPED_CHECKLIST_CATEGORIES = {
    "decision_id": {"cycle_id", "pair"},
    "configuration_version": {"configuration_version"},
    "trading_profile": {"profile_id"},
    "evidence_summary": {"evidence_id"},
    "strategy": {"selected_strategy"},
    "trade_intent": {"trade_intent"},
    "risk_decision": {"risk_approved"},
    "compliance_decision": {"compliance_decision"},
    "bridge_decision": {"bridge_error"},
    "execution_result": {"outcome"},
    "reason_chain": {"reasons"},
    "timing": {"started_at", "ended_at", "duration_ms", "stage_timings"},
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
        # that don't correspond to one of the 13 named checklist
        # categories -- accounted for explicitly, not silently dropped.
        unaccounted = _ACTUAL_FIELDS - mapped_fields - {"stage_reached", "engine_versions"}
        self.assertEqual(unaccounted, set(), f"unmapped RuntimeAuditRecord field(s): {unaccounted}")


class TestConfirmedGaps(unittest.TestCase):
    def test_no_market_intelligence_summary_field_exists(self):
        """Confirmed MISSING category -- no field of any name related to
        Market Intelligence exists on RuntimeAuditRecord."""
        self.assertFalse(any("market_intelligence" in name or name == "mi_id" for name in _ACTUAL_FIELDS))

    def test_evidence_field_is_an_identifier_not_a_rich_summary(self):
        evidence_field = next(f for f in dataclasses.fields(RuntimeAuditRecord) if f.name == "evidence_id")
        self.assertEqual(evidence_field.type, "Optional[str]")

    def test_risk_decision_is_a_bare_bool_not_a_structured_decision(self):
        risk_field = next(f for f in dataclasses.fields(RuntimeAuditRecord) if f.name == "risk_approved")
        self.assertEqual(risk_field.type, "Optional[bool]")

    def test_bridge_field_only_models_the_error_path(self):
        bridge_field = next(f for f in dataclasses.fields(RuntimeAuditRecord) if f.name == "bridge_error")
        self.assertIn("ErrorCode", bridge_field.type)


if __name__ == "__main__":
    unittest.main()
