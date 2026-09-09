"""Reproducible research REPORT SUITE (Phase 9E) — deterministic, read-only ORCHESTRATOR.

This is an ORCHESTRATION layer with ZERO new metric ownership and ZERO trading
authority. It assembles the canonical machine-readable research artifacts by DELEGATING
every calculation to its existing single owner:

  * lifecycle dataset (by signal_id)     -> research.lifecycle (sole join owner)
  * expectancy / drawdown / equity / R    -> research.portfolio (sole calculators)
  * session / symbol / holding / FTMO     -> research.reporting
  * feature stats / correlation / OOS /
    robustness / sample-size / A-D decision -> research.calibration (PR-3Q)
  * Monte Carlo sequence risk             -> research.montecarlo (seeded)
  * walk-forward stability                -> research.walk_forward
  * execution cost                        -> research.execution_analytics
  * git head / strategy version           -> research.provenance

It re-derives none of the above. It owns no strategy/compliance/sizing/PM/EA authority,
places/sizes/blocks no trade, and touches no broker. Every report carries reproducibility
metadata (Section AC): dataset hash, strategy version, code commit, date range, sessions,
symbols, sample count, seed, and injected timestamp — identical inputs -> identical output.

Fail-open-to-honesty: with no realized outcomes (a fresh/DEMO system) each realized-data
report degrades to an explicit status (NO_REALIZED_DATASET / INSUFFICIENT / UNAVAILABLE)
— it NEVER fabricates edge, and NEVER presents synthetic or tiny-sample results as
validated. Production does not import or depend on this module; deleting research/
changes production behaviour in no way.
"""

from __future__ import annotations

import hashlib

from ..bridge import serialize
from . import (calibration, execution_analytics, lifecycle, montecarlo, portfolio,
               provenance, reporting, walk_forward)

SUITE_VERSION = "session_edge_report_suite.v1"

# Minimum realized trades before a report is more than descriptive. Reuses the research
# sample-size discipline (never a live trading gate).
MONTE_CARLO_MIN = calibration.MIN_CLOSED_FOR_EXPLORATORY      # 30
ROBUSTNESS_MIN = calibration.MIN_CLOSED_FOR_EXPLORATORY       # 30

NO_REALIZED = "NO_REALIZED_DATASET"
UNAVAILABLE = "UNAVAILABLE"
INSUFFICIENT = calibration.INSUFFICIENT


def dataset_hash(rows):
    """Deterministic content hash of the research dataset (reproducibility, Section AC)."""
    return hashlib.sha256(serialize.canonical_json(rows).encode("utf-8")).hexdigest()[:16]


def _provenance(*, timestamp, ds_hash, sessions, symbols, n_rows, n_closed, seed,
                repo_root=None):
    return {
        "suite_version": SUITE_VERSION,
        "dataset_hash": ds_hash,
        "strategy_version": provenance.strategy_version(),
        "code_commit": provenance.git_head(repo_root),
        "timestamp": timestamp,
        "sessions": list(sessions) if sessions is not None else None,
        "symbols": list(symbols) if symbols is not None else None,
        "sample_rows": n_rows,
        "sample_closed": n_closed,
        "seed": seed,
    }


def _date_range(closed_trades):
    ts = [t.get("timestamp") for t in closed_trades if t.get("timestamp")]
    ts = sorted(str(x) for x in ts)
    return {"from": (ts[0] if ts else None), "to": (ts[-1] if ts else None)}


