"""Calendar acquisition orchestrator (Phase 9D-R1) — DATA ONLY.

Composes provider -> freshness -> normalization -> provenance -> a bundle in the
EXACT shape the existing ``FileNewsDataProvider`` + ``compliance/news.py`` consume.
Deterministic given (provider output, now). No trade authority, no wall clock of
its own (``now`` is injected), no networking (that lives in the provider).

The produced bundle's ``as_of`` is the ACQUISITION time, so if the acquirer stops
refreshing the file the bundle ages and the existing compliance freshness rule
eventually fails closed (§7/§18) — the acquisition layer can never keep trading
alive on silently stale news.
"""

from __future__ import annotations

from ..bridge import serialize
from . import freshness, normalize
from .contract import (COMPLETENESS_CROSS_VERIFIED, COMPLETENESS_SOURCE_DECLARED,
                       COMPLETENESS_UNESTABLISHED, SCHEMA_VERSION, AcquisitionError,
                       Reason)


class CalendarAcquirer:
    """Turns a provider's raw calendar into a verified, provenance-stamped bundle.

    ``corroborators`` is an optional list of additional providers used ONLY to
    upgrade completeness to cross-verified where events agree (architectural seam
    for §10; empty by default — no unnecessary duplicate providers this phase)."""

    def __init__(self, provider, cfg, *, corroborators=None):
        self.provider = provider
        self.cfg = cfg
        self.corroborators = list(corroborators or [])

    def refresh(self, now):
        """Acquire + validate + normalize into a bundle dict, or raise
        :class:`AcquisitionError` (fail closed — never returns a partial bundle)."""
        raw = self.provider.fetch(now)
        freshness.check_source_freshness(raw, now, self.cfg)
        events, warnings = normalize.normalize_events(raw)
        if not events:
            raise AcquisitionError(Reason.EMPTY_PAYLOAD, {"event_count": 0})

        completeness = (COMPLETENESS_SOURCE_DECLARED if raw.complete is True
                        else COMPLETENESS_UNESTABLISHED)
        if self.corroborators:
            events, completeness = self._cross_verify(events, now, completeness)

        fetched_iso = serialize.iso_utc(raw.fetched_at)
        source_as_of_iso = serialize.iso_utc(raw.source_as_of) if raw.source_as_of else None
        as_of = fetched_iso                       # acquisition time drives freshness

        provenance = {
            "source_name": raw.source_name,
            "source_identifier": raw.source_identifier,
            "source_as_of": source_as_of_iso,
            "fetched_at": fetched_iso,
            "normalized_at": fetched_iso,
            "bundle_as_of": as_of,
            "provider_version": raw.provider_version,
            "schema_version": SCHEMA_VERSION,
            "completeness": completeness,
            "event_count": len(events),
            "trusted_source": bool(raw.trusted),
            "normalization_warnings": sorted(set(warnings)),
        }
        bundle = {
            "schema_version": SCHEMA_VERSION,
            "as_of": as_of,
            "verified": bool(raw.trusted),
            "provenance": provenance,
            "events": events,
        }
        # Tamper-evident digest for audit/provenance. The news gate ignores it; it
        # is available to any consumer that wants to verify the file end-to-end.
        return serialize.with_integrity_digest(bundle)

    def _cross_verify(self, events, now, completeness):
        """Upgrade completeness to cross-verified for events also present in a
        corroborating source (by stable source_event_key). Events NOT corroborated
        keep their own verification_state — never downgraded silently, never merged
        into conflicts (a corroborator conflict fails closed in normalize)."""
        corroborated = set()
        for c in self.corroborators:
            raw = c.fetch(now)
            freshness.check_source_freshness(raw, now, self.cfg)
            other, _ = normalize.normalize_events(raw)
            corroborated |= {e["source_event_key"] for e in other}
        if corroborated:
            for e in events:
                if e["source_event_key"] in corroborated:
                    e["cross_verified"] = True
            completeness = COMPLETENESS_CROSS_VERIFIED
        return events, completeness
