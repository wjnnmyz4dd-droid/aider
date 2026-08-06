"""Experiment manager & toolbox (Phase 9B) — deterministic, read-only.

Runs a research callable and AUTOMATICALLY records full provenance (git commit,
strategy version, dataset, parameters, config, injected timestamp, results,
metrics) as an immutable, content-addressed record persisted to a jsonl. The
experiment body must be a pure function of its inputs (no wall clock, no unseeded
randomness) so runs are reproducible. It has ZERO trade authority and performs no
networking.
"""

from __future__ import annotations

from pathlib import Path

from ..bridge import serialize
from ..bridge.atomic import append_line_fsync
from .provenance import ExperimentRecord


class Experiment:
    """A named, reproducible experiment: ``fn(parameters, config) -> (results,
    metrics)``. ``fn`` must be deterministic (pure over its inputs)."""

    def __init__(self, experiment_id, fn, *, dataset_id, parameters=None, config=None):
        self.experiment_id = experiment_id
        self.fn = fn
        self.dataset_id = dataset_id
        self.parameters = dict(parameters or {})
        self.config = dict(config or {})

    def run(self, timestamp, repo_root=None):
        """Execute the experiment at an INJECTED timestamp; return its provenance
        record dict. Deterministic given identical inputs (record_id excludes only
        the injected timestamp's effect via canonical hashing of all fields)."""
        results, metrics = self.fn(self.parameters, self.config)
        rec = ExperimentRecord.build(
            self.experiment_id, dataset_id=self.dataset_id, parameters=self.parameters,
            config=self.config, timestamp=timestamp, results=dict(results or {}),
            metrics=dict(metrics or {}), repo_root=repo_root)
        return rec


class ExperimentManager:
    """Persists experiment provenance records to an append-only jsonl (atomic,
    fsync'd). Read-only w.r.t. production; writes only to the research output path."""

    def __init__(self, output_path):
        self.output_path = Path(output_path)

    def run(self, experiment, timestamp, repo_root=None):
        rec = experiment.run(timestamp, repo_root=repo_root).to_dict()
        append_line_fsync(self.output_path, serialize.canonical_json(rec))
        return rec

    def read_all(self):
        out = []
        try:
            for line in self.output_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    ok, obj = serialize.loads(line)
                    if ok:
                        out.append(obj)
        except (FileNotFoundError, OSError):
            pass
        return out


# --------------------------------------------------------------------------- #
# toolbox helpers (compose the analytics/walk-forward/MC modules deterministically)
# --------------------------------------------------------------------------- #
def parameter_study(engine_factory, df, symbol, param_grid, *, window, step):
    """Run walk-forward for each parameter set (deterministic). ``engine_factory``
    builds the FROZEN engine with a given config (read-only). Returns per-param
    stability of instruction counts."""
    from . import walk_forward as wf
    out = {}
    for i, params in enumerate(param_grid):
        engine = engine_factory(params)
        results = wf.walk_forward(engine, df, symbol, window=window, step=step)
        out[serialize.canonical_json(params)] = wf.stability(
            [r["instruction_count"] for r in results])
    return out


def historical_replay(engine, df, symbol):
    """Deterministic full-history replay of the frozen engine over ``df`` (one
    window = the whole dataset). Read-only; returns the engine's instruction count
    + last weight, never an order."""
    from . import walk_forward as wf
    return wf.run_engine_on_window(engine, df, symbol)
