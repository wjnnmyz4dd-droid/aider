"""Experiment provenance (Phase 9B) — deterministic, read-only.

Records the git commit, strategy version, dataset id, parameters, configuration,
an INJECTED timestamp (never a wall clock), results, and metrics for every
experiment. The git commit is read from the local ``.git`` tree (no subprocess, no
networking). Reuses the accepted bridge serializer for canonical JSON + hashing.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from ..bridge import serialize

_REPO_ROOT = Path(__file__).resolve().parents[2]        # .../aider


class ProvenanceError(RuntimeError):
    pass


def git_head(repo_root=None):
    """Return the current commit sha by reading ``.git`` directly (deterministic;
    no subprocess, no network). None if unavailable."""
    root = Path(repo_root) if repo_root else _REPO_ROOT
    head = root / ".git" / "HEAD"
    try:
        text = head.read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return None
    if text.startswith("ref:"):
        ref = text.split(" ", 1)[1].strip()
        try:
            return (root / ".git" / ref).read_text(encoding="utf-8").strip()
        except (OSError, ValueError):
            # packed-refs fallback
            try:
                for line in (root / ".git" / "packed-refs").read_text(encoding="utf-8").splitlines():
                    if line.endswith(" " + ref) or line.endswith("\t" + ref):
                        return line.split()[0]
            except (OSError, ValueError):
                return None
            return None
    return text or None


def strategy_version():
    """The frozen strategy version, read from the engine module (read-only; the
    authoritative owner). None if the module cannot be loaded."""
    try:
        from ..producer.strategy_adapter import load_engine_module
        return getattr(load_engine_module(), "STRATEGY_VERSION", None)
    except Exception:
        return None


@dataclass(frozen=True)
class ExperimentRecord:
    """Immutable, content-addressed provenance for one experiment run."""
    experiment_id: str
    dataset_id: str
    parameters: dict
    config: dict
    timestamp: str                      # INJECTED (ISO-8601); never a wall clock
    results: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)
    git_commit: str = None
    strategy_version_str: str = None

    @classmethod
    def build(cls, experiment_id, *, dataset_id, parameters, config, timestamp,
              results=None, metrics=None, repo_root=None):
        if not isinstance(timestamp, str) or not timestamp:
            raise ProvenanceError("timestamp must be an injected ISO-8601 string")
        return cls(
            experiment_id=experiment_id, dataset_id=dataset_id,
            parameters=dict(parameters or {}), config=dict(config or {}),
            timestamp=timestamp, results=dict(results or {}),
            metrics=dict(metrics or {}), git_commit=git_head(repo_root),
            strategy_version_str=strategy_version())

    def record_id(self):
        """Content-addressed 16-hex id over the full record (deterministic)."""
        payload = serialize.canonical_json({
            "experiment_id": self.experiment_id, "dataset_id": self.dataset_id,
            "parameters": self.parameters, "config": self.config,
            "timestamp": self.timestamp, "results": self.results,
            "metrics": self.metrics, "git_commit": self.git_commit,
            "strategy_version": self.strategy_version_str})
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def to_dict(self):
        d = {
            "kind": "experiment_record", "experiment_id": self.experiment_id,
            "dataset_id": self.dataset_id, "parameters": self.parameters,
            "config": self.config, "timestamp": self.timestamp,
            "results": self.results, "metrics": self.metrics,
            "git_commit": self.git_commit, "strategy_version": self.strategy_version_str,
        }
        d["record_id"] = self.record_id()
        return d