def build(instructions, memory=None, *, timestamp, seed=12345, sessions=None,
          symbols=None, account_state=None, profile=None, ftmo_cfg=None, fills=None,
          engine=None, df=None, symbol=None, window=200, step=50, mc_sims=1000,
          rolling_window=20, bins=4, repo_root=None):
    """Return the full named report suite (Section Z) as one deterministic dict. All
    reports delegate to existing owners; realized-data reports degrade to an explicit
    status when the dataset is empty/insufficient. Never raises on empty inputs."""
    rows = lifecycle.quality_dataset(instructions, memory)
    closed = lifecycle.load_closed_trades(memory) if memory is not None else []
    ds_hash = dataset_hash(rows)
    n_rows, n_closed = len(rows), len(closed)
    prov = _provenance(timestamp=timestamp, ds_hash=ds_hash, sessions=sessions,
                       symbols=symbols, n_rows=n_rows, n_closed=n_closed, seed=seed,
                       repo_root=repo_root)

    suite = {"suite_version": SUITE_VERSION, "provenance": prov}

    # -- research_dataset: the canonical lifecycle view + explicit denominators ------
    suite["research_dataset"] = {
        "provenance": prov,
        "dataset_hash": ds_hash,
        "row_count": n_rows,
        "closed_count": n_closed,
        "candidate_observations": n_rows,          # authorized instructions observed
        "closed_trades": n_closed,                 # realized outcomes (subset)
        "date_range": _date_range(closed),
        "fact_availability": dict(lifecycle.FACT_AVAILABILITY),
        "rows": rows,
    }

    # -- baseline_report (Section S): descriptive stats of the realized base strategy --
    if closed:
        suite["baseline_report"] = {
            "provenance": prov, "status": "OK",
            "overall": portfolio.summary(closed),
            "by_session": reporting.session_performance(closed),
            "by_symbol": reporting.pair_performance(closed),
        }
    else:
        suite["baseline_report"] = {"provenance": prov, "status": NO_REALIZED,
                                    "detail": "no realized outcomes recorded yet"}

    # -- feature_report + calibration_report (Section J/P/Q): delegate to PR-3Q --------
    cal = calibration.calibration_report(instructions, memory, timestamp=timestamp,
                                         bins=bins, repo_root=repo_root)
    suite["calibration_report"] = cal
    suite["feature_report"] = {
        "provenance": prov,
        "sample_size_classification": cal.get("sample_size_classification"),
        "feature_distributions": cal.get("feature_distributions"),
        "monotonicity": cal.get("monotonicity"),
        "correlation_matrix": cal.get("correlation_matrix"),
        "redundancy_flags": cal.get("redundancy_flags"),
        "out_of_sample": cal.get("out_of_sample"),
    }

    # -- session_report / symbol_report (Sections T/U) --------------------------------
    suite["session_report"] = ({"provenance": prov, "status": "OK",
                                "by_session": reporting.session_performance(closed)}
                               if closed else
                               {"provenance": prov, "status": NO_REALIZED})
    suite["symbol_report"] = ({"provenance": prov, "status": "OK",
                               "by_symbol": reporting.pair_performance(closed)}
                              if closed else
                              {"provenance": prov, "status": NO_REALIZED})

    # -- drawdown_report (Section J.5/6): equity, max DD, DD duration, rolling ---------
    if closed:
        eq = portfolio.equity_curve(closed)
        suite["drawdown_report"] = {
            "provenance": prov, "status": "OK",
            "max_drawdown": portfolio.max_drawdown(eq),
            "max_drawdown_duration": portfolio.drawdown_duration(eq),
            "rolling_expectancy": portfolio.rolling_expectancy(closed, rolling_window),
            "rolling_hit_rate": portfolio.rolling_hit_rate(closed, rolling_window),
            "final_equity": eq[-1] if eq else 0.0,
        }
    else:
        suite["drawdown_report"] = {"provenance": prov, "status": NO_REALIZED}

    # -- monte_carlo_report (Section M): seeded bootstrap of realized R ----------------
    r_multiples = [t["r_multiple"] for t in closed
                   if isinstance(t.get("r_multiple"), (int, float))
                   and not isinstance(t.get("r_multiple"), bool)]
    if len(r_multiples) >= MONTE_CARLO_MIN:
        try:
            mc = montecarlo.bootstrap(r_multiples, sims=mc_sims, seed=seed)
            suite["monte_carlo_report"] = {"provenance": prov, "status": "OK",
                                           "n_trades": len(r_multiples), "result": mc}
        except montecarlo.MonteCarloError as exc:
            suite["monte_carlo_report"] = {"provenance": prov, "status": UNAVAILABLE,
                                           "detail": str(exc)}
    else:
        suite["monte_carlo_report"] = {
            "provenance": prov, "status": INSUFFICIENT,
            "detail": f"{len(r_multiples)} realized trades < {MONTE_CARLO_MIN} "
                      f"(sequence-risk analysis withheld; IID not assumed)"}

    # -- robustness_report (Section L): neighboring-threshold survival per fact --------
    if n_closed >= ROBUSTNESS_MIN:
        ds = calibration.build_dataset(instructions, memory)
        suite["robustness_report"] = {
            "provenance": prov, "status": "OK",
            "by_fact": {f: calibration.robustness(ds, f) for f in calibration.ANALYSIS_FACTS}}
    else:
        suite["robustness_report"] = {
            "provenance": prov, "status": INSUFFICIENT,
            "detail": f"{n_closed} closed < {ROBUSTNESS_MIN}"}

    # -- walk_forward_report (Section K): only when a historical bar dataset is given --
    if engine is not None and df is not None and symbol is not None:
        wf = walk_forward.walk_forward(engine, df, symbol, window=window, step=step)
        suite["walk_forward_report"] = {"provenance": prov, "status": "OK", "windows": wf}
    else:
        suite["walk_forward_report"] = {
            "provenance": prov, "status": UNAVAILABLE,
            "detail": "no historical bar dataset supplied (engine/df/symbol)"}

    # -- execution + FTMO risk (Sections V/W): delegate; optional inputs ---------------
    suite["execution_report"] = ({"provenance": prov, "status": "OK",
                                  "execution": execution_analytics.summary(fills)}
                                 if fills else
                                 {"provenance": prov, "status": UNAVAILABLE,
                                  "detail": "no recorded fills supplied"})
    if account_state is not None and profile is not None and ftmo_cfg is not None:
        suite["ftmo_risk_report"] = {"provenance": prov, "status": "OK",
                                     "ftmo": reporting.ftmo_report(account_state, profile, ftmo_cfg)}
    else:
        suite["ftmo_risk_report"] = {"provenance": prov, "status": UNAVAILABLE,
                                     "detail": "no account_state/profile/ftmo_cfg supplied"}
    return suite


def write_suite(output_dir, suite):
    """Write each named report as a deterministic JSON artifact under ``output_dir``.
    Outputs only — production never reads these; their absence changes nothing."""
    from pathlib import Path
    from ..bridge.atomic import atomic_write_text
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, report in suite.items():
        if not isinstance(report, dict):
            continue
        p = out / (name + ".json")
        atomic_write_text(p, serialize.canonical_json(report))
        written.append(str(p))
    return written
