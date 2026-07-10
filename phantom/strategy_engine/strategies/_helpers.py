"""Shared, private helpers used by more than one concrete strategy --
kept here once rather than duplicated per-file (CLAUDE.md §6)."""

from __future__ import annotations

from typing import Optional

from phantom.evidence_engine.models import ComponentScore, EvidenceReport


def component(report: EvidenceReport, name: str) -> Optional[ComponentScore]:
    return next((c for c in report.score.components if c.name == name), None)


def clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


__all__ = ["component", "clamp"]
