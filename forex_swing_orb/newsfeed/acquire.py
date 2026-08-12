"""Calendar acquisition orchestrator (Phase 9D-R1-R) — DATA ONLY.

Composes provider -> download sanity -> normalization -> coverage/effective
freshness -> provenance -> a bundle in the EXACT shape the existing
``FileNewsDataProvider`` + ``compliance/news.py`` consume. Deterministic given
(provider output, now, previous bundle). No trade authority, no wall clock of
its own, no networking (that lives in the provider).

F-2/H4 correction: the bundle's authoritative ``as_of`` is the EFFECTIVE calendar
freshness — an upstream generated timestamp when present, otherwise the instant this
exact CONTENT VERSION was first seen (pinned across repeat downloads and restart),
gated by a passing COVERAGE check. It is NEVER the bare download/fetch time, so
re-fetching identical stale content cannot keep it authorization-eligible; unchanged
content ages out through the existing compliance freshness rule. If freshness cannot
be established the acquirer raises and the caller preserves last-known-good.
"""

from __future__ import annotations

import hashlib

from ..bridge import serialize
from . import freshness, normalize
from .contract import (COMPLETENESS_CROSS_VERIFIED, COMPLETENESS_SOURCE_DECLARED,
                       COMPLETENESS_UNESTABLISHED, SCHEMA_VERSION, AcquisitionError,
                       Reason)

_HIGH_TOKENS = frozenset({"HIGH"})


def _as_previous(previous):
    """Normalize the previous-state input into ``{content_hash, content_first_seen}``.

    Accepts: a persisted bundle dict (with a ``provenance`` sub-dict), a bare
    provenance dict, a plain content-hash string (back-compat), or None."""
    if previous is None:
        return {}
    if isinstance(previous, str):
        return {"content_hash": previous, "content_first_seen": None}
    if isinstance(previous, dict):
        prov = previous.get("provenance") if isinstance(previous.get("provenance"), dict) else previous
        return {"content_hash": prov.get("content_hash"),
                "content_first_seen": prov.get("content_first_seen")}
    return {}


def _content_hash(events):
    """Deterministic fingerprint of the normalized calendar content (excludes
    volatile provenance/timestamps) — provenance/diagnostic evidence only."""
    payload = serialize.canonical_json([
        {"event_id": e["event_id"], "event_timestamp": e["event_timestamp"],
         "impact": e["impact"], "currency": e["currency"],
         "event_name": e["event_name"]} for e in events])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class CalendarAcquirer:
    """Turns a provider's raw calendar into a verified, coverage-checked,
    provenance-stamped bundle. ``corroborators`` optionally upgrades completeness to
    cross-verified (architectural seam for F-3; empty by default)."""

    def __init__(self, provider, cfg, *, corroborators=None):
        self.provider = provider
        self.cfg = cfg
        self.corroborators = list(corroborators or [])

    def refresh(self, now, previous=None):
        """Acquire + validate + normalize into a bundle dict, or raise
        :class:`AcquisitionError` (fail closed — never a partial/unverified-fresh
        bundle).

        ``previous`` is the last successfully-persisted bundle's provenance (or the
        bundle itself), supplying ``content_hash`` / ``content_first_seen`` so the
        effective freshness is pinned to the content VERSION rather than the download
        time (H4). It is read from the durable bundle on disk, so it survives restart.
        Back-compat: a bare previous-hash string is also accepted."""
        prev = _as_previous(previous)
        raw = self.provider.fetch(now)
        freshness.check_download_sanity(raw, now, self.cfg)
        events, warnings = normalize.normalize_events(raw)
        if not events:
            raise AcquisitionError(Reason.EMPTY_PAYLOAD, {"event_count": 0})

        completeness = (COMPLETENESS_SOURCE_DECLARED if raw.complete is True
                        else COMPLETENESS_UNESTABLISHED)
        if self.corroborators:
            events, completeness = self._cross_verify(events, now, completeness)

        # content version identity is computed BEFORE freshness so the effective
        # as_of can be pinned to when THIS content was first seen (H4).
        content_hash = _content_hash(events)
        effective, cov_start, cov_end, basis, cov_verified, first_seen = \
            freshness.establish_effective_as_of(raw, events, now, self.cfg,
                                                content_hash=content_hash, previous=prev)

        prev_hash = prev.get("content_hash")
        content_changed = (None if prev_hash is None else content_hash != prev_hash)
        high_count = sum(1 for e in events if str(e["impact"]).upper() in _HIGH_TOKENS)

        as_of = serialize.iso_utc(effective)          # = content-first-seen (or trusted source_as_of)
        first_seen_iso = serialize.iso_utc(first_seen)
        provenance = {
            "source_name": raw.source_name,
            "source_identifier": raw.source_identifier,
            "source_as_of": serialize.iso_utc(raw.source_as_of) if raw.source_as_of else None,
            "fetched_at": serialize.iso_utc(raw.fetched_at),
            "normalized_at": serialize.iso_utc(now),
            "bundle_written_at": serialize.iso_utc(now),
            "effective_calendar_as_of": as_of,
            "bundle_as_of": as_of,
            # H4 content-observation lineage (persisted; survives restart)
            "content_first_seen": first_seen_iso,
            "content_last_seen": serialize.iso_utc(now),
            "coverage_start": serialize.iso_utc(cov_start),
            "coverage_end": serialize.iso_utc(cov_end),
            "coverage_basis": basis,
            "coverage_verified": bool(cov_verified),
            "provider_version": raw.provider_version,
            "schema_version": SCHEMA_VERSION,
            "completeness": completeness,
            "single_source_completeness_not_provable": completeness != COMPLETENESS_CROSS_VERIFIED,
            "content_hash": content_hash,
            "content_changed": content_changed,
            "freshness_basis": ("source_as_of" if raw.source_as_of is not None
                                else "content_first_seen"),
            "event_count": len(events),
            "high_event_count": high_count,
            "trusted_source": bool(raw.trusted),
            "normalization_warnings": sorted(set(warnings)),
        }
        bundle = {
            "schema_version": SCHEMA_VERSION,
            "as_of": as_of,                            # consumed by compliance/news.py
            "verified": bool(raw.trusted),
            "provenance": provenance,
            "events": events,
        }
        return serialize.with_integrity_digest(bundle)

    def _cross_verify(self, events, now, completeness):
        corroborated = set()
        for c in self.corroborators:
            raw = c.fetch(now)
            freshness.check_download_sanity(raw, now, self.cfg)
            other, _ = normalize.normalize_events(raw)
            corroborated |= {e["source_event_key"] for e in other}
        if corroborated:
            for e in events:
                if e["source_event_key"] in corroborated:
                    e["cross_verified"] = True
            completeness = COMPLETENESS_CROSS_VERIFIED
        return events, completeness
