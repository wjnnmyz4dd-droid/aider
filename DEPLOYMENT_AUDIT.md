# Deployment Audit — `DEPLOYMENT_PACKAGE/`

**Status: HISTORICAL.** `DEPLOYMENT_PACKAGE/` was removed from this
repository once the Python `deployment_windows/` installer (with its own
`RELEASE_MANIFEST.json`, generated fresh per build) fully superseded it.
This document is a point-in-time record of that now-removed directory's
contents and is not describing anything present in the repository today.

Complete file listing of the rebuilt `DEPLOYMENT_PACKAGE/`, generated
fresh from the current repository state (source commit recorded in
`DEPLOYMENT_PACKAGE/VERSION.txt`). The previous package (14 packages,
157 files, built at commit `a90f7c6`) was deleted in full and this
package was regenerated from scratch — nothing here is patched-over
leftovers.

**Total files in this package: 182**

---

## `DEPLOYMENT_PACKAGE/` (root)

- VERSION.txt
- requirements.txt

## `DEPLOYMENT_PACKAGE/config/`

- dev.env.template
- live.env.template
- paper.env.template

## `DEPLOYMENT_PACKAGE/scripts/`

- start_phantom.bat
- start_phantom.py
- stop_phantom.bat

## `DEPLOYMENT_PACKAGE/phantom_pipeline/`

- __init__.py
- orchestrator.py

## `DEPLOYMENT_PACKAGE/phantom_pipeline/analytics/`

- __init__.py
- attribution.py
- checks.py
- config.py
- engine.py
- logging_sink.py
- metrics.py
- models.py
- performance.py
- store.py

## `DEPLOYMENT_PACKAGE/phantom_pipeline/compliance_engine/`

- __init__.py
- checks.py
- config.py
- engine.py
- logging_sink.py
- metrics.py
- models.py
- state_store.py

## `DEPLOYMENT_PACKAGE/phantom_pipeline/dashboard/`

- __init__.py
- config.py
- engine.py
- logging_sink.py
- metrics.py
- models.py
- prometheus_adapter.py
- prometheus_port.py

## `DEPLOYMENT_PACKAGE/phantom_pipeline/data_pipeline/`

- __init__.py
- bars.py
- config.py
- gaps.py
- health.py
- historical.py
- ingest.py
- logging_sink.py
- market_data_adapter.py
- metrics.py
- models.py
- normalize.py
- pipeline.py
- quality.py
- replay.py
- trace.py

## `DEPLOYMENT_PACKAGE/phantom_pipeline/deployment/`

- __init__.py
- backup_manager.py
- config_manager.py
- deployment_manager.py
- deployment_validator.py
- logging_manager.py
- models.py
- monitoring.py
- service_manager.py

## `DEPLOYMENT_PACKAGE/phantom_pipeline/execution_validator/`

- __init__.py
- checks.py
- config.py
- engine.py
- idempotency_store.py
- logging_sink.py
- metrics.py
- models.py

## `DEPLOYMENT_PACKAGE/phantom_pipeline/knowledge/` *(new this rebuild — `ADR-020`)*

- __init__.py
- config.py
- embeddings.py
- engine.py
- ingestion.py
- logging_sink.py
- memory.py
- metrics.py
- models.py
- retriever.py
- search.py
- vector_store.py

## `DEPLOYMENT_PACKAGE/phantom_pipeline/mt5_bridge/`

- __init__.py
- broker_adapter.py
- checks.py
- config.py
- engine.py
- execution_id.py
- idempotency_store.py
- logging_sink.py
- metrics.py
- models.py
- mt5_adapter.py

## `DEPLOYMENT_PACKAGE/phantom_pipeline/paper_trading/`

- __init__.py
- account_tracker.py
- forward_test_engine.py
- paper_trading_runner.py
- prop_firm_validator.py
- report_generator.py
- session_manager.py
- validation_dashboard.py

## `DEPLOYMENT_PACKAGE/phantom_pipeline/position_manager/`

- __init__.py
- checks.py
- config.py
- engine.py
- execution_id.py
- logging_sink.py
- metrics.py
- models.py
- state_store.py

## `DEPLOYMENT_PACKAGE/phantom_pipeline/research_desk/` *(new this rebuild — `ADR-021`)*

- __init__.py
- config.py
- dashboard.py
- debate.py
- explainable.py
- institutional_review.py
- logging_sink.py
- market_research.py
- metrics.py
- models.py
- strategy_research.py
- trade_journal.py
- trade_thesis.py

## `DEPLOYMENT_PACKAGE/phantom_pipeline/risk_engine/`

- __init__.py
- config.py
- constraints.py
- engine.py
- logging_sink.py
- metrics.py
- models.py

## `DEPLOYMENT_PACKAGE/phantom_pipeline/scanner/`

- __init__.py
- composite.py
- config.py
- logging_sink.py
- metrics.py
- models.py
- quality.py
- scanner.py
- session.py
- structure.py
- swing.py
- trend.py
- volatility.py

## `DEPLOYMENT_PACKAGE/phantom_pipeline/scoring_engine/`

- __init__.py
- config.py
- engine.py
- logging_sink.py
- metrics.py
- models.py
- ranking.py
- registry.py
- rule.py

## `DEPLOYMENT_PACKAGE/phantom_pipeline/scoring_engine/rules/`

- __init__.py
- directional_clarity.py
- evidence_count.py
- reason_code_presence.py
- supporting_observation_count.py

## `DEPLOYMENT_PACKAGE/phantom_pipeline/strategy_engine/`

- __init__.py
- config.py
- engine.py
- logging_sink.py
- metrics.py
- models.py
- playbook.py
- registry.py

## `DEPLOYMENT_PACKAGE/phantom_pipeline/strategy_engine/playbooks/`

- __init__.py
- liquidity_reversal.py
- orb.py
- range_reversal.py
- session_breakout.py
- trend_continuation.py

## `DEPLOYMENT_PACKAGE/phantom_pipeline/watchdog/`

- __init__.py
- alerting.py
- checks.py
- config.py
- engine.py
- logging_sink.py
- metrics.py
- models.py
- real_recovery_executor.py
- recovery_executor.py
- state_store.py
- trace.py

---

## Package count reconciliation

18 packages counted above under `phantom_pipeline/` in this listing (16
top-level + 2 nested sub-packages `scoring_engine/rules` and
`strategy_engine/playbooks`), matching the current source
`phantom_pipeline/` exactly, file for file — verified in
`FINAL_DEPLOYMENT_READINESS_REPORT.md` §3 via `diff -rq`.

## Explicitly excluded from this package (confirmed absent)

`tests/`, `docs/adr/`, `docs/plans/`, `docs/architecture/`,
`docs/research/`, `AUDIT.md`, `IMPLEMENTATION_PLAN.md`,
`VALIDATION_MATRIX.md`, `CLAUDE.md`, `.claude/`, `phantom/` (legacy),
`phantom_institutional.py`, `run_demo.py`, `README.md`, `RELEASE.md`,
`ARCHITECTURE.md`, `INTERFACE_SPECIFICATION.md`, `CHANGELOG.md`, and this
repository's own `.git/` history.
